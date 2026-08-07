"""Tests for Beaming Production Entry endpoints (Page C).

Tests for src/juteProduction/beaming_entry.py (prefix /api/beamingProd).

Portal persona: DB + auth mocked (no real DB). get_tenant_db /
get_current_user_with_refresh are imported into the router module's namespace and
resolved by FastAPI via Depends, so we override them through
app.dependency_overrides keyed by those exact symbols. The resolver
(resolve_machine_standards) and the calc (compute_beaming_daily) are patched on the
router module where they are looked up, so no real standards/formula code runs.

Covered:
  * happy path (entry_create_setup)
  * missing co_id -> 400 (entry_create_setup)
  * composite-quality (is_composite=1) COMPUTES via _dtl components (entry_create, §Q3)
    — the old composite-block-400 guard is REMOVED.
  * successful simple-quality (is_composite=0) create (entry_create)
  * beam_no round-trip — stored in the snapshot bind params + returned (entry_create, Q10)
  * net working_hours — idle (stoppage) SUM subtracted from gross spell hours before
    compute_beaming_daily (entry_create, Q8)
  * dia resolved from the machine standard (Q7); rpm is NOT a production input — it is
    sourced from the future Beaming SQC page (tab, like Spinning SQC), so production entry
    passes NO rpm into compute_beaming_daily and act_speed = 0 until SQC is wired (SQC seam)
"""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.main import app
from src.juteProduction.beaming_entry import (
    get_tenant_db,
    get_current_user_with_refresh,
)

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _quality_row(*, item_id, is_composite, ends=272, std_count=13.0):
    """Attribute-access row for _fetch_quality (uses row.item_id / row.is_composite)."""
    row = MagicMock()
    row.bm_quality_id = 5
    row.item_id = item_id
    row.ends = ends
    row.std_count = std_count
    row.is_composite = is_composite
    return row


