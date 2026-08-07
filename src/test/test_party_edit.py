# src/test/test_party_edit.py
"""
Tests for /api/partyMaster/party_edit, focusing on the diff-based upsert of
party_branch_mst rows.

The previous implementation used a delete-all-then-insert pattern that:
  - Crashed when any branch was referenced by sales_invoice.transporter_branch_id
    (FK fk_sales_invoice_transporter_branch).
  - Silently churned PKs on every save, orphaning unconstrained downstream refs.

The current implementation:
  - UPDATEs in place for branches whose party_mst_branch_id is in the payload.
  - INSERTs new rows for branches without a party_mst_branch_id.
  - Checks sales_invoice for FK refs before DELETEing branches missing from the
    payload, returning HTTP 409 with code BRANCH_IN_USE when blocked.
"""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.masters.models import PartyMst, PartyBranchMst


client = TestClient(app)


def _override_auth():
    return {"user_id": 1}


def _make_mock_db_override(mock_session):
    def _override():
        yield mock_session
    return _override


def _make_party(party_id: int = 1, co_id: int = 1) -> MagicMock:
    party = MagicMock(spec=PartyMst)
    party.party_id = party_id
    party.co_id = co_id
    return party


def _make_branch(pk: int, address: str = "Addr") -> MagicMock:
    """Build a mock PartyBranchMst row with attribute access semantics."""
    row = MagicMock(spec=PartyBranchMst)
    row.party_mst_branch_id = pk
    row.address = address
    return row


def _install_query_side_effect(mock_session, party=None, existing_branches=None):
    """
    Configure mock_session.query so that:
      - query(PartyMst).filter(...).one_or_none() returns `party`
      - query(PartyBranchMst).filter(...).all() returns `existing_branches`
      - query(PartyBranchMst).filter(...).delete(...) returns the count of
        rows we've claimed are being deleted (the endpoint ignores the value)
    Returns (party_chain, branch_chain) so tests can assert on .delete calls.
    """
    party_chain = MagicMock()
    party_chain.filter.return_value.one_or_none.return_value = party

    branch_chain = MagicMock()
    branch_chain.filter.return_value.all.return_value = existing_branches or []
    branch_chain.filter.return_value.delete.return_value = len(existing_branches or [])

    def _query(model):
        if model is PartyMst:
            return party_chain
        if model is PartyBranchMst:
            return branch_chain
        raise AssertionError(f"Unexpected query target: {model!r}")

    mock_session.query.side_effect = _query
    return party_chain, branch_chain


