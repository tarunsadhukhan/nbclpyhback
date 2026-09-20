"""Code generation for new outsiders registered from the mobile app.

The rules under test: the series is the first three characters, numbering is
per branch, the number is zero-padded to four, and a number some other branch
already used is skipped rather than handed out twice.
"""

import pytest

from src.mobileapp.src.onboarding.onboarding import (
    _next_code, _validated_gender, _validated_series,
)


class FakeCursor:
    """Answers the two queries _next_code runs, without a database."""

    def __init__(self, last_no, taken=()):
        self._last_no = last_no
        self._taken = set(taken)
        self._pending = None

    def execute(self, sql, params):
        if "MAX(" in sql:
            self._pending = {"last_no": self._last_no}
        else:                                   # CODE_EXISTS_ANYWHERE
            code = params[0]
            self._pending = {"1": 1} if code in self._taken else None

    def fetchone(self):
        return self._pending


def test_next_code_is_last_plus_one_padded_to_four():
    assert _next_code(FakeCursor(2196), "FOS", 87) == "FOS2197"
    assert _next_code(FakeCursor(2856), "MOS", 87) == "MOS2857"


def test_first_ever_code_in_a_series_starts_at_one():
    assert _next_code(FakeCursor(0), "FOS", 87) == "FOS0001"


def test_numbers_taken_by_another_branch_are_skipped():
    # This branch's max is 2196, but 2197 and 2198 exist elsewhere.
    cursor = FakeCursor(2196, taken={"FOS2197", "FOS2198"})
    assert _next_code(cursor, "FOS", 87) == "FOS2199"


def test_padding_gives_way_once_the_series_passes_four_digits():
    assert _next_code(FakeCursor(9999), "FOS", 87) == "FOS10000"


@pytest.mark.parametrize("raw,expected", [
    ("FOS", "FOS"), ("mos", "MOS"), (" fos ", "FOS"),
    ("OS", None), ("RJM", None), ("", None), (None, None), ("FOSX", None),
])
def test_only_the_two_outsider_series_are_accepted(raw, expected):
    assert _validated_series(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    # Normalised to the ERP's own spelling, whatever case arrives.
    ("Male", "Male"), ("male", "Male"), ("FEMALE", "Female"), (" other ", "Other"),
    ("M", None), ("F", None), ("", None), (None, None), ("unknown", None),
])
def test_gender_is_normalised_to_the_erp_spelling(raw, expected):
    assert _validated_gender(raw) == expected
