"""
Attio → BigQuery pipeline runner.

Run from the dlt/ directory:
    python pipelines/attio_pipeline.py

dlt reads .dlt/secrets.toml and .dlt/config.toml from the working directory.
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


if __name__ == "__main__":
    run()
