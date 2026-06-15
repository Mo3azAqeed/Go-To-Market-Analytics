# dlt Pipelines

Data ingestion from Attio CRM into BigQuery using [dlt](https://dlthub.com).

## Overview

| Pipeline | Source | Destination | Schedule |
|---|---|---|---|
| `attio_pipeline` | Attio REST API v2 | `raw_attio` dataset in BigQuery | Every 1 hour |

The ops DB (`raw_ops`) is managed by a separate team — see `dlt/sources/ops/` scaffold for reference.

---

## Local setup

### 1. Install dependencies

```bash
cd dlt
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure secrets via environment variables

dlt reads configuration from environment variables using `__` as the section
separator (all uppercase). No `secrets.toml` file is needed.

| Variable | Where it's needed | Value |
|---|---|---|
| `ATTIO_SOURCE__API_TOKEN` | Local + CI + Cloud Function | Attio API token (Settings → API) |
| `ATTIO_SOURCE__MQL_LIST_ID` | Local + CI + Cloud Function | Attio MQL list ID |
| `DESTINATION__BIGQUERY__CREDENTIALS` | Local + CI only | Full service account JSON string |

`location` and `project_id` are non-secret and live in `.dlt/config.toml` — no env var needed.

**Why one JSON credential, not five separate fields:**
Splitting the service account JSON into separate fields (`PRIVATE_KEY`, `CLIENT_EMAIL`, etc.) breaks
because the RSA private key contains literal newlines which get mangled in shell env vars.
Passing the full JSON string to `DESTINATION__BIGQUERY__CREDENTIALS` avoids this — dlt parses it natively.

**Locally** — export before running:
```bash
export ATTIO_SOURCE__API_TOKEN="your-token"
export ATTIO_SOURCE__MQL_LIST_ID="lst_abc123"
export DESTINATION__BIGQUERY__CREDENTIALS='{"type":"service_account","project_id":"obito-492802","private_key":"...","client_email":"...",...}'
python pipelines/attio_pipeline.py
```

**In GitHub Actions** — add two secrets (Settings → Secrets → Actions):
- `GCP_SERVICE_ACCOUNT_JSON` — paste the full contents of the service account JSON file
- `ATTIO_API_TOKEN` — Attio API token
- `ATTIO_MQL_LIST_ID` — Attio MQL list ID

The workflow maps these to the correct env vars automatically.

---

## Deploying as a Cloud Function (scheduled automation)

On Cloud Functions, BigQuery authentication works via **Application Default Credentials (ADC)** — the function's attached service account authenticates automatically. You do **not** set `DESTINATION__BIGQUERY__CREDENTIALS`.

**Setup steps:**

1. Deploy the function with entry point `attio_sync` from `dlt/pipelines/attio_pipeline.py`.
2. Attach a service account that has `BigQuery Data Editor` + `BigQuery Job User` roles.
3. Set two environment variables on the function:
   ```
   ATTIO_SOURCE__API_TOKEN   = <your-attio-api-token>   (from Secret Manager recommended)
   ATTIO_SOURCE__MQL_LIST_ID = <your-mql-list-id>
   ```
4. Create a **Cloud Scheduler** job pointing at the function URL, cron: `0 * * * *` (every hour).

**Pipeline state** (cursor positions for incremental loading) is stored in BigQuery's
`raw_attio._dlt_pipeline_state` table — it persists across invocations automatically.
No local filesystem dependency.

### 3. Configure the MQL list ID

In `.dlt/config.toml`, set `attio_source.mql_list_id` to the ID of your Attio MQL list.
Find it by opening the list in Attio and copying the ID from the URL:
`https://app.attio.com/lists/lst_abc123` → `"lst_abc123"`

### 4. Run the pipeline

```bash
cd dlt                          # always run from here so dlt finds .dlt/
python pipelines/attio_pipeline.py
```

dlt prints a load summary and row counts on success. On first run it performs a full backfill from `2020-01-01`; subsequent runs are incremental.

---

## Streams and write dispositions

| Stream | Attio object | Write disposition | Cursor |
|---|---|---|---|
| `mqls` | List entries (People) | merge | `last_modified` |
| `closed_deals` | Deal records (won) | merge | `last_modified` |
| `sdrs` | Workspace members | replace | — |
| `sales_activities` | Notes | append | `created_at` |

All rows carry `_extracted_at` (UTC ISO-8601). dbt source freshness uses this field
(`loaded_at_field: _extracted_at` in `sources.yml`).

---

## Running tests

```bash
cd dlt
pytest sources/attio/tests/ -v
```

Tests mock all HTTP calls — no network or BigQuery connection required.

---

## Adding a new Attio stream

1. Define a new `@dlt.resource` in `dlt/sources/attio/__init__.py`.
   - Set `write_disposition`, `primary_key`, and an `incremental` cursor if applicable.
   - Add `"_extracted_at": extracted_at` to every yielded row.
2. Add it to the `attio_source()` return list.
3. Declare it in `dbt/gtm_analytics_dbt/models/sources.yml` under `raw_attio`.
4. Write a staging model `stg_attio__<stream>.sql`.
5. Add tests to `sources/attio/tests/test_attio.py`.
6. Open a PR touching all four layers, labelled accordingly.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `401 Unauthorized` | Wrong or expired API token | Regenerate in Attio → Settings → API |
| `filter.stage` returns empty | Deal attribute slug differs in your workspace | Check slug in Attio object config; update `closed_deals()` filter key |
| `mql_list_id` not found | Wrong list ID in config.toml | Re-copy from Attio URL |
| BigQuery permission denied | Service account missing `bigquery.dataEditor` role | Grant role in GCP IAM |
| Cursor not advancing | State file corrupted | Delete `dlt/.pipeline/attio_pipeline/` and re-run (triggers full reload) |
