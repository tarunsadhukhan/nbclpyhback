"""Tests for pay-register meta columns (PF/UAN/ESI), column layout and totals.

Covers the pure helpers in src.hrms.payRegister that drive how
tbl_payslip_print_component config becomes register columns:
  - META_FIELDS sentinel → source mapping
  - _meta_value            → text lookup for a meta column
  - _build_register_columns → ordered grid/export columns (NO per-row Total)
  - _register_cell_value    → one cell's value
  - _grand_total_row        → vertical grand-total row (numeric columns summed)
"""

from src.hrms.payRegister import (
    META_FIELDS,
    _meta_value,
    _build_register_columns,
    _register_cell_value,
    _grand_total_row,
)


def _comp(cid, label, *, total_print=False, payslip_print=True, group=""):
    """Build a component dict shaped like _resolve_print_components output."""
    is_meta = cid < 0
    return {
        "component_id": cid,
        "label": label,
        "group": group,
        "total_print": total_print,
        "payslip_print": payslip_print,
        "is_meta": is_meta,
        "meta_key": META_FIELDS.get(cid),
    }


class TestMetaFieldMapping:
    def test_sentinels_map_to_expected_sources(self):
        assert META_FIELDS[-4] == "pf_no"
        assert META_FIELDS[-5] == "pf_uan_no"
        assert META_FIELDS[-6] == "esi_no"
        # identity fields sourced from the salary row
        assert META_FIELDS[-1] == "emp_code"
        assert META_FIELDS[-2] == "emp_name"
        assert META_FIELDS[-3] == "department_name"


class TestMetaValue:
    def test_pf_uan_esi_read_from_meta_dict(self):
        emp = {"emp_code": "110199", "meta": {"pf_no": "PF1", "pf_uan_no": "UAN1", "esi_no": "ESI1"}}
        assert _meta_value(emp, "pf_no") == "PF1"
        assert _meta_value(emp, "pf_uan_no") == "UAN1"
        assert _meta_value(emp, "esi_no") == "ESI1"

    def test_identity_keys_read_from_employee_row(self):
        emp = {"emp_code": "110199", "emp_name": "Asha", "department_name": "HR", "meta": {}}
        assert _meta_value(emp, "emp_code") == "110199"
        assert _meta_value(emp, "department_name") == "HR"

    def test_missing_meta_returns_empty_string_not_none(self):
        emp = {"emp_code": "1", "meta": {}}
        assert _meta_value(emp, "pf_no") == ""
        assert _meta_value(emp, None) == ""


class TestBuildRegisterColumns:
    def test_configured_order_with_anchors_meta_no_per_row_total(self):
        components = [
            _comp(-1, "Emp Code"),          # anchor — must be skipped (already leading)
            _comp(101, "Basic", total_print=True),
            _comp(-4, "PF No"),
            _comp(-6, "ESI No"),
            _comp(102, "Net", total_print=True),
        ]
        cols = _build_register_columns(components, used_config=True)
        keys = [c["key"] for c in cols]
        # Emp Code + Name always lead; configured -1 is not duplicated;
        # there is NO per-row __total__ column.
        assert keys[:2] == ["emp_code", "emp_name"]
        assert keys == ["emp_code", "emp_name", "c101", "m4", "m6", "c102"]
        assert "__total__" not in keys
        by_key = {c["key"]: c for c in cols}
        assert by_key["m4"]["kind"] == "text"
        assert by_key["m4"]["meta_key"] == "pf_no"
        assert by_key["c101"]["kind"] == "num"

    def test_fallback_includes_department_and_all_components(self):
        components = [_comp(101, "Basic"), _comp(102, "HRA")]
        cols = _build_register_columns(components, used_config=False)
        keys = [c["key"] for c in cols]
        assert keys == ["emp_code", "emp_name", "department_name", "c101", "c102"]
        assert "__total__" not in keys


class TestRegisterCellValue:
    def test_meta_text_and_component_number(self):
        emp = {
            "emp_code": "110199",
            "emp_name": "Asha",
            "values": {101: 5000.0},
            "meta": {"pf_no": "PF1"},
        }
        pf_col = {"key": "m4", "kind": "text", "meta_key": "pf_no"}
        basic_col = {"key": "c101", "kind": "num", "component_id": 101}
        anchor_col = {"key": "emp_code", "kind": "text"}

        assert _register_cell_value(pf_col, emp) == "PF1"
        assert _register_cell_value(basic_col, emp) == 5000.0
        assert _register_cell_value(anchor_col, emp) == "110199"

    def test_missing_component_value_is_zero(self):
        emp = {"values": {}, "meta": {}}
        col = {"key": "c999", "kind": "num", "component_id": 999}
        assert _register_cell_value(col, emp) == 0.0


class TestGrandTotalRow:
    def test_sums_numeric_columns_and_labels_name(self):
        components = [
            _comp(101, "Basic"),
            _comp(-4, "PF No"),
            _comp(102, "HRA"),
        ]
        cols = _build_register_columns(components, used_config=True)
        employees = [
            {"emp_code": "1", "emp_name": "A", "values": {101: 5000.0, 102: 1000.0}, "meta": {"pf_no": "PF1"}},
            {"emp_code": "2", "emp_name": "B", "values": {101: 3000.0, 102: 500.0}, "meta": {"pf_no": "PF2"}},
        ]
        row = _grand_total_row(cols, employees)
        assert row["emp_name"] == "GRAND TOTAL"
        assert row["emp_code"] == ""        # leading text column blank
        assert row["m4"] == ""              # meta text column never summed
        assert row["c101"] == 8000.0
        assert row["c102"] == 1500.0

    def test_empty_numeric_columns_sum_to_zero(self):
        components = [_comp(101, "Basic")]
        cols = _build_register_columns(components, used_config=True)
        employees = [{"emp_code": "1", "emp_name": "A", "values": {}, "meta": {}}]
        row = _grand_total_row(cols, employees)
        assert row["c101"] == 0.0