class TestEntryCreateSetup:
    """GET /api/beamingProd/entry_create_setup"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_lookups(self):
        machine_rows = [_mock_row({"machine_id": 7, "machine_name": "Beam-1", "mech_code": "BM01"})]
        spell_rows = [_mock_row({
            "spell_id": 1, "spell_code": "A1", "spell_name": "Morning", "working_hours": 8.0,
        })]
        eb_rows = [_mock_row({
            "eb_id": 3, "emp_code": "EMP-3", "eb_name": "Jane Doe", "branch_id": 2,
        })]
        quality_rows = [_mock_row({
            "bm_quality_id": 5, "item_id": 10, "item_code": "JC-RED", "item_name": "Jute Cloth Red",
            "bm_quality_code": "272-13/272", "bm_quality_name": "Red", "std_count": 13.0,
        })]
        exec_machines = MagicMock(); exec_machines.fetchall.return_value = machine_rows
        exec_spells = MagicMock(); exec_spells.fetchall.return_value = spell_rows
        exec_eb = MagicMock(); exec_eb.fetchall.return_value = eb_rows
        exec_qualities = MagicMock(); exec_qualities.fetchall.return_value = quality_rows
        self._mock_session.execute.side_effect = [
            exec_machines, exec_spells, exec_eb, exec_qualities,
        ]

        response = client.get("/api/beamingProd/entry_create_setup?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["machines"][0]["machine_id"] == 7
        assert data["spells"][0]["spell_code"] == "A1"
        assert data["eb_list"][0]["eb_id"] == 3
        assert data["eb_list"][0]["emp_code"] == "EMP-3"
        assert data["items"][0]["item_id"] == 10
        assert data["qualities"][0]["bm_quality_code"] == "272-13/272"

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/beamingProd/entry_create_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


class TestEntryCreate:
    """POST /api/beamingProd/entry_create"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _payload(self):
        # dia_roller is NO LONGER an entry input (Q7) — it is resolved server-side from the
        # machine standard. rpm_roller is NO LONGER a production input either — the ACTUAL
        # roller speed is entered on the future Beaming SQC page (tab, like Spinning SQC),
        # so it is omitted here (SQC seam). beam_no is the physical beam number (Q10).
        return {
            "co_id": 1,
            "tran_date": "2026-06-21",
            "spell_id": 1,
            "machine_id": 7,
            "item_id": 10,
            "bm_quality_id": 5,
            "beam_no": "BEAM-007",
            "act_cuts": 4,
            "no_of_beam": 2,
        }

    @patch("src.juteProduction.beaming_entry.compute_beaming_daily")
    @patch("src.juteProduction.beaming_entry.resolve_machine_standards")
    def test_composite_quality_computes_via_components(self, mock_resolve, mock_compute):
        """is_composite=1 no longer 400s (§Q3): the server loads the active
        jute_prod_bm_quality_dtl components, passes their (ends, count) pairs into
        compute_beaming_daily for the Σ_n kg_per_cut, and stores ends=SUM(component
        ends) / std_count=NULL on the snapshot."""
        mock_resolve.return_value = {
            "laid_length": 1200.0, "cuts_per_beam": 50.0, "std_speed": 100.0,
            "target_speed": 110.0, "std_eff": 85.0, "target_eff": 90.0, "dia": 12.0,
        }
        mock_compute.return_value = {
            "act_speed": 31.4, "yards_per_beam": 60000.0, "kg_per_cut": 2.7,
            "kg_per_beam": 135.0, "p100prod": 48000.0, "std_prod": 40800.0,
            "target_prod": 43200.0, "act_prod_yards": 9600.0, "act_prod_kg": 21.6,
            "act_eff": 20.0,
        }

        # Execute order for a COMPOSITE quality (branch omitted in payload):
        #   1. _fetch_quality            -> quality row (is_composite=1)
        #   2. _spell_working_hours      -> gross working_hours row (Q8)
        #   3. _idle_hours               -> idle_hours row (Q8)
        #   4. _composite_components     -> fetchall of jute_prod_bm_quality_dtl (§Q3)
        #   5. _derive_branch_id         -> branch row
        #   6. active-row lookup         -> None (no existing)
        #   7. insert_beaming_daily      -> lastrowid
        q_exec = MagicMock(); q_exec.fetchone.return_value = _quality_row(
            item_id=10, is_composite=1, ends=None, std_count=None
        )
        wh_exec = MagicMock()
        wh_row = MagicMock(); wh_row.working_hours = 8.0
        wh_exec.fetchone.return_value = wh_row
        idle_exec = MagicMock()
        idle_row = MagicMock(); idle_row.idle_hours = 0.0
        idle_exec.fetchone.return_value = idle_row
        comp_exec = MagicMock()
        comp_exec.fetchall.return_value = [
            _mock_row({"ends": 120, "count": 8.0}),
            _mock_row({"ends": 160, "count": 10.0}),
        ]
        branch_exec = MagicMock()
        branch_row = MagicMock(); branch_row.branch_id = 2
        branch_exec.fetchone.return_value = branch_row
        active_exec = MagicMock(); active_exec.fetchone.return_value = None
        insert_exec = MagicMock(); insert_exec.lastrowid = 888
        self._mock_session.execute.side_effect = [
            q_exec, wh_exec, idle_exec, comp_exec, branch_exec, active_exec, insert_exec,
        ]

        response = client.post("/api/beamingProd/entry_create", json=self._payload())

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["beaming_daily_id"] == 888
        assert data["computed"]["kg_per_cut"] == 2.7  # Σ_n composite kg/cut
        self._mock_session.commit.assert_called_once()

        # compute received the composite component pairs (Σ_n source) + ends = SUM(120+160).
        _inputs_arg, standards_arg = mock_compute.call_args.args
        assert standards_arg["components"] == [
            {"ends": 120.0, "count": 8.0},
            {"ends": 160.0, "count": 10.0},
        ]
        assert standards_arg["ends"] == 280.0       # SUM of component ends (§Q3)
        assert standards_arg["std_count"] is None    # composite parent std_count NULL

        # The INSERT snapshot stores ends=SUM and a NULL std_count for the composite parent.
        insert_params = self._mock_session.execute.call_args_list[6].args[1]
        assert insert_params["ends"] == 280
        assert insert_params["std_count"] is None

    def test_composite_no_components_returns_400(self):
        """A composite quality with no active _dtl rows is a data-integrity error (§Q3)."""
        with patch("src.juteProduction.beaming_entry.resolve_machine_standards") as mock_resolve:
            mock_resolve.return_value = {
                "laid_length": 1200.0, "cuts_per_beam": 50.0, "std_speed": 100.0,
                "target_speed": 110.0, "std_eff": 85.0, "target_eff": 90.0, "dia": 12.0,
            }
            q_exec = MagicMock(); q_exec.fetchone.return_value = _quality_row(
                item_id=10, is_composite=1, ends=None, std_count=None
            )
            wh_exec = MagicMock()
            wh_row = MagicMock(); wh_row.working_hours = 8.0
            wh_exec.fetchone.return_value = wh_row
            idle_exec = MagicMock()
            idle_row = MagicMock(); idle_row.idle_hours = 0.0
            idle_exec.fetchone.return_value = idle_row
            empty_comp_exec = MagicMock(); empty_comp_exec.fetchall.return_value = []
            self._mock_session.execute.side_effect = [
                q_exec, wh_exec, idle_exec, empty_comp_exec,
            ]

            response = client.post("/api/beamingProd/entry_create", json=self._payload())

            assert response.status_code == 400
            assert "component" in response.json()["detail"].lower()
            self._mock_session.commit.assert_not_called()

    @patch("src.juteProduction.beaming_entry.compute_beaming_daily")
    @patch("src.juteProduction.beaming_entry.resolve_machine_standards")
    def test_simple_quality_create_success(self, mock_resolve, mock_compute):
        """is_composite=0 -> server resolves standards, computes snapshot, inserts."""
        mock_resolve.return_value = {
            "laid_length": 1200.0, "cuts_per_beam": 50.0, "std_speed": 100.0,
            "target_speed": 110.0, "std_eff": 85.0, "target_eff": 90.0, "dia": 12.0,
        }
        mock_compute.return_value = {
            "act_speed": 31.4, "yards_per_beam": 60000.0, "kg_per_cut": 1.5,
            "kg_per_beam": 75.0, "p100prod": 48000.0, "std_prod": 40800.0,
            "target_prod": 43200.0, "act_prod_yards": 9600.0, "act_prod_kg": 12.0,
            "act_eff": 20.0,
        }

        # Execute order in entry_create for a simple quality:
        #   1. _fetch_quality          -> fetchone quality row (is_composite=0)
        #   2. _spell_working_hours    -> fetchone working_hours row (gross, Q8)
        #   3. _idle_hours             -> fetchone idle_hours row (Q8)
        #   4. _derive_branch_id       -> fetchone branch row (branch omitted in payload)
        #   5. get_beaming_daily_active_row_query -> fetchone None (no existing)
        #   6. insert_beaming_daily_query -> result with lastrowid
        q_exec = MagicMock(); q_exec.fetchone.return_value = _quality_row(item_id=10, is_composite=0)
        wh_exec = MagicMock()
        wh_row = MagicMock(); wh_row.working_hours = 8.0
        wh_exec.fetchone.return_value = wh_row
        idle_exec = MagicMock()
        idle_row = MagicMock(); idle_row.idle_hours = 0.0
        idle_exec.fetchone.return_value = idle_row
        branch_exec = MagicMock()
        branch_row = MagicMock(); branch_row.branch_id = 2
        branch_exec.fetchone.return_value = branch_row
        active_exec = MagicMock(); active_exec.fetchone.return_value = None
        insert_exec = MagicMock(); insert_exec.lastrowid = 555
        self._mock_session.execute.side_effect = [
            q_exec, wh_exec, idle_exec, branch_exec, active_exec, insert_exec,
        ]

        response = client.post("/api/beamingProd/entry_create", json=self._payload())

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["beaming_daily_id"] == 555
        assert data["computed"]["act_eff"] == 20.0
        self._mock_session.commit.assert_called_once()

        # The resolver is now called with the bm_quality_id (qid ref) so the quality-linked
        # std cuts/beam, laid_length and eff resolve off the Beaming Quality Master.
        # Signature: resolve_machine_standards(db, co_id, machine_id, bm_quality_id, tran_date).
        resolve_args = mock_resolve.call_args.args
        assert resolve_args[3] == 5  # bm_quality_id from the payload

        # dia comes from the resolved machine STANDARD (Q7), NOT a client input. rpm is NOT
        # a production input — it is sourced from the future Beaming SQC page (SQC seam), so
        # production entry passes NO rpm into compute. Neither dia_roller nor rpm_roller is
        # present in the compute inputs.
        inputs_arg, standards_arg = mock_compute.call_args.args
        assert standards_arg["dia"] == 12.0          # resolved machine standard (Q7)
        assert "dia_roller" not in inputs_arg          # dia is a standard now, not an input
        assert "rpm_roller" not in inputs_arg          # rpm comes from SQC, not production entry

        # The snapshot persists dia_roller = the resolved standard, not a client value; and
        # rpm_roller binds NULL (SQC populates it later, act_speed = 0 until then).
        insert_params = self._mock_session.execute.call_args_list[5].args[1]
        assert insert_params["dia_roller"] == 12.0
        assert insert_params["rpm_roller"] is None

    @patch("src.juteProduction.beaming_entry.compute_beaming_daily")
    @patch("src.juteProduction.beaming_entry.resolve_machine_standards")
    def test_beam_no_round_trip(self, mock_resolve, mock_compute):
        """beam_no (Q10) is carried into the snapshot INSERT bind params verbatim."""
        mock_resolve.return_value = {
            "laid_length": 1200.0, "cuts_per_beam": 50.0, "std_speed": 100.0,
            "target_speed": 110.0, "std_eff": 85.0, "target_eff": 90.0, "dia": 12.0,
        }
        mock_compute.return_value = {
            "act_speed": 31.4, "yards_per_beam": 60000.0, "kg_per_cut": 1.5,
            "kg_per_beam": 75.0, "p100prod": 48000.0, "std_prod": 40800.0,
            "target_prod": 43200.0, "act_prod_yards": 9600.0, "act_prod_kg": 12.0,
            "act_eff": 20.0,
        }
        # Same execute order as the simple-create happy path.
        q_exec = MagicMock(); q_exec.fetchone.return_value = _quality_row(item_id=10, is_composite=0)
        wh_exec = MagicMock()
        wh_row = MagicMock(); wh_row.working_hours = 8.0
        wh_exec.fetchone.return_value = wh_row
        idle_exec = MagicMock()
        idle_row = MagicMock(); idle_row.idle_hours = 0.0
        idle_exec.fetchone.return_value = idle_row
        branch_exec = MagicMock()
        branch_row = MagicMock(); branch_row.branch_id = 2
        branch_exec.fetchone.return_value = branch_row
        active_exec = MagicMock(); active_exec.fetchone.return_value = None
        insert_exec = MagicMock(); insert_exec.lastrowid = 600
        self._mock_session.execute.side_effect = [
            q_exec, wh_exec, idle_exec, branch_exec, active_exec, insert_exec,
        ]

        response = client.post("/api/beamingProd/entry_create", json=self._payload())

        assert response.status_code == 200
        insert_params = self._mock_session.execute.call_args_list[5].args[1]
        assert insert_params["beam_no"] == "BEAM-007"  # round-tripped from the payload (Q10)

    @patch("src.juteProduction.beaming_entry.compute_beaming_daily")
    @patch("src.juteProduction.beaming_entry.resolve_machine_standards")
    def test_net_working_hours_subtracts_idle(self, mock_resolve, mock_compute):
        """working_hours passed to compute = max(0, gross spell hours − Σ idle hours) (Q8).

        gross = 8.0 (spell_mst), idle = 1.5 (Σ jute_prod_stoppage_hours via
        get_beaming_idle_hours_query) -> net = 6.5 flows into compute_beaming_daily and the
        persisted snapshot, NOT the gross 8.0."""
        mock_resolve.return_value = {
            "laid_length": 1200.0, "cuts_per_beam": 50.0, "std_speed": 100.0,
            "target_speed": 110.0, "std_eff": 85.0, "target_eff": 90.0, "dia": 12.0,
        }
        mock_compute.return_value = {
            "act_speed": 31.4, "yards_per_beam": 60000.0, "kg_per_cut": 1.5,
            "kg_per_beam": 75.0, "p100prod": 48000.0, "std_prod": 40800.0,
            "target_prod": 43200.0, "act_prod_yards": 9600.0, "act_prod_kg": 12.0,
            "act_eff": 20.0,
        }
        q_exec = MagicMock(); q_exec.fetchone.return_value = _quality_row(item_id=10, is_composite=0)
        wh_exec = MagicMock()
        wh_row = MagicMock(); wh_row.working_hours = 8.0      # gross spell hours
        wh_exec.fetchone.return_value = wh_row
        idle_exec = MagicMock()
        idle_row = MagicMock(); idle_row.idle_hours = 1.5     # Σ stoppage hours (Q8)
        idle_exec.fetchone.return_value = idle_row
        branch_exec = MagicMock()
        branch_row = MagicMock(); branch_row.branch_id = 2
        branch_exec.fetchone.return_value = branch_row
        active_exec = MagicMock(); active_exec.fetchone.return_value = None
        insert_exec = MagicMock(); insert_exec.lastrowid = 601
        self._mock_session.execute.side_effect = [
            q_exec, wh_exec, idle_exec, branch_exec, active_exec, insert_exec,
        ]

        response = client.post("/api/beamingProd/entry_create", json=self._payload())

        assert response.status_code == 200
        # compute received the NET working_hours (8.0 − 1.5 = 6.5), not the gross.
        _inputs_arg, standards_arg = mock_compute.call_args.args
        assert standards_arg["working_hours"] == 6.5
        # ...and the persisted snapshot stores the same net value.
        insert_params = self._mock_session.execute.call_args_list[5].args[1]
        assert insert_params["working_hours"] == 6.5

    @patch("src.juteProduction.beaming_entry.resolve_machine_standards")
    def test_quality_item_mismatch_returns_400(self, mock_resolve):
        """Quality belongs to a different item than the one chosen -> 400."""
        q_exec = MagicMock()
        q_exec.fetchone.return_value = _quality_row(item_id=99, is_composite=0)
        self._mock_session.execute.return_value = q_exec

        response = client.post("/api/beamingProd/entry_create", json=self._payload())

        assert response.status_code == 400
        assert "does not belong" in response.json()["detail"].lower()
        mock_resolve.assert_not_called()

    def test_quality_not_found_returns_404(self):
        q_exec = MagicMock()
        q_exec.fetchone.return_value = None
        self._mock_session.execute.return_value = q_exec

        response = client.post("/api/beamingProd/entry_create", json=self._payload())

        assert response.status_code == 404


