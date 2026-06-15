"""
dlt source for Attio CRM.

Streams
-------
mqls             List entries (People in the MQL list).  merge, cursor=last_modified
closed_deals     Deal records with stage=won.            merge, cursor=last_modified
sdrs             Workspace members.                      replace (full refresh)
sales_activities Notes / outreach activity.              append, cursor=created_at

Every yielded row carries _extracted_at (ISO-8601 UTC) so dbt source freshness
can assert staleness via loaded_at_field: _extracted_at.

Attio API v2 base URL: https://api.attio.com/v2
Auth: Authorization: Bearer <token>
Pagination: POST bodies accept {"limit": N, "offset": N}; GET endpoints use ?limit=N&offset=N
"""

from __future__ import annotations

from typing import Any, Generator, Iterator

import pendulum
import requests
import dlt
from dlt.sources import DltResource

BASE_URL = "https://api.attio.com/v2"
PAGE_LIMIT = 500


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}


def _get_pages(url: str, headers: dict, params: dict | None = None) -> Iterator[list[dict]]:
    """Paginate a GET endpoint using offset/limit query params."""
    offset = 0
    while True:
        resp = requests.get(
            url,
            headers=headers,
            params={**(params or {}), "limit": PAGE_LIMIT, "offset": offset},
            timeout=30,
        )
        resp.raise_for_status()
        page: list[dict] = resp.json().get("data", [])
        if not page:
            break
        yield page
        if len(page) < PAGE_LIMIT:
            break
        offset += len(page)


def _post_pages(url: str, headers: dict, body: dict) -> Iterator[list[dict]]:
    """Paginate a POST query endpoint using offset/limit in the request body."""
    offset = 0
    while True:
        resp = requests.post(
            url,
            headers=headers,
            json={**body, "limit": PAGE_LIMIT, "offset": offset},
            timeout=30,
        )
        resp.raise_for_status()
        page: list[dict] = resp.json().get("data", [])
        if not page:
            break
        yield page
        if len(page) < PAGE_LIMIT:
            break
        offset += len(page)


def _scalar(values: dict, key: str) -> Any:
    """
    Extract a scalar from an Attio record values dict.

    Attio returns values as: {"field_name": [{"attribute_type": "...", "value": ...}]}
    Some "value" entries are nested dicts (e.g. select options, references).
    """
    entries = values.get(key, [])
    if not entries or not isinstance(entries, list):
        return None
    v = entries[0].get("value")
    if isinstance(v, dict):
        # select option → use title; record reference → use target_record_id
        return v.get("title") or v.get("target_record_id") or str(v)
    return v


# ---------------------------------------------------------------------------
# Source entry point
# ---------------------------------------------------------------------------

@dlt.source(name="attio")
def attio_source(
    api_token: str = dlt.secrets.value,
    mql_list_id: str = dlt.config.value,
) -> list[DltResource]:
    """Return all four Attio streams."""
    return [
        mqls(api_token, mql_list_id),
        closed_deals(api_token),
        sdrs(api_token),
        sales_activities(api_token),
    ]


# ---------------------------------------------------------------------------
# Individual resources
# ---------------------------------------------------------------------------

@dlt.resource(name="mqls", write_disposition="merge", primary_key="mql_id")
def mqls(
    api_token: str = dlt.secrets.value,
    mql_list_id: str = dlt.config.value,
    cursor: dlt.sources.incremental[str] = dlt.sources.incremental(
        "last_modified",
        initial_value="2020-01-01T00:00:00.000Z",
    ),
) -> Generator[dict[str, Any], None, None]:
    """
    MQLs from the Attio MQL list (People object).

    The list ID is workspace-specific; set attio.mql_list_id in config.toml.
    Attio filter uses updated_at >= cursor to reduce data transferred.
    dlt tracks the max value of last_modified to advance the cursor on next run.
    """
    hdrs = _headers(api_token)
    extracted_at = pendulum.now("UTC").isoformat()
    body = {"filter": {"updated_at": {"$gte": cursor.last_value}}}

    for page in _post_pages(f"{BASE_URL}/lists/{mql_list_id}/entries/query", hdrs, body):
        for entry in page:
            values = entry.get("entry_values", {})
            yield {
                "mql_id": entry["id"]["entry_id"],
                "list_id": entry["id"]["list_id"],
                "origin": _scalar(values, "origin"),
                "first_contact_date": _scalar(values, "first_contact_date"),
                "last_modified": entry.get("updated_at"),
                "created_at": entry.get("created_at"),
                "_extracted_at": extracted_at,
            }


