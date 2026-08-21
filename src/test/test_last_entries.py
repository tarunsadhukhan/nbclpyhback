"""Self-check for GET /employees/last-entries row collapsing.

The SQL LEFT JOINs machines, so one employee with two machines comes back as
two rows; the endpoint must collapse them to one row per employee with the
machine ids gathered (and de-duplicated) into a list.
Run: python -m src.test.test_last_entries
"""
from unittest.mock import patch

from flask import Flask

from src.mobileapp.src.employees.employees import employees_bp


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *args, **kwargs):
        pass

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _DB:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self, dictionary=False):
        return _Cursor(self._rows)

    def close(self):
        pass


def _client():
    app = Flask(__name__)
    app.register_blueprint(employees_bp)
    return app.test_client()


def _row(code, dept, desig, mc):
    return {'emp_code': code, 'worked_department_id': dept,
            'worked_designation_id': desig, 'mc_id': mc}


def test_last_entries():
    rows = [
        _row('A1', 8, 21, 5),
        _row('A1', 8, 21, 7),
        _row('A1', 8, 21, 7),      # duplicate machine row
        _row('B2', 9, 22, None),   # employee with no machines
    ]
    with patch('src.mobileapp.src.employees.employees.get_db', lambda: _DB(rows)):
        body = _client().get('/employees/last-entries?branch_id=87').get_json()

    assert body['total'] == 2, body
    a1, b2 = body['data']
    assert a1 == {'emp_code': 'A1', 'dept_id': 8, 'designation_id': 21,
                  'machine_ids': [5, 7]}, a1
    assert b2 == {'emp_code': 'B2', 'dept_id': 9, 'designation_id': 22,
                  'machine_ids': []}, b2

    # branch_id is required — no DB call should even be attempted.
    assert _client().get('/employees/last-entries').status_code == 400


if __name__ == "__main__":
    test_last_entries()
    print("test_last_entries: OK")
