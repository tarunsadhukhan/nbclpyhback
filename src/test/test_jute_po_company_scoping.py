"""
Regression tests for jute PO company-scoping bugs.

Background: A jute PO was found in production with a party_id belonging to a
different company than the PO's branch. Root cause: get_parties_by_supplier
endpoint and underlying SQL did not filter by co_id at all, so the dropdown
could return parties mapped to the supplier in any company. Even after
fixing the dropdown query, jute_po_create / jute_po_update did not validate
that the posted party_id was actually mapped to (supplier_id, co_id) in
jute_supp_party_map, so a stale client cache or direct API call could still
recreate the bug. These tests lock in both layers of the fix.
"""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.juteProcurement.jutePO import (
    _validate_branch_belongs_to_co,
    _validate_supplier_party_for_co,
)
from src.juteProcurement.query import (
    get_all_suppliers_query,
    get_parties_by_supplier_query,
)


# =============================================================================
# SQL queries — must reference :co_id
# =============================================================================


class TestQueriesAreCoIdScoped:
    """The SQL itself must include :co_id — defense in the data layer."""

    def test_parties_by_supplier_query_filters_by_co_id(self):
        sql = str(get_parties_by_supplier_query())
        assert ":co_id" in sql, (
            "get_parties_by_supplier_query MUST filter by :co_id — without it "
            "the dropdown leaks parties from other companies (regression of "
            "the cross-company party_id bug)."
        )
        assert ":supplier_id" in sql

    def test_all_suppliers_query_filters_by_co_id(self):
        sql = str(get_all_suppliers_query())
        assert ":co_id" in sql, (
            "get_all_suppliers_query MUST scope by :co_id via "
            "jute_supp_party_map; jute_supplier_mst itself has no co_id."
        )


# =============================================================================
# _validate_branch_belongs_to_co
# =============================================================================


def _mock_db_branch_co(branch_co_id):
    """Build a MagicMock db.execute(...).fetchone() returning a row with .co_id."""
    db = MagicMock()
    if branch_co_id is None:
        db.execute.return_value.fetchone.return_value = None
    else:
        row = MagicMock()
        row.co_id = branch_co_id
        db.execute.return_value.fetchone.return_value = row
    return db


class TestValidateBranchBelongsToCo:
    def test_matching_co_id_passes(self):
        db = _mock_db_branch_co(9)
        # Should not raise
        _validate_branch_belongs_to_co(db, branch_id=12, co_id=9)

    def test_mismatched_co_id_raises_400(self):
        db = _mock_db_branch_co(9)
        with pytest.raises(HTTPException) as exc:
            _validate_branch_belongs_to_co(db, branch_id=12, co_id=1)
        assert exc.value.status_code == 400
        assert "company" in exc.value.detail.lower()

    def test_unknown_branch_raises_400(self):
        db = _mock_db_branch_co(None)
        with pytest.raises(HTTPException) as exc:
            _validate_branch_belongs_to_co(db, branch_id=99999, co_id=1)
        assert exc.value.status_code == 400
        assert "branch" in exc.value.detail.lower()


# =============================================================================
# _validate_supplier_party_for_co — the core bug
# =============================================================================


def _mock_db_mapping_exists(exists: bool):
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (1,) if exists else None
    return db


class TestValidateSupplierPartyForCo:
    def test_valid_mapping_passes(self):
        db = _mock_db_mapping_exists(True)
        # Should not raise
        _validate_supplier_party_for_co(
            db, supplier_id=804, party_id=7729, co_id=9
        )

    def test_cross_company_party_raises_400(self):
        """The exact regression scenario from the production audit:
        supplier 804 + party 7729 are mapped under co_id=1 in the live data,
        but a PO was created on a branch belonging to co_id=9. With the fix,
        this combination must be rejected."""
        db = _mock_db_mapping_exists(False)
        with pytest.raises(HTTPException) as exc:
            _validate_supplier_party_for_co(
                db, supplier_id=804, party_id=7729, co_id=9
            )
        assert exc.value.status_code == 400
        assert "party_id" in exc.value.detail
        assert "company" in exc.value.detail.lower()

    def test_orphan_party_for_supplier_raises_400(self):
        """Audit also surfaced a row where (supplier=837, party=316) had no
        jute_supp_party_map entry in any company at all — historical/orphan
        data. The fix must reject this on new writes too."""
        db = _mock_db_mapping_exists(False)
        with pytest.raises(HTTPException) as exc:
            _validate_supplier_party_for_co(
                db, supplier_id=837, party_id=316, co_id=1
            )
        assert exc.value.status_code == 400

    def test_null_party_with_supplier_mapped_in_co_passes(self):
        """party_id is nullable on the PO; if the supplier has at least one
        mapping for the company we accept party_id=None."""
        db = _mock_db_mapping_exists(True)
        # Should not raise
        _validate_supplier_party_for_co(
            db, supplier_id=804, party_id=None, co_id=9
        )

    def test_null_party_supplier_not_in_co_raises_400(self):
        db = _mock_db_mapping_exists(False)
        with pytest.raises(HTTPException) as exc:
            _validate_supplier_party_for_co(
                db, supplier_id=804, party_id=None, co_id=9
            )
        assert exc.value.status_code == 400
        assert "supplier" in exc.value.detail.lower()
