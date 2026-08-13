"""dept_master_create must UPDATE (not insert) when dept_master_id is present.

Calls the handler directly — importing src.main is broken in this environment
(installed FastAPI dropped APIRouter(on_startup=...)), which takes the whole
TestClient-based suite down with it.
"""

import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock
from src.masters.departments import dept_master_create

PAYLOAD = {
    "co_id": 1,
    "branch_id": 2,
    "dept_code": "FIN",
    "dept_name": "Finance",
    "order_id": 3,
    "worker_staff": 2,
}


@pytest.fixture
def session():
    s = MagicMock()
    s.refresh = MagicMock(side_effect=lambda obj: setattr(obj, "dept_id", 42))
    return s


def test_with_dept_master_id_updates_row_and_does_not_insert(session):
    existing = MagicMock(dept_id=7)
    session.query.return_value.filter.return_value.first.return_value = existing

    result = dept_master_create(
        {**PAYLOAD, "dept_master_id": 7}, MagicMock(), db=session, token_data={"user_id": 1}
    )

    assert result == {"message": "Department updated successfully", "dept_master_id": 7}
    session.add.assert_not_called()
    session.commit.assert_called_once()
    assert (existing.dept_code, existing.dept_desc, existing.branch_id) == ("FIN", "Finance", 2)
    assert (existing.order_id, existing.worker_staff, existing.updated_by) == (3, 2, 1)
    assert existing.updated_date_time is not None


def test_unknown_dept_master_id_returns_404(session):
    session.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc:
        dept_master_create(
            {**PAYLOAD, "dept_master_id": 999}, MagicMock(), db=session, token_data={"user_id": 1}
        )
    assert exc.value.status_code == 404


def test_without_dept_master_id_still_inserts(session):
    result = dept_master_create(PAYLOAD, MagicMock(), db=session, token_data={"user_id": 1})

    session.add.assert_called_once()
    inserted = session.add.call_args[0][0]
    assert (inserted.order_id, inserted.worker_staff) == (3, 2)
    assert result["message"] == "Department created successfully"


@pytest.mark.parametrize(
    "overrides",
    [
        {"order_id": None},          # Order is mandatory
        {"order_id": "abc"},         # Order must be numeric
        {"worker_staff": 3},         # only 1 (Worker) / 2 (Staff)
        {"worker_staff": None},
    ],
)
def test_rejects_bad_order_or_department_for(session, overrides):
    with pytest.raises(HTTPException) as exc:
        dept_master_create({**PAYLOAD, **overrides}, MagicMock(), db=session, token_data={"user_id": 1})
    assert exc.value.status_code == 400
