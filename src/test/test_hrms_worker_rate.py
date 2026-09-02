"""Smallest check for the Worker Rate Muster input normalisers."""

import pytest
from fastapi import HTTPException

from src.hrms.workerRate import (
    FLAG_FIELDS,
    RATE_FIELDS,
    _eff_date,
    _flag,
    _rate,
    _validate_bulk,
)


def test_flag_accepts_yn_strings_and_booleans():
    assert _flag({"pf": "Y"}, "pf") == "Y"
    assert _flag({"pf": " y "}, "pf") == "Y"
    assert _flag({"pf": "N"}, "pf") == "N"
    assert _flag({"pf": True}, "pf") == "Y"
    assert _flag({"pf": False}, "pf") == "N"
    assert _flag({}, "pf") == "N"


def test_rate_parses_numbers_and_rejects_bad_input():
    assert _rate({"fbasic": "2672"}, "fbasic") == 2672.0
    assert _rate({"fbasic": 11023.8}, "fbasic") == 11023.8
    assert _rate({"fbasic": ""}, "fbasic") is None
    assert _rate({}, "fbasic") is None
    with pytest.raises(HTTPException):
        _rate({"fbasic": "abc"}, "fbasic")
    with pytest.raises(HTTPException):
        _rate({"fbasic": -1}, "fbasic")


def test_field_sets_match_the_muster_columns():
    assert set(FLAG_FIELDS) == {"da_all", "hra", "hrd", "quarter", "pf", "esi", "ptax"}
    assert set(RATE_FIELDS) == {"fbasic", "fbasic_hr", "da_rate"}


def test_eff_date_parses_and_requires():
    assert _eff_date({"effective_date": "2026-08-31"}).isoformat() == "2026-08-31"
    with pytest.raises(HTTPException):
        _eff_date({})
    with pytest.raises(HTTPException):
        _eff_date({"effective_date": "31/08/2026"})


def test_validate_bulk_whitelists_column_and_op():
    assert _validate_bulk({"column": "da_rate", "op": "add", "value": "105.58"}) == (
        "da_rate", "add", 105.58,
    )
    assert _validate_bulk({"column": "fbasic", "op": "set", "value": 500}) == (
        "fbasic", "set", 500.0,
    )
    # A negative adjustment (rate decrease) is valid for bulk changes.
    assert _validate_bulk({"column": "da_rate", "op": "add", "value": -105.58}) == (
        "da_rate", "add", -105.58,
    )
    # SQL-injection-shaped column names and unknown ops must be rejected.
    for bad in (
        {"column": "da_rate; DROP TABLE x", "op": "add", "value": 1},
        {"column": "is_active", "op": "add", "value": 1},
        {"column": "da_rate", "op": "multiply", "value": 1},
        {"column": "da_rate", "op": "add", "value": "abc"},
    ):
        with pytest.raises(HTTPException):
            _validate_bulk(bad)
