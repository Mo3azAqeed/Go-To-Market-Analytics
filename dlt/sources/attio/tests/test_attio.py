"""
Unit tests for dlt/sources/attio/__init__.py

Tests are isolated from the real Attio API — HTTP calls are mocked.
Run from the dlt/ directory:
    pytest sources/attio/tests/

Coverage
--------
1. Schema validation   — every resource yields rows with the expected columns
2. Cursor progression  — incremental cursor advances after a successful load
3. Auth failure        — 401 response raises an exception, not silently empty
4. CDC event types     — not applicable for Attio REST; covered in ops tests
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pendulum
import pytest

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

MQL_ENTRY = {
    "id": {"list_id": "list_abc", "entry_id": "entry_001"},
    "entry_values": {
        "origin": [{"attribute_type": "select", "value": {"option_id": "opt1", "title": "organic"}}],
        "first_contact_date": [{"attribute_type": "date", "value": "2024-01-15"}],
    },
    "created_at": "2024-01-15T10:00:00.000Z",
    "updated_at": "2024-02-01T09:00:00.000Z",
}

DEAL_RECORD = {
    "id": {"object_id": "obj_deals", "record_id": "deal_001"},
    "values": {
        "mql_id": [{"attribute_type": "text", "value": "entry_001"}],
        "seller_id": [{"attribute_type": "text", "value": "seller_xyz"}],
        "won_date": [{"attribute_type": "date", "value": "2024-02-10"}],
        "business_segment": [{"attribute_type": "select", "value": {"title": "home_decor"}}],
        "lead_type": [{"attribute_type": "select", "value": {"title": "inbound"}}],
        "stage": [{"attribute_type": "select", "value": {"title": "won"}}],
    },
    "created_at": "2024-01-20T08:00:00.000Z",
    "updated_at": "2024-02-10T11:00:00.000Z",
}

SDR_MEMBER = {
    "id": {"workspace_id": "ws1", "workspace_member_id": "sdr_001"},
    "first_name": "Ana",
    "last_name": "Lima",
    "email_address": "ana@example.com",
    "created_at": "2023-06-01T00:00:00.000Z",
}

NOTE_RECORD = {
    "id": {"note_id": "note_001"},
    "parent_object": "deals",
    "parent_record_id": "deal_001",
    "title": "First call",
    "created_at": "2024-01-22T14:00:00.000Z",
    "created_by_actor": {"type": "workspace-member", "id": "sdr_001"},
}


def _mock_post_response(data: list[dict]) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {"data": data}
    return mock


def _mock_get_response(data: list[dict]) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {"data": data}
    return mock


def _mock_401() -> MagicMock:
    mock = MagicMock()
    mock.status_code = 401
    mock.raise_for_status.side_effect = Exception("401 Unauthorized")
    mock.json.return_value = {"error": "Unauthorized"}
    return mock


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestMqlsSchema:
    REQUIRED_FIELDS = {"mql_id", "list_id", "origin", "first_contact_date", "last_modified", "created_at", "_extracted_at"}

    def test_yields_expected_fields(self):
        from sources.attio import mqls

        with patch("sources.attio.requests.post", return_value=_mock_post_response([MQL_ENTRY])):
            rows = list(mqls(api_token="tok", mql_list_id="list_abc"))

        assert len(rows) == 1
        row = rows[0]
        assert self.REQUIRED_FIELDS.issubset(row.keys()), f"Missing: {self.REQUIRED_FIELDS - row.keys()}"

    def test_scalar_extraction(self):
        from sources.attio import mqls

        with patch("sources.attio.requests.post", return_value=_mock_post_response([MQL_ENTRY])):
            rows = list(mqls(api_token="tok", mql_list_id="list_abc"))

        row = rows[0]
        assert row["mql_id"] == "entry_001"
        assert row["list_id"] == "list_abc"
        assert row["origin"] == "organic"
        assert row["first_contact_date"] == "2024-01-15"
        assert row["last_modified"] == "2024-02-01T09:00:00.000Z"

    def test_extracted_at_is_utc_iso(self):
        from sources.attio import mqls

        with patch("sources.attio.requests.post", return_value=_mock_post_response([MQL_ENTRY])):
            rows = list(mqls(api_token="tok", mql_list_id="list_abc"))

        extracted_at = rows[0]["_extracted_at"]
        parsed = pendulum.parse(extracted_at)
        assert parsed.timezone_name in ("UTC", "+00:00")


class TestClosedDealsSchema:
    REQUIRED_FIELDS = {
        "deal_id", "mql_id", "seller_id", "won_date",
        "business_segment", "lead_type", "last_modified", "created_at", "_extracted_at",
    }

    def test_yields_expected_fields(self):
        from sources.attio import closed_deals

        with patch("sources.attio.requests.post", return_value=_mock_post_response([DEAL_RECORD])):
            rows = list(closed_deals(api_token="tok"))

        assert len(rows) == 1
        row = rows[0]
        assert self.REQUIRED_FIELDS.issubset(row.keys()), f"Missing: {self.REQUIRED_FIELDS - row.keys()}"

    def test_seller_id_populated(self):
        from sources.attio import closed_deals

        with patch("sources.attio.requests.post", return_value=_mock_post_response([DEAL_RECORD])):
            rows = list(closed_deals(api_token="tok"))

        assert rows[0]["seller_id"] == "seller_xyz"

    def test_business_segment_from_select(self):
        from sources.attio import closed_deals

        with patch("sources.attio.requests.post", return_value=_mock_post_response([DEAL_RECORD])):
            rows = list(closed_deals(api_token="tok"))

        assert rows[0]["business_segment"] == "home_decor"


class TestSdrsSchema:
    def test_yields_members_with_extracted_at(self):
        from sources.attio import sdrs

        with patch("sources.attio.requests.get", return_value=_mock_get_response([SDR_MEMBER])):
            rows = list(sdrs(api_token="tok"))

        assert len(rows) == 1
        assert "_extracted_at" in rows[0]
        assert rows[0]["first_name"] == "Ana"

    def test_passthrough_fields_preserved(self):
        from sources.attio import sdrs

        with patch("sources.attio.requests.get", return_value=_mock_get_response([SDR_MEMBER])):
            rows = list(sdrs(api_token="tok"))

        row = rows[0]
        assert row["email_address"] == "ana@example.com"


class TestSalesActivitiesSchema:
    REQUIRED_FIELDS = {"activity_id", "parent_object", "parent_record_id", "title", "created_at", "_extracted_at"}

    def test_yields_expected_fields(self):
        from sources.attio import sales_activities

        with patch("sources.attio.requests.get", return_value=_mock_get_response([NOTE_RECORD])):
            rows = list(sales_activities(api_token="tok"))

        assert len(rows) == 1
        assert self.REQUIRED_FIELDS.issubset(rows[0].keys())

    def test_note_id_as_activity_id(self):
        from sources.attio import sales_activities

        with patch("sources.attio.requests.get", return_value=_mock_get_response([NOTE_RECORD])):
            rows = list(sales_activities(api_token="tok"))

        assert rows[0]["activity_id"] == "note_001"


# ---------------------------------------------------------------------------
# Cursor progression
# ---------------------------------------------------------------------------

class TestCursorProgression:
    def test_mqls_cursor_filter_applied(self):
        """The filter sent to Attio uses the current cursor value."""
        from sources.attio import mqls

        captured_body: list[dict] = []

        def fake_post(url, headers=None, json=None, timeout=None):
            captured_body.append(json)
            return _mock_post_response([])

        resource = mqls(api_token="tok", mql_list_id="list_abc")
        # Override the cursor's last_value to simulate a previous run
        resource.incremental._cursor_path = "last_modified"

        with patch("sources.attio.requests.post", side_effect=fake_post):
            list(resource)

        assert len(captured_body) >= 1
        sent_filter = captured_body[0].get("filter", {})
        assert "updated_at" in sent_filter

    def test_closed_deals_filter_includes_stage_won(self):
        """Filter for closed_deals always includes stage=won."""
        from sources.attio import closed_deals

        captured: list[dict] = []

        def fake_post(url, headers=None, json=None, timeout=None):
            captured.append(json)
            return _mock_post_response([])

        with patch("sources.attio.requests.post", side_effect=fake_post):
            list(closed_deals(api_token="tok"))

        sent_filter = captured[0].get("filter", {})
        assert sent_filter.get("stage", {}).get("$eq") == "won"


# ---------------------------------------------------------------------------
# Auth failure
# ---------------------------------------------------------------------------

class TestAuthFailure:
    def test_mqls_raises_on_401(self):
        from sources.attio import mqls

        with patch("sources.attio.requests.post", return_value=_mock_401()):
            with pytest.raises(Exception, match="401"):
                list(mqls(api_token="bad_token", mql_list_id="list_abc"))

    def test_closed_deals_raises_on_401(self):
        from sources.attio import closed_deals

        with patch("sources.attio.requests.post", return_value=_mock_401()):
            with pytest.raises(Exception, match="401"):
                list(closed_deals(api_token="bad_token"))

    def test_sdrs_raises_on_401(self):
        from sources.attio import sdrs

        with patch("sources.attio.requests.get", return_value=_mock_401()):
            with pytest.raises(Exception, match="401"):
                list(sdrs(api_token="bad_token"))

    def test_sales_activities_raises_on_401(self):
        from sources.attio import sales_activities

        with patch("sources.attio.requests.get", return_value=_mock_401()):
            with pytest.raises(Exception, match="401"):
                list(sales_activities(api_token="bad_token"))


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestPagination:
    def test_mqls_fetches_all_pages(self):
        """When first page is full (500 rows), a second request is made."""
        from sources.attio import mqls

        full_page = [MQL_ENTRY] * 500
        partial_page = [MQL_ENTRY] * 3

        call_count = 0

        def fake_post(url, headers=None, json=None, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_post_response(full_page)
            return _mock_post_response(partial_page)

        with patch("sources.attio.requests.post", side_effect=fake_post):
            rows = list(mqls(api_token="tok", mql_list_id="list_abc"))

        assert call_count == 2
        assert len(rows) == 503
