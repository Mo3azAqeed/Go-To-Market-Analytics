# Problems & Lessons

Running log of every problem hit during this build, what we tried, and what we concluded. New entries go at the top. Each problem gets an ID so it can be referenced from PRs and code comments.

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