class TestPartyEditDiffUpsert:

    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth
        self.mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(self.mock_session)

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    # ------------------------------------------------------------------
    # Edit party-level field only -> branches untouched
    # ------------------------------------------------------------------
    def test_edit_party_only_no_branch_changes(self):
        party = _make_party(party_id=42, co_id=1)
        existing = [_make_branch(101, "Addr A"), _make_branch(102, "Addr B")]
        _, branch_chain = _install_query_side_effect(
            self.mock_session, party=party, existing_branches=existing
        )

        # Payload includes both existing branches with their PKs -> no removals,
        # no inserts, two UPDATEs. The FK guard SELECT must not run because
        # to_remove_ids is empty.
        response = client.post(
            "/api/partyMaster/party_edit",
            json={
                "co_id": 1,
                "party_id": 42,
                "supp_name": "Acme Inc.",
                "branches": [
                    {"party_mst_branch_id": 101, "address": "Addr A"},
                    {"party_mst_branch_id": 102, "address": "Addr B"},
                ],
            },
        )

        assert response.status_code == 200, response.text
        # No delete should ever fire
        branch_chain.filter.return_value.delete.assert_not_called()
        # No new branches added
        assert self.mock_session.add.call_count == 0
        # FK check SELECT must not be issued
        assert self.mock_session.execute.call_count == 0
        self.mock_session.commit.assert_called_once()

    # ------------------------------------------------------------------
    # Add a new branch -> existing rows untouched, one INSERT
    # ------------------------------------------------------------------
    def test_add_new_branch_preserves_existing(self):
        party = _make_party(party_id=42, co_id=1)
        existing = [_make_branch(101, "Addr A")]
        _, branch_chain = _install_query_side_effect(
            self.mock_session, party=party, existing_branches=existing
        )

        response = client.post(
            "/api/partyMaster/party_edit",
            json={
                "co_id": 1,
                "party_id": 42,
                "supp_name": "Acme Inc.",
                "branches": [
                    {"party_mst_branch_id": 101, "address": "Addr A"},
                    # New branch (no party_mst_branch_id)
                    {"address": "New Addr", "contact_no": "555-0001"},
                ],
            },
        )

        assert response.status_code == 200, response.text
        # No delete
        branch_chain.filter.return_value.delete.assert_not_called()
        # FK SELECT not issued (nothing to remove)
        assert self.mock_session.execute.call_count == 0
        # Exactly one INSERT (the new branch)
        assert self.mock_session.add.call_count == 1
        added = self.mock_session.add.call_args[0][0]
        assert added.party_id == 42
        assert added.address == "New Addr"

    # ------------------------------------------------------------------
    # Remove a branch with no FK refs -> DELETE proceeds
    # ------------------------------------------------------------------
    def test_remove_unreferenced_branch_succeeds(self):
        party = _make_party(party_id=42, co_id=1)
        existing = [_make_branch(101, "Addr A"), _make_branch(102, "Addr B")]
        _, branch_chain = _install_query_side_effect(
            self.mock_session, party=party, existing_branches=existing
        )
        # FK check returns no blocking rows
        self.mock_session.execute.return_value.fetchall.return_value = []

        response = client.post(
            "/api/partyMaster/party_edit",
            json={
                "co_id": 1,
                "party_id": 42,
                "supp_name": "Acme Inc.",
                "branches": [
                    {"party_mst_branch_id": 101, "address": "Addr A"},
                    # 102 omitted -> should be deleted
                ],
            },
        )

        assert response.status_code == 200, response.text
        # Column-existence probe + FK check
        assert self.mock_session.execute.call_count == 2
        # Delete fired
        branch_chain.filter.return_value.delete.assert_called_once_with(
            synchronize_session=False
        )

    # ------------------------------------------------------------------
    # Remove a branch referenced by sales_invoice -> 409 BRANCH_IN_USE
    # ------------------------------------------------------------------
    def test_remove_referenced_branch_returns_409(self):
        party = _make_party(party_id=42, co_id=1)
        existing = [_make_branch(101, "Addr A"), _make_branch(102, "Blocked Addr")]
        _, branch_chain = _install_query_side_effect(
            self.mock_session, party=party, existing_branches=existing
        )

        # FK check returns one blocking row for branch 102
        blocking_row = MagicMock()
        blocking_row._mapping = {"transporter_branch_id": 102, "ref_count": 7}
        self.mock_session.execute.return_value.fetchall.return_value = [blocking_row]

        response = client.post(
            "/api/partyMaster/party_edit",
            json={
                "co_id": 1,
                "party_id": 42,
                "supp_name": "Acme Inc.",
                "branches": [
                    {"party_mst_branch_id": 101, "address": "Addr A"},
                    # 102 omitted -> attempt to delete -> blocked
                ],
            },
        )

        assert response.status_code == 409, response.text
        body = response.json()
        detail = body["detail"]
        assert detail["code"] == "BRANCH_IN_USE"
        assert "sales invoices" in detail["message"].lower()
        assert detail["blocked_branches"] == [
            {
                "party_mst_branch_id": 102,
                "address": "Blocked Addr",
                "referenced_in_sales_invoices": 7,
            }
        ]
        # Delete must NOT have run
        branch_chain.filter.return_value.delete.assert_not_called()
        # Commit must NOT have run
        self.mock_session.commit.assert_not_called()

    # ------------------------------------------------------------------
    # Mixed: add + edit + remove (unreferenced) in one call
    # ------------------------------------------------------------------
    def test_mixed_add_edit_remove_unreferenced(self):
        party = _make_party(party_id=42, co_id=1)
        existing = [
            _make_branch(101, "Addr A"),
            _make_branch(102, "Addr B"),
            _make_branch(103, "Addr C"),  # to be removed
        ]
        _, branch_chain = _install_query_side_effect(
            self.mock_session, party=party, existing_branches=existing
        )
        # No FK conflicts
        self.mock_session.execute.return_value.fetchall.return_value = []

        response = client.post(
            "/api/partyMaster/party_edit",
            json={
                "co_id": 1,
                "party_id": 42,
                "supp_name": "Acme Inc.",
                "branches": [
                    {"party_mst_branch_id": 101, "address": "Addr A updated"},
                    {"party_mst_branch_id": 102, "address": "Addr B"},
                    # 103 omitted -> delete
                    {"address": "New Addr", "contact_no": "555-0002"},  # insert
                ],
            },
        )

        assert response.status_code == 200, response.text
        # Column-existence probe + FK check
        assert self.mock_session.execute.call_count == 2
        # Delete ran for the removed branch
        branch_chain.filter.return_value.delete.assert_called_once_with(
            synchronize_session=False
        )
        # Exactly one INSERT (the new branch only)
        assert self.mock_session.add.call_count == 1
        added = self.mock_session.add.call_args[0][0]
        assert added.address == "New Addr"
        # In-place update applied to existing row 101
        assert existing[0].address == "Addr A updated"

    # ------------------------------------------------------------------
    # Validation: missing party_id -> 400
    # ------------------------------------------------------------------
    def test_missing_party_id_returns_400(self):
        response = client.post(
            "/api/partyMaster/party_edit",
            json={"co_id": 1, "supp_name": "X"},
        )
        assert response.status_code == 400
        assert "party_id" in response.json()["detail"].lower()

    # ------------------------------------------------------------------
    # Party not found -> 404
    # ------------------------------------------------------------------
    def test_party_not_found_returns_404(self):
        _install_query_side_effect(self.mock_session, party=None, existing_branches=[])

        response = client.post(
            "/api/partyMaster/party_edit",
            json={"co_id": 1, "party_id": 99999, "supp_name": "X"},
        )
        assert response.status_code == 404