class TestEntrySurfaceSpeedDerivation:
    """RPM -> SURFACE-SPEED model end-to-end (LOCKED CONTRACT).

    These tests mock ONLY resolve_machine_standards (so no real target-map DB read) and
    let the REAL compute_beaming_daily run, proving the entry path derives every surface
    speed from rpm × dia × π/36 and persists the right snapshot columns:
      * std_speed / target_speed (snapshot) = SURFACE speeds from std/target RPM, NOT the
        raw RPMs that came out of resolve_machine_standards;
      * act_speed = act_rpm × dia × π/36 (act_rpm resolved from value_role='actual');
      * rpm_roller = the resolved act_rpm (NOT NULL once SQC has an actual RPM);
      * dia_roller = the resolved dia standard (Q7);
      * p100prod is computed from the STD SURFACE speed (NOT the raw std rpm).
    """

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _payload(self):
        return {
            "co_id": 1,
            "tran_date": "2026-06-21",
            "spell_id": 1,
            "machine_id": 7,
            "item_id": 10,
            "bm_quality_id": 5,
            "beam_no": "BEAM-007",
            "act_cuts": 4,
            "no_of_beam": 2,
        }

    @patch("src.juteProduction.beaming_entry.resolve_machine_standards")
    def test_act_speed_and_snapshot_from_rpm_and_dia(self, mock_resolve):
        """resolve_machine_standards hands back RPMs (std=100, target=110, act_rpm=30) +
        dia=12; the REAL compute converts each to a surface speed (rpm×dia×π/36) and the
        snapshot persists those surface speeds, rpm_roller=act_rpm, dia_roller=dia."""
        # std_speed / target_speed are RPMs here (LOCKED CONTRACT); act_rpm = actual RPM
        # resolved from value_role='actual' (Beaming SQC). dia is the machine standard (Q7).
        mock_resolve.return_value = {
            "laid_length": 1200.0, "cuts_per_beam": 50.0,
            "std_speed": 100.0, "target_speed": 110.0, "act_rpm": 30.0,
            "std_eff": 85.0, "target_eff": 90.0, "dia": 12.0,
        }

        # Execute order (simple quality, branch omitted): _fetch_quality, _spell_working_hours,
        # _idle_hours, _derive_branch_id, active-row lookup (None), insert.
        q_exec = MagicMock(); q_exec.fetchone.return_value = _quality_row(
            item_id=10, is_composite=0, ends=272, std_count=13.0
        )
        wh_exec = MagicMock()
        wh_row = MagicMock(); wh_row.working_hours = 8.0
        wh_exec.fetchone.return_value = wh_row
        idle_exec = MagicMock()
        idle_row = MagicMock(); idle_row.idle_hours = 0.0
        idle_exec.fetchone.return_value = idle_row
        branch_exec = MagicMock()
        branch_row = MagicMock(); branch_row.branch_id = 2
        branch_exec.fetchone.return_value = branch_row
        active_exec = MagicMock(); active_exec.fetchone.return_value = None
        insert_exec = MagicMock(); insert_exec.lastrowid = 700
        self._mock_session.execute.side_effect = [
            q_exec, wh_exec, idle_exec, branch_exec, active_exec, insert_exec,
        ]

        response = client.post("/api/beamingProd/entry_create", json=self._payload())

        assert response.status_code == 200
        computed = response.json()["data"]["computed"]
        # SURFACE speeds = rpm × dia × π / 36 (real compute, not mocked).
        assert computed["std_speed"] == 104.72     # 100 × 12 × π/36
        assert computed["target_speed"] == 115.192  # 110 × 12 × π/36
        assert computed["act_speed"] == 31.416      # 30 (act_rpm) × 12 × π/36
        # p100prod uses the STD SURFACE speed (104.72), NOT the raw std rpm 100:
        #   round(104.72 × 8 × 60) = 50266  (raw-rpm would have been 48000).
        assert computed["p100prod"] == 50266.0

        # The persisted snapshot carries the SURFACE speeds + rpm_roller=act_rpm, dia_roller=dia.
        insert_params = self._mock_session.execute.call_args_list[5].args[1]
        assert insert_params["std_speed"] == 104.72
        assert insert_params["target_speed"] == 115.192
        assert insert_params["act_speed"] == 31.416
        assert insert_params["rpm_roller"] == 30.0   # resolved act_rpm (NOT NULL — SQC value)
        assert insert_params["dia_roller"] == 12.0    # resolved machine standard (Q7)

    @patch("src.juteProduction.beaming_entry.resolve_machine_standards")
    def test_act_speed_zero_when_no_actual_rpm(self, mock_resolve):
        """SQC seam: with no value_role='actual' row (act_rpm=0), act_speed = 0 and
        rpm_roller binds NULL — std/target surface speeds still derive from their RPMs."""
        mock_resolve.return_value = {
            "laid_length": 1200.0, "cuts_per_beam": 50.0,
            "std_speed": 100.0, "target_speed": 110.0, "act_rpm": 0.0,
            "std_eff": 85.0, "target_eff": 90.0, "dia": 12.0,
        }
        q_exec = MagicMock(); q_exec.fetchone.return_value = _quality_row(
            item_id=10, is_composite=0, ends=272, std_count=13.0
        )
        wh_exec = MagicMock()
        wh_row = MagicMock(); wh_row.working_hours = 8.0
        wh_exec.fetchone.return_value = wh_row
        idle_exec = MagicMock()
        idle_row = MagicMock(); idle_row.idle_hours = 0.0
        idle_exec.fetchone.return_value = idle_row
        branch_exec = MagicMock()
        branch_row = MagicMock(); branch_row.branch_id = 2
        branch_exec.fetchone.return_value = branch_row
        active_exec = MagicMock(); active_exec.fetchone.return_value = None
        insert_exec = MagicMock(); insert_exec.lastrowid = 701
        self._mock_session.execute.side_effect = [
            q_exec, wh_exec, idle_exec, branch_exec, active_exec, insert_exec,
        ]

        response = client.post("/api/beamingProd/entry_create", json=self._payload())

        assert response.status_code == 200
        computed = response.json()["data"]["computed"]
        assert computed["act_speed"] == 0.0          # no actual RPM -> 0 surface speed
        assert computed["std_speed"] == 104.72        # std surface still derives from rpm
        insert_params = self._mock_session.execute.call_args_list[5].args[1]
        assert insert_params["rpm_roller"] is None    # NULL until SQC enters an actual RPM
        assert insert_params["act_speed"] == 0.0
        assert insert_params["dia_roller"] == 12.0


