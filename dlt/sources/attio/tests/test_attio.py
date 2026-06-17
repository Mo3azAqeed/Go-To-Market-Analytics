"""
Unit tests for dlt/sources/attio/__init__.py

Tests are isolated from the real Attio API — HTTP calls are mocked.
Run from the dlt/ directory:
    pytest sources/attio/tests/

Fixtures match the actual Attio API v2 response shapes verified 2026-06-17.

Coverage
--------
1. Schema validation   — every resource yields rows with the expected columns
2. Scalar extraction   — nested Attio value format unwrapped correctly
3. Auth failure        — 401 response raises an exception, not silently empty
4. Pagination          — full page (500 rows) triggers a second request
5. Cursor filter       — incremental filter uses created_at with $gte operator
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pendulum
import pytest


# ---------------------------------------------------------------------------
# Fixture helpers — match real API shapes verified via live calls
# ---------------------------------------------------------------------------

MQL_RECORD = {
    "id": {
        "workspace_id": "ws1",
        "object_id": "22ec9de3-696e-4403-91f2-5cf0417ac000",
        "record_id": "000825a4-4e87-45b7-a836-927c19965591",
    },
    "created_at": "2026-06-13T14:52:06.007000000Z",
    "values": {
        "mql_id": [{"attribute_type": "text", "value": "8cc73dd2a42ac2d64984ddb3c72f633b"}],
        "first_contact_date": [{"attribute_type": "date", "value": "2017-10-28"}],
        "landing_page_id": [{"attribute_type": "text", "value": "f017be4dbf86243af5c1ebed0cff36a2"}],
        "origin": [{"attribute_type": "text", "value": "organic_search"}],
    },
}

SQL_RECORD = {
    "id": {
        "workspace_id": "ws1",
        "object_id": "cfcedef9-b879-45f1-b83f-1dafeec4b022",
        "record_id": "0000b9c6-08d0-5f27-a15e-370c2fa9ffca",
    },
    "created_at": "2026-06-13T15:05:16.458000000Z",
    "values": {
        "mql_id": [{"attribute_type": "text", "value": "caea756b29bd071f00ce526f40645a78"}],
        "seller_id": [{"attribute_type": "text", "value": "fadb07c842a2aef5d5a676b85f220e71"}],
        "sdr_id": [{"attribute_type": "text", "value": "4b339f9567d060bcea4f5136b9f5949e"}],
        "sr_id": [{"attribute_type": "text", "value": "d3d1e91a157ea7f90548eef82f1955e3"}],
        "won_date": [{"attribute_type": "date", "value": "2018-04-10"}],
        "segment": [{"attribute_type": "text", "value": "sports_leisure"}],
        "lead_type": [{"attribute_type": "text", "value": "online_medium"}],
    },
}

WORKSPACE_MEMBER = {
    "id": {"workspace_id": "ws1", "workspace_member_id": "9dd38721-cf33-4ae3-b7ee-3a3a42e8b2fe"},
    "first_name": "moaz",
    "last_name": "mohamed",
    "email_address": "moaz@example.com",
    "access_level": "admin",
    "created_at": "2026-06-13T14:30:12.205000000Z",
}

NOTE_RECORD = {
    "id": {"note_id": "note_001"},
    "parent_object": "sqls",
    "parent_record_id": "0000b9c6-08d0-5f27-a15e-370c2fa9ffca",
    "title": "First call",
    "created_at": "2026-06-14T10:00:00.000Z",
    "created_by_actor": {"type": "workspace-member", "id": "9dd38721-cf33-4ae3-b7ee-3a3a42e8b2fe"},
}


def _mock_response(data: list[dict], status: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = {"data": data}
    if status >= 400:
        mock.raise_for_status.side_effect = Exception(f"{status} Error")
    else:
        mock.raise_for_status = MagicMock()
    return mock


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestMqlsSchema:
    REQUIRED_FIELDS = {
        "record_id", "mql_id", "first_contact_date", "landing_page_id",
        "origin", "created_at", "_extracted_at",
    }

    def test_yields_expected_fields(self):
        from sources.attio import mqls

        with patch("sources.attio.requests.post", return_value=_mock_response([MQL_RECORD])):
            rows = list(mqls(api_token="tok"))

        assert len(rows) == 1
        row = rows[0]
        assert self.REQUIRED_FIELDS.issubset(row.keys()), f"Missing: {self.REQUIRED_FIELDS - row.keys()}"

    def test_scalar_values_extracted(self):
        from sources.attio import mqls

        with patch("sources.attio.requests.post", return_value=_mock_response([MQL_RECORD])):
            rows = list(mqls(api_token="tok"))

        row = rows[0]
        assert row["record_id"] == "000825a4-4e87-45b7-a836-927c19965591"
        assert row["mql_id"] == "8cc73dd2a42ac2d64984ddb3c72f633b"
        assert row["origin"] == "organic_search"
        assert row["first_contact_date"] == "2017-10-28"
        assert row["created_at"] == "2026-06-13T14:52:06.007000000Z"

    def test_extracted_at_is_utc_iso(self):
        from sources.attio import mqls

        with patch("sources.attio.requests.post", return_value=_mock_response([MQL_RECORD])):
            rows = list(mqls(api_token="tok"))

        parsed = pendulum.parse(rows[0]["_extracted_at"])
        assert parsed.timezone_name in ("UTC", "+00:00")


class TestSqlsSchema:
    REQUIRED_FIELDS = {
        "record_id", "mql_id", "seller_id", "sdr_id", "sr_id",
        "won_date", "segment", "lead_type", "created_at", "_extracted_at",
    }

    def test_yields_expected_fields(self):
        from sources.attio import sqls

        with patch("sources.attio.requests.post", return_value=_mock_response([SQL_RECORD])):
            rows = list(sqls(api_token="tok"))

        assert len(rows) == 1
        row = rows[0]
        assert self.REQUIRED_FIELDS.issubset(row.keys()), f"Missing: {self.REQUIRED_FIELDS - row.keys()}"

    def test_all_id_fields_populated(self):
        from sources.attio import sqls

        with patch("sources.attio.requests.post", return_value=_mock_response([SQL_RECORD])):
            rows = list(sqls(api_token="tok"))

        row = rows[0]
        assert row["record_id"] == "0000b9c6-08d0-5f27-a15e-370c2fa9ffca"
        assert row["seller_id"] == "fadb07c842a2aef5d5a676b85f220e71"
        assert row["sdr_id"] == "4b339f9567d060bcea4f5136b9f5949e"
        assert row["segment"] == "sports_leisure"
        assert row["won_date"] == "2018-04-10"


class TestWorkspaceMembersSchema:
    REQUIRED_FIELDS = {
        "workspace_member_id", "first_name", "last_name",
        "email_address", "access_level", "created_at", "_extracted_at",
    }

    def test_yields_expected_fields(self):
        from sources.attio import workspace_members

        with patch("sources.attio.requests.get", return_value=_mock_response([WORKSPACE_MEMBER])):
            rows = list(workspace_members(api_token="tok"))

        assert len(rows) == 1
        row = rows[0]
        assert self.REQUIRED_FIELDS.issubset(row.keys()), f"Missing: {self.REQUIRED_FIELDS - row.keys()}"

    def test_member_id_extracted_from_nested_id(self):
        from sources.attio import workspace_members

        with patch("sources.attio.requests.get", return_value=_mock_response([WORKSPACE_MEMBER])):
            rows = list(workspace_members(api_token="tok"))

        assert rows[0]["workspace_member_id"] == "9dd38721-cf33-4ae3-b7ee-3a3a42e8b2fe"
        assert rows[0]["email_address"] == "moaz@example.com"


class TestSalesActivitiesSchema:
    REQUIRED_FIELDS = {
        "activity_id", "parent_object", "parent_record_id",
        "title", "created_at", "_extracted_at",
    }

    def test_yields_expected_fields(self):
        from sources.attio import sales_activities

        with patch("sources.attio.requests.get", return_value=_mock_response([NOTE_RECORD])):
            rows = list(sales_activities(api_token="tok"))

        assert len(rows) == 1
        assert self.REQUIRED_FIELDS.issubset(rows[0].keys())

    def test_note_id_as_activity_id(self):
        from sources.attio import sales_activities

        with patch("sources.attio.requests.get", return_value=_mock_response([NOTE_RECORD])):
            rows = list(sales_activities(api_token="tok"))

        assert rows[0]["activity_id"] == "note_001"


# ---------------------------------------------------------------------------
# Cursor filter
# ---------------------------------------------------------------------------

class TestCursorFilter:
    def test_mqls_sends_created_at_gte_filter(self):
        """POST body must include created_at $gte filter for incremental loading."""
        from sources.attio import mqls

        captured: list[dict] = []

        def fake_post(url, headers=None, json=None, timeout=None):
            captured.append(json)
            return _mock_response([])

        with patch("sources.attio.requests.post", side_effect=fake_post):
            list(mqls(api_token="tok"))

        assert len(captured) >= 1
        sent_filter = captured[0].get("filter", {})
        assert "created_at" in sent_filter
        assert "$gte" in sent_filter["created_at"]

    def test_sqls_sends_created_at_gte_filter(self):
        from sources.attio import sqls

        captured: list[dict] = []

        def fake_post(url, headers=None, json=None, timeout=None):
            captured.append(json)
            return _mock_response([])

        with patch("sources.attio.requests.post", side_effect=fake_post):
            list(sqls(api_token="tok"))

        sent_filter = captured[0].get("filter", {})
        assert "created_at" in sent_filter
        assert "$gte" in sent_filter["created_at"]


# ---------------------------------------------------------------------------
# Auth failure
# ---------------------------------------------------------------------------

class TestAuthFailure:
    def test_mqls_raises_on_401(self):
        from sources.attio import mqls

        with patch("sources.attio.requests.post", return_value=_mock_response([], 401)):
            with pytest.raises(Exception, match="401"):
                list(mqls(api_token="bad_token"))

    def test_sqls_raises_on_401(self):
        from sources.attio import sqls

        with patch("sources.attio.requests.post", return_value=_mock_response([], 401)):
            with pytest.raises(Exception, match="401"):
                list(sqls(api_token="bad_token"))

    def test_workspace_members_raises_on_401(self):
        from sources.attio import workspace_members

        with patch("sources.attio.requests.get", return_value=_mock_response([], 401)):
            with pytest.raises(Exception, match="401"):
                list(workspace_members(api_token="bad_token"))

    def test_sales_activities_raises_on_401(self):
        from sources.attio import sales_activities

        with patch("sources.attio.requests.get", return_value=_mock_response([], 401)):
            with pytest.raises(Exception, match="401"):
                list(sales_activities(api_token="bad_token"))


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestPagination:
    def test_mqls_fetches_second_page_when_first_is_full(self):
        """A full page (500 rows) triggers a second POST request."""
        from sources.attio import mqls

        full_page = [MQL_RECORD] * 500
        partial_page = [MQL_RECORD] * 7

        call_count = 0

        def fake_post(url, headers=None, json=None, timeout=None):
            nonlocal call_count
            call_count += 1
            return _mock_response(full_page if call_count == 1 else partial_page)

        with patch("sources.attio.requests.post", side_effect=fake_post):
            rows = list(mqls(api_token="tok"))

        assert call_count == 2
        assert len(rows) == 507

    def test_sqls_fetches_second_page_when_first_is_full(self):
        from sources.attio import sqls

        full_page = [SQL_RECORD] * 500
        partial_page = [SQL_RECORD] * 3

        call_count = 0

        def fake_post(url, headers=None, json=None, timeout=None):
            nonlocal call_count
            call_count += 1
            return _mock_response(full_page if call_count == 1 else partial_page)

        with patch("sources.attio.requests.post", side_effect=fake_post):
            rows = list(sqls(api_token="tok"))

        assert call_count == 2
        assert len(rows) == 503
