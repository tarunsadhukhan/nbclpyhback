"""Legacy WIL amount rules — expected values are real rows from the legacy Winsome tables."""

import pytest
from fastapi import HTTPException

from src.production.winsomeProduction import FORMS, _parse_lines


def _line(**kw):
    return {"ECode": "095699", "Mch1Code": "M1", **kw}


def test_beaming_matches_legacy_row():
    # PayOProdBMG BMS02: Prod1 192, QRate 0.2289, Prod_HR 8, Mch_HR 8 -> CalcRate 1.783583, Amount 14.27
    ln = _parse_lines(FORMS["beaming"], {"lines": [_line(Prod1=192, QRate=0.2289, Prod_HR=8, Mch_HR=8)]})[0]
    assert ln["CalcRate"] == 1.783583 and ln["Amount"] == 14.27 and ln["PayableAmt"] == 14.27
    head = _parse_lines(FORMS["beaming"], {"lines": [_line(Prod1=192, QRate=0.2289, Prod_HR=8, Mch_HR=8,
                                                           OcpCode="22104")]})[0]
    assert head["PayableAmt"] == round(14.27 + 192 * 0.2289 * 0.026003, 2)


def test_weaving_cuts_and_sixteenths():
    ln = _parse_lines(FORMS["weaving"], {"lines": [_line(Prod1=12.08, QRate=3.4, Prod_HR=8)]})[0]
    assert ln["Amount"] == round(12 * 3.4 + 8 * 0.0625 * 3.4, 2)
    with pytest.raises(HTTPException):
        _parse_lines(FORMS["weaving"], {"lines": [_line(Prod1=12.16, QRate=3.4, Prod_HR=8)]})


def test_plain_and_hour_clamp():
    ln = _parse_lines(FORMS["winding"], {"lines": [_line(Prod1=100, QRate=0.7594, Prod_HR=12)]})[0]
    assert ln["Prod_HR"] == 8 and ln["Amount"] == 75.94


def test_doc_forms_reject_duplicate_employee():
    with pytest.raises(HTTPException):
        _parse_lines(FORMS["productionEntry"], {"lines": [_line(Prod1=1, QRate=33), _line(Prod1=2, QRate=33)]})
    ln = _parse_lines(FORMS["productionEntry"], {"lines": [_line(Prod1=10, QRate=33)]})[0]
    assert ln["Amount"] == 330


def test_weaving_fill_allows_idle_loom_without_employee():
    lines = _parse_lines(FORMS["weaving"], {"lines": [{"Mch1Code": "LM001", "Prod1": "0"}]})
    assert lines[0]["ECode"] == "" and lines[0]["Amount"] == 0
    with pytest.raises(HTTPException):  # still required without a machine, and on non-fill forms
        _parse_lines(FORMS["weaving"], {"lines": [{"Prod1": "1"}]})
    with pytest.raises(HTTPException):
        _parse_lines(FORMS["winding"], {"lines": [{"Mch1Code": "WDG01", "Prod1": "1"}]})
