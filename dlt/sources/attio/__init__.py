"""
dlt source for Attio CRM.

Streams
-------
mqls                MQL records (custom object).           merge, cursor=created_at
sqls                SQL records — the won-deal event.      merge, cursor=created_at
workspace_members   Workspace members (SDRs, AEs, etc).   replace (full refresh)
sales_activities    Notes / outreach activity.             append, cursor=created_at

Object structure verified against live API 2026-06-17:
  - mqls:  POST /v2/objects/mqls/records/query
  - sqls:  POST /v2/objects/sqls/records/query
  - workspace_members: GET /v2/workspace_members
  - notes: GET /v2/notes

There is no "deals" object in this workspace. The sqls object carries won_date,
seller_id, sdr_id, sr_id, segment, and lead_type — it IS the conversion event.

Attio records have created_at but no updated_at at the top level. The cursor
therefore tracks created_at. Records imported via CSV bulk upload are immutable
(the business keys like mql_id are set once on import), so created_at is sufficient.

Every yielded row carries _extracted_at (ISO-8601 UTC) so dbt source freshness
can assert staleness via loaded_at_field: _extracted_at.
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
    """
    entries = values.get(key, [])
    if not entries or not isinstance(entries, list):
        return None
    v = entries[0].get("value")
    if isinstance(v, dict):
        return v.get("title") or v.get("target_record_id") or str(v)
    return v


# ---------------------------------------------------------------------------
# Source entry point
# ---------------------------------------------------------------------------

@dlt.source(name="attio")
def attio_source(
    api_token: str = dlt.secrets.value,
) -> list[DltResource]:
    """Return all four Attio streams."""
    return [
        mqls(api_token),
        sqls(api_token),
        workspace_members(api_token),
        sales_activities(api_token),
    ]


# ---------------------------------------------------------------------------
# Individual resources
# ---------------------------------------------------------------------------

@dlt.resource(name="mqls", write_disposition="merge", primary_key="record_id")
def mqls(
    api_token: str = dlt.secrets.value,
    cursor: dlt.sources.incremental[str] = dlt.sources.incremental(
        "created_at",
        initial_value="2020-01-01T00:00:00.000Z",
    ),
) -> Generator[dict[str, Any], None, None]:
    """
    MQL records from the custom mqls object.

    Fields confirmed live: record_id, mql_id, first_contact_date, landing_page_id,
    origin, created_at.

    mql_id is the cross-system business key linking to raw_ops.leads.
    """
    hdrs = _headers(api_token)
    extracted_at = pendulum.now("UTC").isoformat()
    body = {"filter": {"created_at": {"$gte": cursor.last_value}}}

    for page in _post_pages(f"{BASE_URL}/objects/mqls/records/query", hdrs, body):
        for record in page:
            values = record.get("values", {})
            yield {
                "record_id": record["id"]["record_id"],
                "mql_id": _scalar(values, "mql_id"),
                "first_contact_date": _scalar(values, "first_contact_date"),
                "landing_page_id": _scalar(values, "landing_page_id"),
                "origin": _scalar(values, "origin"),
                "created_at": record.get("created_at"),
                "_extracted_at": extracted_at,
            }


@dlt.resource(name="sqls", write_disposition="merge", primary_key="record_id")
def sqls(
    api_token: str = dlt.secrets.value,
    cursor: dlt.sources.incremental[str] = dlt.sources.incremental(
        "created_at",
        initial_value="2020-01-01T00:00:00.000Z",
    ),
) -> Generator[dict[str, Any], None, None]:
    """
    SQL records — the won-deal / conversion event.

    There is no separate "deals" object in this workspace. The sqls object carries
    the full conversion payload: who converted (mql_id), who sold (seller_id/sdr_id/sr_id),
    when (won_date), and what segment/lead_type.

    Fields confirmed live: record_id, mql_id, seller_id, sdr_id, sr_id, won_date,
    segment, lead_type, created_at.
    """
    hdrs = _headers(api_token)
    extracted_at = pendulum.now("UTC").isoformat()
    body = {"filter": {"created_at": {"$gte": cursor.last_value}}}

    for page in _post_pages(f"{BASE_URL}/objects/sqls/records/query", hdrs, body):
        for record in page:
            values = record.get("values", {})
            yield {
                "record_id": record["id"]["record_id"],
                "mql_id": _scalar(values, "mql_id"),
                "seller_id": _scalar(values, "seller_id"),
                "sdr_id": _scalar(values, "sdr_id"),
                "sr_id": _scalar(values, "sr_id"),
                "won_date": _scalar(values, "won_date"),
                "segment": _scalar(values, "segment"),
                "lead_type": _scalar(values, "lead_type"),
                "created_at": record.get("created_at"),
                "_extracted_at": extracted_at,
            }


@dlt.resource(name="workspace_members", write_disposition="replace")
def workspace_members(
    api_token: str = dlt.secrets.value,
) -> Generator[dict[str, Any], None, None]:
    """
    Workspace members — SDRs, AEs, and other team members.

    Full refresh — low cardinality. Endpoint: GET /v2/workspace_members.
    Note: the endpoint uses underscore (workspace_members), not a hyphen.
    """
    hdrs = _headers(api_token)
    extracted_at = pendulum.now("UTC").isoformat()
    for page in _get_pages(f"{BASE_URL}/workspace_members", hdrs):
        for member in page:
            yield {
                "workspace_member_id": member["id"]["workspace_member_id"],
                "first_name": member.get("first_name"),
                "last_name": member.get("last_name"),
                "email_address": member.get("email_address"),
                "access_level": member.get("access_level"),
                "created_at": member.get("created_at"),
                "_extracted_at": extracted_at,
            }


@dlt.resource(name="sales_activities", write_disposition="append", primary_key="activity_id")
def sales_activities(
    api_token: str = dlt.secrets.value,
    cursor: dlt.sources.incremental[str] = dlt.sources.incremental(
        "created_at",
        initial_value="2020-01-01T00:00:00.000Z",
    ),
) -> Generator[dict[str, Any], None, None]:
    """
    Notes / outreach activity (empty at time of writing, kept for future use).

    Append-only — notes are immutable once created.
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
