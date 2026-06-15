# Problems & Lessons

Running log of every problem hit during this build, what we tried, and what we concluded. New entries go at the top. Each problem gets an ID so it can be referenced from PRs and code comments.

---

## P-007 — dbt CI failed in 7s: requirements.txt missing, cache-dependency-path broke setup-python

**Phase:** Phase 1 (dbt foundation)
**Date:** 2026-06-15

### Problem
The `dbt_ci.yml` workflow failed immediately with:
```
No file in /home/runner/work/Go-To-Market-Analytics matched to
[dbt/gtm_analytics_dbt/requirements*.txt or **/pyproject.toml],
make sure you have checked out the target repository
```
The `setup-python` step uses `cache: pip` with `cache-dependency-path: dbt/gtm_analytics_dbt/requirements*.txt` to fingerprint the pip cache. GitHub Actions evaluates that glob before running any other step — if the file doesn't exist, the step fails in seconds and the entire job dies before dbt is even installed.

The dbt project was scaffolded without a `requirements.txt` because the original intent was to hardcode `pip install dbt-bigquery` directly in the workflow YAML. That's the root cause: the cache path referenced a file that was never created.

### Fix
1. Created `dbt/gtm_analytics_dbt/requirements.txt` with `dbt-bigquery>=1.8.0`.
2. Changed both `dbt_ci.yml` and `freshness.yml` install steps from `pip install dbt-bigquery` to `pip install -r requirements.txt` — version is now controlled from one file, not scattered across workflow YAML.

### Lesson
Always create `requirements.txt` before writing a workflow that references it in `cache-dependency-path`. The cache path glob is evaluated at job startup — a missing file kills the job before a single meaningful step runs. Also: never hardcode package versions in workflow YAML. Pin them in `requirements.txt` so upgrades are a one-line change in one file, not a hunt across multiple workflow files.

---

## P-005 — dbt profiles.yml: keyfile path breaks CI; use service-account-json with env_var()

**Phase:** Phase 1 (dbt foundation)
**Date:** 2026-06-15

### Problem
The scaffolded `profiles.yml` used `keyfile: <path-to-gcp-service-account-json>` — a static file path. This works on a developer machine where the file exists, but breaks in CI because:
- The runner has no access to a local keyfile
- Hardcoded paths make the profile environment-specific and non-portable
- The project placeholders `<your-gcp-project-id>` were never replaced, so `dbt parse` would fail immediately

### What we did
Replaced the `keyfile` approach with `method: service-account-json` for the `prod` target and `method: oauth` for `dev`:

```yaml
prod:
  type: bigquery
  method: service-account-json
  project: "{{ env_var('DBT_BQ_PROJECT', 'obito-492802') }}"
  keyfile_json: "{{ env_var('GCP_SERVICE_ACCOUNT_JSON') | fromjson }}"
```

`GCP_SERVICE_ACCOUNT_JSON` is the same single JSON secret already used by the dlt pipeline — one secret, both tools.

The `dev` target uses `method: oauth` so developers authenticate once with `gcloud auth application-default login` and never touch a keyfile.

### Lesson
Never scaffold a `profiles.yml` with `keyfile:` and commit it. It will always break CI. The correct pattern for BigQuery in any CI/CD environment is `method: service-account-json` + `env_var()`. For GCP-native compute (Cloud Functions, Cloud Run), use `method: oauth` — ADC handles it with zero config.

---

## P-006 — dbt CI: dbt build beats dbt run + dbt test; state:modified+ beats full rebuild

**Phase:** Phase 1 (dbt foundation)
**Date:** 2026-06-15

### Problem
The naive CI pattern (`dbt run` then `dbt test`) has two inefficiencies:
1. Running all models on every PR rebuild is slow and wastes BigQuery slot time as the project grows.
2. Separating `run` and `test` means seeds are often forgotten and source freshness is never checked in PR CI.

### What we did
**`dbt build`** replaces `dbt run + dbt test`. It runs seeds, models, snapshots, and tests in dependency order in a single command. Nothing gets skipped.

**`--select state:modified+ --defer --state ./target`** limits the build to only models changed in the PR and all their downstream dependents. Unmodified upstream models are deferred — dbt reads their results from the prod manifest instead of rebuilding them. This keeps PR CI fast regardless of project size.