@dlt.resource(name="closed_deals", write_disposition="merge", primary_key="deal_id")
def closed_deals(
    api_token: str = dlt.secrets.value,
    cursor: dlt.sources.incremental[str] = dlt.sources.incremental(
        "last_modified",
        initial_value="2020-01-01T00:00:00.000Z",
    ),
) -> Generator[dict[str, Any], None, None]:
    """
    Won deals from Attio's Deals object.

    The "stage" filter name matches the Deals object attribute slug in Attio.
    If your workspace uses a different attribute name (e.g. "status", "deal_stage"),
    update the filter key here and document in PROBLEMS_AND_LESSONS.md.

    seller_id is the cross-system bridge to raw_ops.sellers.
    """
    hdrs = _headers(api_token)
    extracted_at = pendulum.now("UTC").isoformat()
    body = {
        "filter": {
            "stage": {"$eq": "won"},
            "updated_at": {"$gte": cursor.last_value},
        }
    }

    for page in _post_pages(f"{BASE_URL}/objects/deals/records/query", hdrs, body):
        for record in page:
            values = record.get("values", {})
            yield {
                "deal_id": record["id"]["record_id"],
                "mql_id": _scalar(values, "mql_id"),
                "seller_id": _scalar(values, "seller_id"),
                "won_date": _scalar(values, "won_date"),
                "business_segment": _scalar(values, "business_segment"),
                "lead_type": _scalar(values, "lead_type"),
                "last_modified": record.get("updated_at"),
                "created_at": record.get("created_at"),
                "_extracted_at": extracted_at,
            }


@dlt.resource(name="sdrs", write_disposition="replace")
def sdrs(
    api_token: str = dlt.secrets.value,
) -> Generator[dict[str, Any], None, None]:
    """
    Workspace members (Sales Development Reps).

    Full refresh — low cardinality, no cursor needed.
    Attio pagination still applied in case workspace grows.
    """
    hdrs = _headers(api_token)
    extracted_at = pendulum.now("UTC").isoformat()
    for page in _get_pages(f"{BASE_URL}/workspace-members", hdrs):
        for member in page:
            yield {**member, "_extracted_at": extracted_at}


@dlt.resource(name="sales_activities", write_disposition="append", primary_key="activity_id")
def sales_activities(
    api_token: str = dlt.secrets.value,
    cursor: dlt.sources.incremental[str] = dlt.sources.incremental(
        "created_at",
        initial_value="2020-01-01T00:00:00.000Z",
    ),
) -> Generator[dict[str, Any], None, None]:
    """
    Notes / outreach activity per deal (future use).

    Append-only — notes are immutable once created.
    Filter uses created_at:gte Attio query param convention.
    """
    hdrs = _headers(api_token)
    extracted_at = pendulum.now("UTC").isoformat()
    params = {"created_at:gte": cursor.last_value}

    for page in _get_pages(f"{BASE_URL}/notes", hdrs, params):
        for note in page:
            yield {
                "activity_id": note["id"]["note_id"],
                "parent_object": note.get("parent_object"),
                "parent_record_id": note.get("parent_record_id"),
                "title": note.get("title"),
                "created_at": note.get("created_at"),
                "created_by_actor": note.get("created_by_actor"),
                "_extracted_at": extracted_at,
            }
