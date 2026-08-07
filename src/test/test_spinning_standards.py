"""Unit tests for src/juteProduction/services/spinning_standards.py.

The resolvers run raw SQL through an injected Session, so the DB is mocked with
MagicMock (same pattern as src/test/test_yarn_quality.py). We assert the float
coercion / fallback contract, not the SQL text itself.
"""

from datetime import date
from unittest.mock import MagicMock

from src.juteProduction.constants import (
    ID_TYPE_MC,
    ID_TYPE_QLTY,
    PARAM_EFF,
    PARAM_SPEED,
    PARAM_TPI,
    VALUE_ROLE_ACTUAL,
    VALUE_ROLE_STANDARD,
)
from src.juteProduction.services.spinning_standards import (
    resolve_act_count,
    resolve_param,
)


ON_DATE = date(2026, 6, 13)


def _db_returning(row):
    """A mock Session whose execute(...).fetchone() yields ``row``."""
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = row
    return db


# =============================================================================
# resolve_param
# =============================================================================


class TestResolveParam:
    def test_returns_value_as_float(self):
        row = MagicMock()
        row.value = 4000.5
        db = _db_returning(row)

        result = resolve_param(
            db, co_id=1, ref_id=10, id_type=ID_TYPE_MC,
            value_role=VALUE_ROLE_STANDARD, param=PARAM_SPEED, on_date=ON_DATE,
        )

        assert result == 4000.5
        assert isinstance(result, float)

    def test_returns_zero_when_no_row(self):
        db = _db_returning(None)
        result = resolve_param(
            db, co_id=1, ref_id=10, id_type=ID_TYPE_QLTY,
            value_role=VALUE_ROLE_STANDARD, param=PARAM_EFF, on_date=ON_DATE,
        )
        assert result == 0.0

    def test_returns_zero_when_value_is_null(self):
        row = MagicMock()
        row.value = None
        db = _db_returning(row)
        result = resolve_param(
            db, co_id=1, ref_id=10, id_type=ID_TYPE_QLTY,
            value_role=VALUE_ROLE_STANDARD, param=PARAM_EFF, on_date=ON_DATE,
        )
        assert result == 0.0


# =============================================================================
# resolve_act_count
# =============================================================================


class TestResolveActCount:
    def test_returns_avg_as_float(self):
        row = MagicMock()
        row.avg_count = 12.5
        db = _db_returning(row)

        result = resolve_act_count(db, co_id=1, item_id=7, on_date=ON_DATE)

        assert result == 12.5
        assert isinstance(result, float)

    def test_returns_zero_when_no_row(self):
        db = _db_returning(None)
        result = resolve_act_count(db, co_id=1, item_id=7, on_date=ON_DATE)
        assert result == 0.0

    def test_returns_zero_when_avg_is_null(self):
        # AVG over no rows yields NULL.
        row = MagicMock()
        row.avg_count = None
        db = _db_returning(row)
        result = resolve_act_count(db, co_id=1, item_id=7, on_date=ON_DATE)
        assert result == 0.0


# =============================================================================
# resolve_param with value_role='actual' — Act Spd / Act TPI now resolve here
# (same table + last-date manner as std/target), not jute_sqc_spinning_entry.
# =============================================================================


class TestResolveActualViaParam:
    def test_actual_speed_resolves_like_std(self):
        row = MagicMock()
        row.value = 3900.0
        db = _db_returning(row)

        result = resolve_param(
            db, co_id=1, ref_id=10, id_type=ID_TYPE_MC,
            value_role=VALUE_ROLE_ACTUAL, param=PARAM_SPEED, on_date=ON_DATE,
        )

        assert result == 3900.0
        assert isinstance(result, float)

    def test_actual_tpi_zero_when_no_row(self):
        db = _db_returning(None)
        result = resolve_param(
            db, co_id=1, ref_id=7, id_type=ID_TYPE_QLTY,
            value_role=VALUE_ROLE_ACTUAL, param=PARAM_TPI, on_date=ON_DATE,
        )
        assert result == 0.0