Two separate workflows, not one:
- `dbt_ci.yml` — triggers on code changes, runs the slim build
- `freshness.yml` — nightly cron, runs `dbt source freshness`, alerts Slack on failure

### Lesson
From the first PR: use `dbt build --select state:modified+ --defer`. Full rebuilds on every PR become impractical once the project has more than ~20 models. The `--defer` flag is the key — it lets you test a change in isolation without rebuilding the entire lineage. Split freshness into its own nightly workflow so it does not block PR CI.

---

## P-004 — BigQuery credentials: single JSON secret beats five separate fields

**Phase:** Phase 0 (dlt ingestion — Attio)
**Date:** 2026-06-15

### Problem
Initially the CI workflow passed BigQuery service account credentials as five separate environment variables: `BQ_PRIVATE_KEY`, `BQ_PRIVATE_KEY_ID`, `BQ_CLIENT_EMAIL`, `BQ_CLIENT_ID`, `BQ_TOKEN_URI`. This is fragile because the RSA private key contains literal newlines which are frequently mangled when a multi-line string is injected as a shell environment variable. The result is a silent auth failure: dlt loads without error but BigQuery rejects the key signature.

### Decision
Pass the full service account JSON as **one secret** (`GCP_SERVICE_ACCOUNT_JSON`) and set:
```
DESTINATION__BIGQUERY__CREDENTIALS=<full JSON string>
```
dlt's BigQuery adapter accepts a JSON string for the credentials field and parses it internally — no shell escaping, no newline issues, one secret to rotate.

### Cloud Functions: no BigQuery credentials needed at all
When the pipeline runs as a Cloud Function, the function's attached service account authenticates to BigQuery automatically via Application Default Credentials (ADC). `DESTINATION__BIGQUERY__CREDENTIALS` is not set. Only the Attio token is needed as an env var. This is the correct pattern for any GCP-native deployment.

### Changes made
- `dlt_ci.yml`: replaced five `BQ_*` env vars with `DESTINATION__BIGQUERY__CREDENTIALS: ${{ secrets.GCP_SERVICE_ACCOUNT_JSON }}`.
- `attio_pipeline.py`: added `attio_sync(request)` Cloud Function entry point with ADC note.
- `dlt/README.md`: documented both the CI (JSON credential) path and the Cloud Function (ADC) path.

### Lesson
Never split a service account key into separate env vars for CI. The RSA private key is a multi-line PEM block; shells and YAML parsers corrupt it. Always pass the JSON blob whole. For GCP-native compute (Cloud Functions, Cloud Run, GKE), don't pass credentials at all — attach the right service account and let ADC handle it.

---

## P-003 — secrets.toml replaced by environment variables

**Phase:** Phase 0 (dlt ingestion — Attio)
**Date:** 2026-06-15

### Problem
Initially configured dlt credentials via `.dlt/secrets.toml`. This approach has two risks:
- The file must be created manually on every machine and in every CI environment, creating an easy path to accidental commits.
- Writing the file from CI (echoing secrets into a shell heredoc) is fragile and exposes secret values in shell history and CI logs.

### Decision
Use dlt's native environment variable support instead. dlt maps env vars to config sections using `__` as the separator (all uppercase):

| secrets.toml key | Environment variable |
|---|---|
| `[attio_source] api_token` | `SOURCES__ATTIO_SOURCE__API_TOKEN` |
| `[destination.bigquery.credentials] private_key` | `DESTINATION__BIGQUERY__CREDENTIALS__PRIVATE_KEY` |
| `[destination.bigquery.credentials] client_email` | `DESTINATION__BIGQUERY__CREDENTIALS__CLIENT_EMAIL` |

In GitHub Actions, secrets are passed directly as `env:` entries on each job — no file is written, no heredoc, no shell escaping issues.

### Changes made
- Deleted `dlt/.dlt/secrets.toml`.
- Rewrote `.github/workflows/dlt_ci.yml` to pass all credentials as `env:` vars.
- Updated `dlt/README.md` with the full env var reference table.

### Lesson
For any dlt project in a CI/CD context, prefer environment variables over `secrets.toml`. The `secrets.toml` file is useful for solo local dev but does not scale to teams or automation. The `__` separator convention is easy to remember: take the TOML path, replace dots and brackets with `__`, uppercase everything.

---

