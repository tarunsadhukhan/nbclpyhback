"""
Live check of the Winsome gratuity endpoints against the winsome tenant DB (needs env/database.env).
Writes run inside one transaction that is rolled back — nothing is kept.

    python -m pytest src/test/test_winsome_gratuity.py -q
"""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text
from starlette.requests import Request

from src.config.db import get_tenant_engine
from src.hrms import winsomeGratuity as g

TOKEN = {"user_id": 4}


def _req(**q) -> Request:
    qs = "&".join(f"{k}={v}" for k, v in q.items()).encode()
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": qs, "headers": []})


@pytest.fixture()
def db():
    try:
        engine = get_tenant_engine("winsome")
        s = sessionmaker(bind=engine)()
        s.execute(text("SELECT 1 FROM PayGratOSTL LIMIT 1"))
    except Exception as e:  # no DB access here
        pytest.skip(f"winsome DB not reachable: {e}")
    s.commit = s.flush  # keep every write inside the test transaction
    yield s
    s.rollback()
    s.close()


def test_reads(db):
    assert "DEATH" in g.grat_setup(db, TOKEN)["data"]["exit_reasons"]
    years = g.grat_years(_req(**{"from": "2001-05-01", "to": "2004-02-01"}), db, TOKEN)["data"]
    assert [y["GYear"] for y in years] == [2001, 2002, 2003, 2004]
    assert next(y for y in years if y["GYear"] == 2003)["StrikeDays"] == 147  # PayOTSW 2003
    lst = g.grat_list("stl", _req(limit=5), db, TOKEN)
    assert lst["total"] > 3000 and len(lst["data"]) == 5
    doc = g.grat_doc("stl", int(lst["data"][0]["DocEntry"]), db, TOKEN)["data"]
    assert doc["lines"] and doc["header"]["ECode"]
    assert g.voucher_list(_req(), db, TOKEN)["data"]
    with pytest.raises(HTTPException):
        g.grat_list("voucher", _req(), db, TOKEN)


def test_calc_from_stl_appends_years(db):
    """A leaver with an STL record: the calculation starts from it and adds the years up to leaving."""
    row = db.execute(text("""SELECT e.ECode, YEAR(e.LeavingDate) FROM PayOEMP e JOIN PayGratOSTL s ON s.ECode = e.ECode
                             WHERE e.LeavingDate > e.DoJ AND e.ECode NOT IN (SELECT ECode FROM PayGratOGratuity)
                               AND YEAR(e.LeavingDate) > 2023 LIMIT 1""")).first()
    if not row:
        pytest.skip("no leaver with an open STL record")
    new = g.grat_new("calc", row[0], db, TOKEN)["data"]
    years = [int(ln["GYear"]) for ln in new["lines"]]
    assert years == sorted(years) and len(set(years)) == len(years) and years[-1] == row[1]
    assert new["header"]["FromSTL"] and new["header"]["DocMode"] == "DRAFT"


def test_stl_save_update_and_voucher_flow(db):
    ecode = db.execute(text("""SELECT ECode FROM PayOEMP WHERE ECode <> '' AND ECode NOT IN
                               (SELECT ECode FROM PayGratOSTL UNION SELECT ECode FROM PayGratOGratuity) LIMIT 1""")).scalar()
    new = g.grat_new("stl", ecode, db, TOKEN)["data"]
    lines = [{"GYear": 2021, "WorkingDays": 250, "TSWAllow": "Y", "STLEarned": 13, "Eligible": "Y", "FinalCount": 1,
              "TotalDays": 250}, {"GYear": 2022, "WorkingDays": 100, "TSWAllow": "Y"}]
    header = new["header"] | {"AvgRatePerDay": 300, "GratuityAmt": 4500, "AdvanceAgainstGrat": 10}
    de = g.grat_save("stl", {"header": header, "lines": lines, "nominees": []}, db, TOKEN)["doc_entry"]
    doc = g.grat_doc("stl", de, db, TOKEN)["data"]
    assert doc["header"]["WagesRate"] == 300 and doc["header"]["Advance"] == 10
    assert doc["header"]["DocMode"] == "DRAFT" and [ln["GYear"] for ln in doc["lines"]] == [2021, 2022]
    with pytest.raises(HTTPException):  # same employee twice
        g.grat_save("stl", {"header": header, "lines": lines}, db, TOKEN)
    doc["header"]["ORemarks"] = "edited"
    g.grat_save("stl", {"header": doc["header"], "lines": doc["lines"][:1], "nominees": []}, db, TOKEN)
    again = g.grat_doc("stl", de, db, TOKEN)["data"]
    assert again["header"]["ORemarks"] == "edited" and len(again["lines"]) == 1

    # Voucher: request -> mismatched update refused -> approve -> locked.
    gcode = db.execute(text(f"SELECT ECode, EName, FinalNetAmt FROM PayGratOGratuity WHERE ECode NOT IN "
                            f"(SELECT ECode FROM {g.VOUCHER}) LIMIT 1")).first()
    if not gcode:
        return
    h = {"ECode": gcode[0], "EName": gcode[1], "DocDate": "2026-11-22", "GratAmount": 1000}
    vde = g.voucher_save({"header": h, "lines": [{"GPAmt": 600, "NomineeName": "A"}, {"GPAmt": 400}]},
                         db, TOKEN)["doc_entry"]
    v = g.voucher_doc(vde, db, TOKEN)["data"]
    assert len(v["lines"]) == 2 and v["header"]["DocMode"] == "DRAFT"
    with pytest.raises(HTTPException):  # total != gratuity amount
        g.voucher_save({"header": v["header"] | {"GratAmount": 999}, "lines": v["lines"]}, db, TOKEN)
    with pytest.raises(HTTPException):  # duplicate cheque
        g.voucher_approve({"DocEntry": vde, "lines": [{"LineID": 1, "ChequeNo": "X1", "ChequeDate": "2026-11-22"},
                                                      {"LineID": 2, "ChequeNo": "X1", "ChequeDate": "2026-11-22"}]},
                          db, TOKEN)
    g.voucher_approve({"DocEntry": vde, "lines": [{"LineID": 1, "ChequeNo": "X1", "ChequeDate": "2026-11-22"},
                                                  {"LineID": 2, "ChequeNo": "X2", "ChequeDate": "2026-11-22"}]},
                      db, TOKEN)
    assert g.voucher_doc(vde, db, TOKEN)["data"]["header"]["DocMode"] == "APPROVED"
    with pytest.raises(HTTPException):
        g.voucher_save({"header": v["header"], "lines": v["lines"]}, db, TOKEN)


def test_tsw_round_trip(db):
    rows = g.tsw_list(db, TOKEN)["data"]
    n = len(rows)
    rows[-1]["TSW"] = 5
    rows[-1]["LockOut"] = 2
    g.tsw_save({"rows": rows}, db, TOKEN)
    after = g.tsw_list(db, TOKEN)["data"]
    assert len(after) == n and any(r["Total"] == 7 for r in after)