class TestMachineStandardsEndpoint:
    """GET /api/beamingProd/machine_standards (prefill resolver, qid+mcid)."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    @patch("src.juteProduction.beaming_entry.resolve_machine_standards")
    def test_passes_bm_quality_id_and_aliases_std_cuts(self, mock_resolve):
        """The endpoint forwards bm_quality_id to the resolver and aliases
        std_cuts_per_beam = cuts_per_beam (now QID-resolved) for the FE act-cuts
        default. Signature: resolve_machine_standards(db, co_id, machine_id,
        bm_quality_id, tran_date)."""
        mock_resolve.return_value = {
            "laid_length": 1200.0, "cuts_per_beam": 50.0, "std_speed": 100.0,
            "target_speed": 110.0, "act_rpm": 0.0, "std_eff": 85.0,
            "target_eff": 90.0, "dia": 12.0,
        }

        response = client.get(
            "/api/beamingProd/machine_standards"
            "?co_id=1&machine_id=7&bm_quality_id=5&tran_date=2026-06-21"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        # std_cuts_per_beam is the alias of cuts_per_beam (now resolved from the qid ref).
        assert data["std_cuts_per_beam"] == 50.0
        assert data["cuts_per_beam"] == 50.0
        # resolver received machine_id=7 and bm_quality_id=5 in the new arg order.
        resolve_args = mock_resolve.call_args.args
        assert resolve_args[2] == 7  # machine_id
        assert resolve_args[3] == 5  # bm_quality_id

    @patch("src.juteProduction.beaming_entry.resolve_machine_standards")
    def test_machine_id_optional_for_quality_only_prefill(self, mock_resolve):
        """machine_id may be omitted (0/None) when only the QID-resolved std cuts/beam is
        needed — int parsing is guarded, no 400, and the resolver gets machine_id=0."""
        mock_resolve.return_value = {
            "laid_length": 1200.0, "cuts_per_beam": 50.0, "std_speed": 0.0,
            "target_speed": 0.0, "act_rpm": 0.0, "std_eff": 85.0,
            "target_eff": 90.0, "dia": 0.0,
        }

        response = client.get(
            "/api/beamingProd/machine_standards"
            "?co_id=1&bm_quality_id=5&tran_date=2026-06-21"
        )

        assert response.status_code == 200
        assert response.json()["data"]["std_cuts_per_beam"] == 50.0
        resolve_args = mock_resolve.call_args.args
        assert resolve_args[2] == 0  # machine_id defaulted to 0 (guarded parse)
        assert resolve_args[3] == 5  # bm_quality_id


class TestPlanningGridSave:
    """POST /api/beamingProd/planning_grid_save (server-authoritative batch upsert)."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _row(self, **overrides):
        """A planning-grid row carrying FABRICATED computed columns the server must
        overwrite (kg/eff numbers that compute_beaming_daily will NOT produce)."""
        row = {
            "spell_id": 1,
            "machine_id": 7,
            "item_id": 10,
            "bm_quality_id": 5,
            "eb_id": 3,
            "act_cuts": 4,
            "no_of_beam": 2,
            # rpm_roller/dia_roller kept on the payload only to prove they are DISCARDED:
            # rpm comes from the future Beaming SQC page (SQC seam) and dia from the machine
            # standard (Q7) — neither is a production input.
            "rpm_roller": 30.0,
            "dia_roller": 12.0,
            # --- client-fabricated resolved/computed fields (must be discarded) ---
            "ends": 999,
            "std_count": 99.0,
            "act_count": 99.0,
            "laid_length": 9999.0,
            "std_cuts_per_beam": 999.0,
            "std_speed": 999.0,
            "target_speed": 999.0,
            "act_speed": 999.0,
            "std_eff": 999.0,
            "target_eff": 999.0,
            "working_hours": 999.0,
            "yards_per_beam": 999999.0,
            "kg_per_cut": 999.0,
            "kg_per_beam": 999.0,
            "p100prod": 999999.0,
            "std_prod": 999999.0,
            "target_prod": 999999.0,
            "act_prod_kg": 99999.0,
            "act_prod_yards": 99999.0,
            "act_eff": 777.0,
        }
        row.update(overrides)
        return row

    def _payload(self, rows):
        return {"co_id": 1, "tran_date": "2026-06-21", "rows": rows}

    def test_composite_quality_in_batch_returns_400(self):
        """A row whose quality has is_composite=1 must 400 (the §C.5 guard cannot be
        bypassed by client-sent fields) and the whole batch rolls back, nothing saved."""
        # _fetch_quality is the only execute reached before the composite guard fires.
        comp_exec = MagicMock()
        comp_exec.fetchone.return_value = _quality_row(item_id=10, is_composite=1)
        self._mock_session.execute.return_value = comp_exec

        response = client.post(
            "/api/beamingProd/planning_grid_save",
            json=self._payload([self._row()]),
        )

        assert response.status_code == 400
        assert "composite" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()
        self._mock_session.rollback.assert_called_once()

    @patch("src.juteProduction.beaming_entry.compute_beaming_daily")
    @patch("src.juteProduction.beaming_entry.resolve_machine_standards")
    def test_client_computed_fields_are_overwritten_by_server(self, mock_resolve, mock_compute):
        """Client-sent act_eff/kg/etc are DISCARDED; the persisted + returned snapshot
        carries the values produced by the SERVER compute, not the client payload."""
        mock_resolve.return_value = {
            "laid_length": 1200.0, "cuts_per_beam": 50.0, "std_speed": 100.0,
            "target_speed": 110.0, "std_eff": 85.0, "target_eff": 90.0, "dia": 12.0,
        }
        server_computed = {
            "act_speed": 31.4, "yards_per_beam": 60000.0, "kg_per_cut": 1.5,
            "kg_per_beam": 75.0, "p100prod": 48000.0, "std_prod": 40800.0,
            "target_prod": 43200.0, "act_prod_yards": 9600.0, "act_prod_kg": 12.0,
            "act_eff": 20.0,
        }
        mock_compute.return_value = server_computed

        # Execute order per row (simple quality, branch omitted in payload):
        #   1. _fetch_quality          -> fetchone quality row (is_composite=0)
        #   2. _spell_working_hours    -> fetchone working_hours row (gross, Q8)
        #   3. _idle_hours             -> fetchone idle_hours row (Q8)
        #   4. _derive_branch_id       -> fetchone branch row
        #   5. get_beaming_daily_active_row_query -> fetchone None (no existing)
        #   6. insert_beaming_daily_query -> insert
        q_exec = MagicMock(); q_exec.fetchone.return_value = _quality_row(
            item_id=10, is_composite=0, ends=272, std_count=13.0
        )
        wh_exec = MagicMock()
        wh_row = MagicMock(); wh_row.working_hours = 8.0
        wh_exec.fetchone.return_value = wh_row
        idle_exec = MagicMock()
        idle_row = MagicMock(); idle_row.idle_hours = 0.0
        idle_exec.fetchone.return_value = idle_row
        branch_exec = MagicMock()
        branch_row = MagicMock(); branch_row.branch_id = 2
        branch_exec.fetchone.return_value = branch_row
        active_exec = MagicMock(); active_exec.fetchone.return_value = None
        insert_exec = MagicMock()
        self._mock_session.execute.side_effect = [
            q_exec, wh_exec, idle_exec, branch_exec, active_exec, insert_exec,
        ]

        response = client.post(
            "/api/beamingProd/planning_grid_save",
            json=self._payload([self._row()]),
        )

        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 1
        self._mock_session.commit.assert_called_once()

        # compute_beaming_daily received the GENUINE inputs only — NOT the client-sent
        # dia_roller (now a server-resolved standard, Q7) and NOT rpm_roller (the ACTUAL
        # roller speed comes from the future Beaming SQC page, not production entry — SQC
        # seam). The resolved standards came from the server resolver — including dia and the
        # net working_hours (Q7/Q8).
        inputs_arg, standards_arg = mock_compute.call_args.args
        assert inputs_arg == {
            "act_cuts": 4, "no_of_beam": 2,
        }
        assert "dia_roller" not in inputs_arg        # dia is a standard now, not an input
        assert "rpm_roller" not in inputs_arg        # rpm comes from SQC, not production entry
        assert standards_arg["ends"] == 272.0          # from quality, not client 999
        assert standards_arg["std_count"] == 13.0      # from quality, not client 99
        assert standards_arg["laid_length"] == 1200.0  # from resolver, not client 9999
        assert standards_arg["std_eff"] == 85.0        # from resolver, not client 999
        assert standards_arg["dia"] == 12.0            # dia resolved from machine standard
        assert standards_arg["working_hours"] == 8.0   # net = gross 8 - idle 0 (Q8)
        # The resolver was called with the row's bm_quality_id (qid ref) so the quality-
        # linked laid_length/cuts_per_beam/eff resolve off the Beaming Quality Master.
        resolve_args = mock_resolve.call_args.args
        assert resolve_args[3] == 5  # bm_quality_id from the planning row

        # The INSERT bind params carry the SERVER-computed snapshot, NOT the client payload.
        insert_call = self._mock_session.execute.call_args_list[5]
        params = insert_call.args[1]
        assert params["act_eff"] == 20.0          # server compute, not client 777
        assert params["act_prod_kg"] == 12.0      # server compute, not client 99999
        assert params["kg_per_cut"] == 1.5        # server compute, not client 999
        assert params["p100prod"] == 48000.0      # server compute, not client 999999
        assert params["ends"] == 272              # server quality, not client 999
        assert params["std_eff"] == 85.0          # server resolver, not client 999
        assert params["dia_roller"] == 12.0       # resolved standard, not client 12 input
        assert params["rpm_roller"] is None       # client 30.0 discarded — set later by SQC
        # genuine client inputs are preserved
        assert params["act_cuts"] == 4
        assert params["no_of_beam"] == 2
        assert params["eb_id"] == 3