## P-002 — Cube images blocked removal by stopped containers

**Phase:** Pre-Phase 0 (environment cleanup)
**Date:** 2026-06-14

### Problem
Running `docker rmi cubejs/cube:latest cubejs/cubestore:latest` failed:
```
Error response from daemon: conflict: unable to remove repository reference
"cubejs/cube:latest" — container 0ff683d48293 is using its referenced image
```
Two-month-old stopped containers (`cube_saas-cube_api-1`, `cube_saas-cubestore_worker_1-1`, `cube_saas-cubestore_router-1`) from a previous `saas/` project were still holding references to the images.

### Iterations
1. **Tried:** `docker rmi cubejs/cube:latest cubejs/cubestore:latest` → blocked by container references.
2. **Fixed:** Removed the stopped containers first (`docker rm <names>`), then the image removal succeeded cleanly.

### Lesson
Always run `docker ps -a` (not just `docker ps`) before attempting image removal. Stopped containers still hold image references. Check what project they belong to before removing them — in this case they were from `saas/`, unrelated to `gtm_analytics`.

---

## P-001 — Airbyte abandoned: wrong tool for this stack

**Phase:** Phase 0 (ingestion)
**Date:** 2026-06-14

### Problem
Chose Airbyte as the ingestion layer. After beginning installation it became clear it was the wrong fit:
- Airbyte (via `abctl`) runs a full Kubernetes cluster locally (via `kind`), pulling ~3.5 GB of Docker images just to start.
- Requires a persistent UI/server process — heavy operational overhead for a pipeline that just needs to run on a schedule.
- Custom connectors (Python CDK) require scaffolding, Dockerfiles, acceptance-test suites, and GHCR image publishing — a lot of ceremony for two sources.
- No CDC support out of the box for Postgres without additional configuration.

### Iterations
1. **First attempt:** Ran `curl -LsfS https://get.airbyte.com | bash -`. Script installed `abctl` CLI but did not start any containers. Portal at `http://localhost:8000` was empty.
2. **Diagnosis:** The script only installs the CLI. Actual startup requires a separate `abctl local install` command.
3. **Second attempt:** Ran `abctl local install` inside `airbyte/platform/`. Began pulling images (Kubernetes via `kind`, Helm chart, 5+ containers).
4. **Decision:** Stopped the install. The overhead (Kubernetes cluster, 3.5 GB images, separate server, custom CDK connectors) was disproportionate to the task. Decided to replace with **dlt + CDC**.

### What we replaced it with
- **dlt** (`dlt[bigquery]` + `dlt[postgres]`): a Python library, no separate server, runs as a script or scheduled GitHub Actions workflow.
- **Attio source:** dlt `rest_api` source with incremental cursor on `last_modified`.
- **Ops DB source:** dlt `pg_replication` source — true CDC via Postgres WAL (logical replication). Captures INSERT/UPDATE/DELETE events.

### Cleanup performed
- `abctl local uninstall` (cluster was already gone — never fully started).
- Removed all Airbyte Docker images: `airbyte/connector-sidecar`, `airbyte/server`, `airbyte/workload-init-container`, `airbyte/container-orchestrator`, `airbyte/db`, `temporalio/auto-setup` (~3.5 GB recovered).
- Removed `~/.airbyte/` (Helm cache, kubeconfig, PVC data).
- Removed `/usr/local/bin/abctl` (required `sudo`).
- Removed `airbyte/` folder from the project entirely.

### Project changes made
- `airbyte/` → deleted.
- `dlt/` → created with `pipelines/`, `sources/attio/`, `sources/ops/`, `.dlt/`.
- `PROJECT (1).md` → stack table, §4 ingestion section, gotchas, §9.1 CI, layer rules — all updated.
- `task_brief (1).md` → Phase 0 fully rewritten for dlt + CDC.
- `README.md` → quick start and structure updated.
- `dbt/models/sources.yml` → `_airbyte_extracted_at` renamed to `_extracted_at`.

### Lesson
Before committing to a data ingestion tool, evaluate: (1) operational weight (does it need its own server?), (2) CDC support, (3) how pipelines are deployed and scheduled, (4) what the CI story looks like. Airbyte is the right choice when you need a managed UI for non-engineers to configure connections. For a code-first, scheduled pipeline owned by engineers, a library like dlt is simpler and more composable.
