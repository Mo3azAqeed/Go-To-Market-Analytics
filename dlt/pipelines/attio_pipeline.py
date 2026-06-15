"""
Attio → BigQuery pipeline.

Local run (from dlt/ directory):
    python pipelines/attio_pipeline.py

Cloud Function (HTTP trigger, Gen 2):
    Entry point: attio_sync
    Runtime env vars required:
        ATTIO_SOURCE__API_TOKEN   — Attio API token (from Secret Manager)
        ATTIO_SOURCE__MQL_LIST_ID — Attio MQL list ID
    BigQuery auth: handled automatically via the function's attached service account (ADC).
    No DESTINATION__BIGQUERY__CREDENTIALS needed in Cloud Functions.

Pipeline state (cursor positions) is stored in BigQuery's _dlt_pipeline_state table,
so it persists across Cloud Function invocations without any local filesystem dependency.
"""

import dlt

from sources.attio import attio_source


def run() -> None:
    pipeline = dlt.pipeline(
        pipeline_name="attio_pipeline",
        destination="bigquery",
        dataset_name="raw_attio",
    )
    load_info = pipeline.run(attio_source())
    print(load_info)


def attio_sync(request):
    """
    Cloud Function entry point (HTTP trigger, Gen 2).

    Triggered by Cloud Scheduler on a cron schedule (every 1 hour).
    Authentication to BigQuery uses the function's attached service account via ADC —
    no credential env vars required.
    """
    run()
    return ("OK", 200)


if __name__ == "__main__":
    run()
