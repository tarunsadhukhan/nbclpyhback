"""Smallest check for the Misc Earn master payload normaliser."""

import pytest
from fastapi import HTTPException

from src.hrms.miscEarn import EARN_TYPES, _parse_body

BASE = {"branch_id": "87", "dept_id": "15136", "earn_type": "misc earn",
        "amount": "75", "per_hrs": "96"}


def test_parse_body_normalises_sheet_row():
    out = _parse_body({**BASE, "designation_id": "", "remarks": "  RS. 75/- PER 96 HRS "})
    assert out == {
        "branch_id": 87, "dept_id": 15136, "designation_id": None, "cata_id": None,
        "earn_type": "MISC EARN", "amount": 75.0, "per_hrs": 96.0, "rate_pct": 100.0,
        "remarks": "RS. 75/- PER 96 HRS",
    }


def test_beam_changes_keeps_pct():
    out = _parse_body({**BASE, "earn_type": "BEAM CHANGES", "amount": 450, "per_hrs": 880,
                       "rate_pct": 60, "designation_id": 2032, "cata_id": "90"})
    assert (out["amount"], out["per_hrs"], out["rate_pct"], out["designation_id"], out["cata_id"]) == (
        450.0, 880.0, 60.0, 2032, 90)
    # the DB generated column computes this; make sure the inputs reproduce the xlsx value
    assert round(out["amount"] / out["per_hrs"] * out["rate_pct"] / 100, 4) == 0.3068


@pytest.mark.parametrize("bad", [
    {"branch_id": ""}, {"dept_id": None}, {"earn_type": "BONUS"},
    {"amount": "abc"}, {"amount": -1}, {"per_hrs": 0}, {"per_hrs": ""},
])
def test_parse_body_rejects_bad_input(bad):
    with pytest.raises(HTTPException):
        _parse_body({**BASE, **bad})


def test_earn_types_match_the_sheet():
    assert set(EARN_TYPES) == {"MISC EARN", "BEAM CHANGES", "OIL CHARGE"}
