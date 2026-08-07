"""Slice + process query construction tests (no DB — string assertions only)."""

from src.juteProduction.spinning_query import (
    spinning_day_slice_sql,
    get_spinning_planning_slice_query,
    insert_spinning_log_from_slice_query,
    get_spinning_attendance_inactive_query,
    get_spinning_drift_query,
    get_spinning_log_rows_query,
    get_spinning_unmapped_produced_machines_query,
    get_machine_bobbin_batch_query,
)


class TestSpinningDaySlice:
    def test_slice_driver_is_stamped_doffs_union_today_helper(self):
        """Spec 5.5.2 driver: day's doff rows grouped (mc, spell, item) — item
        from the ROW, no frames_winding — UNION helper idle rows gated to
        today only."""
        sql = spinning_day_slice_sql()
        assert "dd.doff_date = :tran_date" in sql  # day filter first in driver
        assert "GROUP BY dd.mc_id, dd.spell, dd.item_id" in sql
        assert "spg_quality_helper" in sql
        assert ":tran_date = CURRENT_DATE()" in sql  # helper branch is today-only
        assert "daily_doff_frames_winding" not in sql  # mapping surface retired
        assert "bm.co_id = :co_id" in sql  # tenant-safety: driver co-scoped

    def test_unmapped_probe_is_null_item_on_doff_rows(self):
        """B1: active doff rows with item_id IS NULL, co-scoped via the machine
        spine — no COALESCE, no frames_winding."""
        sql = str(get_spinning_unmapped_produced_machines_query())
        assert "dd.item_id IS NULL" in sql
        assert "bm.co_id = :co_id" in sql
        assert "daily_doff_frames_winding" not in sql
        assert "COALESCE" not in sql

    def test_attendance_inactive_probe_scopes_sync_stamps(self):
        """W11: only eb_source='sync' rows, missing a live daily_attendance
        backing row for (eb, date, spell_id).

        Keyed on spell_id, never the spell name: spell_code repeats once per
        shift generation (sls 'A1' = 91/97/102), so a name join spans
        generations and under-reports."""
        sql = str(get_spinning_attendance_inactive_query())
        assert "dd.eb_source = 'sync'" in sql
        assert "NOT EXISTS" in sql and "daily_attendance" in sql
        assert "da.spell_id = :spell_id" in sql
        assert "da.spell = " not in sql

    def test_drift_doff_sum_keyed_machine_spell_item(self):
        """Drift doff compare joins on the frozen-row grain (machine, spell,
        item) so item reassignment between groups trips it."""
        sql = str(get_spinning_drift_query())
        assert "GROUP BY mc_id, spell, item_id" in sql
        assert "dff.item_id = sd.item_id" in sql

    def test_slice_has_no_view_reads(self):
        sql = spinning_day_slice_sql()
        assert "vw_winding_daily_reconciled" not in sql
        assert "vw_spinning_planning_grid" not in sql

    def test_slice_uses_set_based_probes(self):
        sql = spinning_day_slice_sql()
        assert "ROW_NUMBER() OVER" in sql          # target-map pivot
        assert "PARTITION BY t2.ref_id, t2.value_role, t2.param" in sql
        assert "jute_prod_winding_doff" in sql      # inline winding reconciliation
        assert "GROUP BY" in sql

    def test_slice_winding_block_is_person_keyed(self):
        """Winding entry is person-keyed: the sub-select must group/join on eb_id
        and co/branch-scope off the doff row itself. The old
        machine_mst -> dept_mst -> branch_mst INNER JOIN chain matched on
        machine_id, which is no longer written — leaving it would drop every new
        row and silently zero winding_total (and so eff_winding)."""
        sql = spinning_day_slice_sql()
        assert "GROUP BY wd.co_id, wd.branch_id, wd.spell_id, wd.eb_id, wd.item_id" in sql
        assert "jo.eb_id = wd.eb_id" in sql
        assert "jc.eb_id = wd.eb_id" in sql
        assert "wd.co_id = :co_id" in sql
        # The machine spine is gone from the winding sub-select.
        assert "wm.machine_id = wd.machine_id" not in sql
        assert "INNER JOIN machine_mst wm" not in sql
        assert "wdp.dept_id" not in sql
        assert "wbm.branch_id" not in sql
        assert "wd.machine_id" not in sql

    def test_slice_winding_rollup_is_unchanged(self):
        """The outer rollup keeps its meaning: winding_total per (item, shift
        bucket), joined to the frame's item and shift."""
        sql = spinning_day_slice_sql()
        assert "GROUP BY wdr.item_id, LEFT(wsp.spell_code, 1)" in sql
        assert "SUM(wdr.reconciled_qty) AS winding_total" in sql
        assert (
            "wnd ON wnd.item_id = f.item_id AND wnd.shift_bucket = LEFT(sp.spell_code, 1)"
            in sql
        )

    def test_drift_winding_block_is_person_keyed(self):
        """Same re-key in the drift probe — a machine-keyed compare would read 0
        winding_total and flag every frozen unit as drifted."""
        sql = str(get_spinning_drift_query())
        assert "GROUP BY wd.co_id, wd.branch_id, wd.spell_id, wd.eb_id, wd.item_id" in sql
        assert "jo.eb_id = wd.eb_id" in sql
        assert "jc.eb_id = wd.eb_id" in sql
        assert "wd.co_id = :co_id" in sql
        assert "INNER JOIN machine_mst wm" not in sql
        assert "wd.machine_id" not in sql
        # The rollup grain is untouched.
        assert "GROUP BY wdr.item_id, LEFT(wsp.spell_code, 1)" in sql

    def test_drift_winding_block_matches_the_slice(self):
        """The freeze writes what the SLICE computes, so the drift probe has to
        reconcile winding the same way. Any divergence reads as permanent drift
        and pins reprocess_needed on every locked unit."""
        drift = str(get_spinning_drift_query())
        slice_sql = spinning_day_slice_sql()
        for predicate in (
            # Jugar is keyed on BRANCH, not co_id — a branch belongs to one company.
            "jo.branch_id = wd.branch_id",
            "jc.branch_id = wd.branch_id",
            "GROUP BY branch_id, spell_id, eb_id",
            "GROUP BY wd.co_id, wd.branch_id, wd.spell_id, wd.eb_id, wd.item_id",
        ):
            assert predicate in slice_sql, predicate
            assert predicate in drift, predicate

    def test_slice_windowed_allocation_is_day_bounded(self):
        sql = spinning_day_slice_sql()
        assert "SUM(calc.act_prod_doff) OVER" in sql
        assert "PARTITION BY calc.co_id, calc.tran_date, calc.item_id, calc.shift_bucket" in sql

    def test_planning_slice_query_orders_by_mech_code(self):
        assert "ORDER BY" in str(get_spinning_planning_slice_query())

    def test_log_insert_selects_from_slice(self):
        sql = str(insert_spinning_log_from_slice_query())
        assert "INSERT INTO jute_prod_spinning_daily" in sql
        assert "SELECT" in sql and "ROW_NUMBER() OVER" in sql

    def test_drift_query_compares_three_sources(self):
        sql = str(get_spinning_drift_query())
        for col in ("act_count", "act_prod_doff", "winding_total"):
            assert col in sql

    def test_log_rows_query_is_unit_scoped(self):
        sql = str(get_spinning_log_rows_query())
        assert "jute_prod_spinning_daily" in sql
        assert "co_id = :co_id" in sql and "tran_date = :tran_date" in sql

    def test_bobbin_batch_query_pivots_by_machine(self):
        sql = str(get_machine_bobbin_batch_query())
        assert "bobbin_wt" in sql and "ROW_NUMBER() OVER" in sql
