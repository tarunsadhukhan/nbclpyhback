"""Tests for src/sales/enquiry_hooks.py (AMCL enquiry flow, Phase 1) and the
quotation / sales-order touch-points that call those hooks.

Layout:
- validate_transition: pure unit tests (no HTTP, no DB) covering the design §4
  rule matrix — the full ALLOWED_FORWARD map, the Q4 approval gate out of
  ENQ_NOTED, SEND_BACK (mandatory feedback + earlier-stage only), HOLD/RESUME
  stage preservation, MARK_LOST sequence ceiling, CLOSE, AUTO (never backward),
  CREATE, and terminal-stage lockout.
- advance_enquiry_on_sales_order_approved: mocked-session tests — resolution
  via sales_order.sales_enquiry_id (direct/tender path) vs. the quotation
  fallback, idempotency when the enquiry is already at/past ORDER_CONFIRMED,
  and the no-write guarantees (caller owns the transaction; hook never commits).
- Quotation touch-points (src/sales/quotation.py): create_quotation persists
  sales_enquiry_id + per-line enquiry_dtl_id / cost_snapshot_id / base_cost /
  overhead_pct / margin_pct; approve_quotation calls
  advance_enquiry_on_quotation_approved (patched) on final approval only.
- Sales-order touch-points (src/sales/salesOrder.py): create_sales_order
  persists committed_delivery_date / advance_amount / advance_note /
  sales_enquiry_id; approve_sales_order calls
  advance_enquiry_on_sales_order_approved (patched) on final approval and
  auto-creates a project (decision Q5) when the advanced enquiry has
  project_id NULL.

DB and auth are always mocked (dependency_overrides on the main app for the
router tests, MagicMock sessions dispatching on SQL substrings for the hook
tests) — no real database is ever touched.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.main import app
from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.sales.enquiry_constants import (
    ACTION_AUTO,
    ACTION_CLOSE,
    ACTION_CREATE,
    ACTION_FORWARD,
    ACTION_HOLD,
    ACTION_MARK_LOST,
    ACTION_RESUME,
    ACTION_SEND_BACK,
    ALLOWED_FORWARD,
    ENQUIRY_FLOW_DOC_TYPE,
    ENQUIRY_STAGE_CODES,
    ENQUIRY_STATUS_IDS,
    LINKED_DOC_SALES_ORDER,
    MARK_LOST_MAX_SEQUENCE,
    STAGE_CLOSED,
    STAGE_COSTING_REVIEW,
    STAGE_DESIGN_RELEASE,
    STAGE_ENQ_NOTED,
    STAGE_LOST,
    STAGE_ORDER_CONFIRMED,
    STAGE_PRICE_CHECK,
    STAGE_PRODUCTION,
    STAGE_QUOTATION,
    STAGE_SEQUENCE,
    TERMINAL_STAGES,
)
from src.sales.enquiry_hooks import (
    advance_enquiry_on_sales_order_approved,
    validate_transition,
)

client = TestClient(app)

STATUS_APPROVED = ENQUIRY_STATUS_IDS["APPROVED"]
STATUS_OPEN = ENQUIRY_STATUS_IDS["OPEN"]

# Deterministic flow_stage_mst.stage_id per stage code for the mocked sessions.
STAGE_IDS = {code: 100 + i for i, code in enumerate(ENQUIRY_STAGE_CODES, start=1)}

NON_TERMINAL_STAGES = tuple(c for c in ENQUIRY_STAGE_CODES if c not in TERMINAL_STAGES)


# =============================================================================
# MOCK HELPERS (same dispatch style as test_sales_enquiry.py)
# =============================================================================

def _row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _result(fetchall=None, fetchone=None, lastrowid=0):
    """A MagicMock standing in for a SQLAlchemy CursorResult."""
    result = MagicMock()
    result.fetchall.return_value = fetchall if fetchall is not None else []
    result.fetchone.return_value = fetchone
    result.lastrowid = lastrowid
    return result


def _stage_lookup_result(params: dict):
    """flow_stage_mst row for the get_stage_by_code_query bind params."""
    stage_code = params["stage_code"]
    if stage_code not in STAGE_IDS:
        return _result(fetchone=None)
    return _result(fetchone=_row({
        "stage_id": STAGE_IDS[stage_code],
        "stage_code": stage_code,
        "stage_name": stage_code.replace("_", " ").title(),
        "dept_hint": None,
        "sequence_no": STAGE_SEQUENCE[stage_code],
        "is_terminal": 1 if stage_code in TERMINAL_STAGES else 0,
    }))


def make_session(handlers=()):
    """MagicMock session whose execute() dispatches on SQL substrings.

    handlers: ordered iterable of (sql_marker, result_or_callable). The first
    marker found in str(query) wins; a callable receives the bind params and
    returns the result. Unmatched SQL gets an empty result so incidental
    queries never crash a test.
    """
    session = MagicMock()

    def _execute(query, params=None):
        sql = str(query)
        for marker, result in handlers:
            if marker in sql:
                if isinstance(result, MagicMock):
                    return result
                if callable(result):
                    return result(params or {})
                return result
        return _result()

    session.execute.side_effect = _execute
    return session


def _calls_for(session, marker):
    """(sql, params) of every execute() call whose SQL contains marker."""
    out = []
    for call in session.execute.call_args_list:
        sql = str(call.args[0])
        if marker in sql:
            params = call.args[1] if len(call.args) > 1 else call.kwargs.get("params")
            out.append((sql, params))
    return out


# SQL markers — distinctive substrings of the statements the SO hook runs.
M_SO_LINK = "quotation_sales_enquiry_id"                     # get_sales_order_enquiry_link_query
M_FLOW_STATE = "se.stage_since,"                             # get_enquiry_flow_state_query
M_STAGE_BY_CODE = "fsm.stage_code = :stage_code"             # get_stage_by_code_query
M_INSERT_LOG = "INSERT INTO flow_stage_log"                  # insert_flow_stage_log
M_UPDATE_STAGE_PTR = "current_stage_id = :current_stage_id"  # update_enquiry_current_stage

H_STAGE_BY_CODE = (M_STAGE_BY_CODE, _stage_lookup_result)


def _flow_state(**overrides):
    """A get_enquiry_flow_state_query row mapping (opened-enquiry defaults)."""
    stage_code = overrides.pop("stage_code", STAGE_QUOTATION)
    state = {
        "sales_enquiry_id": 5,
        "enquiry_no": "42",
        "enquiry_date": date(2026, 6, 1),
        "branch_id": 4,
        "co_id": 1,
        "party_id": 9,
        "status_id": STATUS_APPROVED,
        "approval_level": None,
        "current_stage_id": STAGE_IDS[stage_code] if stage_code else None,
        "stage_code": stage_code,
        "sequence_no": STAGE_SEQUENCE[stage_code] if stage_code else None,
        "is_terminal": 1 if stage_code in TERMINAL_STAGES else 0,
        "stage_since": date(2026, 6, 1),
        "hold_flag": 0,
        "close_reason": None,
        "project_id": None,
        "active": 1,
    }
    state.update(overrides)
    return state


def _so_link(sales_order_id=11, sales_enquiry_id=5, quotation_sales_enquiry_id=None):
    return _row({
        "sales_order_id": sales_order_id,
        "sales_enquiry_id": sales_enquiry_id,
        "quotation_sales_enquiry_id": quotation_sales_enquiry_id,
    })


def _so_hook_session(link_row, state=None):
    """Session wired for one advance_enquiry_on_sales_order_approved run."""
    handlers = [
        (M_SO_LINK, _result(fetchone=link_row)),
        H_STAGE_BY_CODE,
    ]
    if state is not None:
        handlers.append((M_FLOW_STATE, _result(fetchone=_row(state))))
    return make_session(handlers)


# =============================================================================
# validate_transition — pure rule-matrix unit tests (no HTTP, no DB)
# =============================================================================

def _rejects(expected_status, current, action, to_stage, status_id=STATUS_APPROVED, feedback=None):
    """Assert validate_transition raises HTTPException(expected_status); return it."""
    with pytest.raises(HTTPException) as exc_info:
        validate_transition(current, action, to_stage, status_id, feedback)
    assert exc_info.value.status_code == expected_status, exc_info.value.detail
    return exc_info.value


class TestValidateTransitionActionsAndStages:
    """Action / stage-code plausibility checks."""

    def test_invalid_action_rejected(self):
        err = _rejects(400, STAGE_ENQ_NOTED, "TELEPORT", STAGE_QUOTATION)
        assert "Invalid action" in err.detail

    def test_unknown_target_stage_rejected(self):
        err = _rejects(400, STAGE_ENQ_NOTED, ACTION_FORWARD, "NOT_A_STAGE")
        assert "Unknown target stage" in err.detail

    def test_unknown_current_stage_rejected(self):
        err = _rejects(400, "NOT_A_STAGE", ACTION_FORWARD, STAGE_QUOTATION)
        assert "Unknown current stage" in err.detail

    def test_no_current_stage_rejected_for_non_create(self):
        err = _rejects(400, None, ACTION_FORWARD, STAGE_COSTING_REVIEW)
        assert "no current stage" in err.detail

    def test_terminal_stages_allow_no_transitions(self):
        for terminal in sorted(TERMINAL_STAGES):
            for action in (ACTION_FORWARD, ACTION_SEND_BACK, ACTION_HOLD,
                           ACTION_RESUME, ACTION_MARK_LOST, ACTION_CLOSE, ACTION_AUTO):
                err = _rejects(400, terminal, action, None, feedback="fb")
                assert "terminal" in err.detail


class TestValidateTransitionCreate:
    def test_create_valid_with_no_current_stage(self):
        assert validate_transition(None, ACTION_CREATE, None, ENQUIRY_STATUS_IDS["DRAFT"], None) is None
        assert validate_transition(None, ACTION_CREATE, STAGE_ENQ_NOTED, ENQUIRY_STATUS_IDS["OPEN"], None) is None

    def test_create_rejected_when_stage_already_set(self):
        _rejects(400, STAGE_ENQ_NOTED, ACTION_CREATE, STAGE_ENQ_NOTED)

    def test_create_must_target_enq_noted(self):
        err = _rejects(400, None, ACTION_CREATE, STAGE_COSTING_REVIEW)
        assert STAGE_ENQ_NOTED in err.detail


class TestValidateTransitionForward:
    def test_forward_requires_target(self):
        err = _rejects(400, STAGE_COSTING_REVIEW, ACTION_FORWARD, None)
        assert "to_stage is required" in err.detail

    def test_forward_full_matrix(self):
        """Every (current, target) pair: allowed per ALLOWED_FORWARD passes,
        everything else is a 400. Uses status 3 so the Q4 gate never interferes."""
        for current in NON_TERMINAL_STAGES:
            allowed = ALLOWED_FORWARD[current]
            for target in ENQUIRY_STAGE_CODES:
                if target in allowed:
                    assert validate_transition(
                        current, ACTION_FORWARD, target, STATUS_APPROVED, None
                    ) is None, f"{current} -> {target} should be legal"
                else:
                    err = _rejects(400, current, ACTION_FORWARD, target)
                    assert "Cannot FORWARD" in err.detail, f"{current} -> {target}"

    def test_price_check_is_skippable(self):
        """QUOTATION and ORDER_CONFIRMED reachable straight from COSTING_REVIEW."""
        assert validate_transition(STAGE_COSTING_REVIEW, ACTION_FORWARD,
                                   STAGE_QUOTATION, STATUS_APPROVED, None) is None
        assert validate_transition(STAGE_COSTING_REVIEW, ACTION_FORWARD,
                                   STAGE_ORDER_CONFIRMED, STATUS_APPROVED, None) is None

    def test_direct_order_path_from_price_check(self):
        """Tender path (decision Q3): PRICE_CHECK -> ORDER_CONFIRMED, no quotation."""
        assert validate_transition(STAGE_PRICE_CHECK, ACTION_FORWARD,
                                   STAGE_ORDER_CONFIRMED, STATUS_APPROVED, None) is None

    def test_forward_out_of_enq_noted_gated_on_approval(self):
        """Q4 gate: leaving ENQ_NOTED needs status 3 — everything else is 403."""
        for status_id in (v for k, v in ENQUIRY_STATUS_IDS.items() if k != "APPROVED"):
            err = _rejects(403, STAGE_ENQ_NOTED, ACTION_FORWARD,
                           STAGE_COSTING_REVIEW, status_id=status_id)
            assert "Approved" in err.detail
        assert validate_transition(STAGE_ENQ_NOTED, ACTION_FORWARD,
                                   STAGE_COSTING_REVIEW, STATUS_APPROVED, None) is None

    def test_approval_gate_applies_only_to_enq_noted(self):
        """Later FORWARDs are not re-gated on the enquiry status."""
        assert validate_transition(STAGE_COSTING_REVIEW, ACTION_FORWARD,
                                   STAGE_QUOTATION, STATUS_OPEN, None) is None


class TestValidateTransitionSendBack:
    def test_send_back_requires_feedback(self):
        for feedback in (None, "", "   "):
            err = _rejects(400, STAGE_COSTING_REVIEW, ACTION_SEND_BACK,
                           STAGE_ENQ_NOTED, feedback=feedback)
            assert "feedback is mandatory" in err.detail

    def test_send_back_requires_target(self):
        err = _rejects(400, STAGE_COSTING_REVIEW, ACTION_SEND_BACK, None, feedback="specs missing")
        assert "to_stage is required" in err.detail

    def test_send_back_to_earlier_stage_allowed(self):
        assert validate_transition(STAGE_COSTING_REVIEW, ACTION_SEND_BACK,
                                   STAGE_ENQ_NOTED, STATUS_APPROVED, "specs missing") is None
        # Not restricted to adjacent stages: QUOTATION all the way back to ENQ_NOTED.
        assert validate_transition(STAGE_QUOTATION, ACTION_SEND_BACK,
                                   STAGE_ENQ_NOTED, STATUS_APPROVED, "requote") is None

    def test_send_back_to_same_or_later_stage_rejected(self):
        _rejects(400, STAGE_COSTING_REVIEW, ACTION_SEND_BACK,
                 STAGE_COSTING_REVIEW, feedback="fb")
        _rejects(400, STAGE_COSTING_REVIEW, ACTION_SEND_BACK,
                 STAGE_QUOTATION, feedback="fb")


class TestValidateTransitionHoldResumeLostCloseAuto:
    def test_hold_and_resume_preserve_stage(self):
        for action in (ACTION_HOLD, ACTION_RESUME):
            assert validate_transition(STAGE_QUOTATION, action, None, STATUS_APPROVED, None) is None
            assert validate_transition(STAGE_QUOTATION, action, STAGE_QUOTATION,
                                       STATUS_APPROVED, None) is None
            err = _rejects(400, STAGE_QUOTATION, action, STAGE_COSTING_REVIEW)
            assert "does not change the stage" in err.detail

    def test_mark_lost_allowed_up_to_sequence_ceiling(self):
        for stage in NON_TERMINAL_STAGES:
            if STAGE_SEQUENCE[stage] <= MARK_LOST_MAX_SEQUENCE:
                assert validate_transition(stage, ACTION_MARK_LOST, None,
                                           STATUS_APPROVED, None) is None
                assert validate_transition(stage, ACTION_MARK_LOST, STAGE_LOST,
                                           STATUS_APPROVED, None) is None
            else:
                err = _rejects(400, stage, ACTION_MARK_LOST, None)
                assert "MARK_LOST" in err.detail

    def test_mark_lost_must_target_lost(self):
        err = _rejects(400, STAGE_QUOTATION, ACTION_MARK_LOST, STAGE_CLOSED)
        assert STAGE_LOST in err.detail

    def test_close_from_any_non_terminal_stage(self):
        for stage in NON_TERMINAL_STAGES:
            assert validate_transition(stage, ACTION_CLOSE, None, STATUS_APPROVED, None) is None
            assert validate_transition(stage, ACTION_CLOSE, STAGE_CLOSED,
                                       STATUS_APPROVED, None) is None

    def test_close_must_target_closed(self):
        err = _rejects(400, STAGE_QUOTATION, ACTION_CLOSE, STAGE_LOST)
        assert STAGE_CLOSED in err.detail

    def test_auto_requires_target_and_never_moves_backward(self):
        err = _rejects(400, STAGE_QUOTATION, ACTION_AUTO, None)
        assert "to_stage is required" in err.detail
        # Same stage (re-log, e.g. quotation approved) and forward are fine.
        assert validate_transition(STAGE_QUOTATION, ACTION_AUTO, STAGE_QUOTATION,
                                   STATUS_APPROVED, None) is None
        assert validate_transition(STAGE_QUOTATION, ACTION_AUTO, STAGE_ORDER_CONFIRMED,
                                   STATUS_APPROVED, None) is None
        err = _rejects(400, STAGE_QUOTATION, ACTION_AUTO, STAGE_COSTING_REVIEW)
        assert "cannot move to an earlier stage" in err.detail


# =============================================================================
# advance_enquiry_on_sales_order_approved — mocked-session unit tests
# =============================================================================

class TestAdvanceEnquiryOnSalesOrderApproved:

    def test_advances_via_own_enquiry_column(self):
        """Direct/tender path (Q3): sales_order.sales_enquiry_id set."""
        session = _so_hook_session(
            _so_link(sales_order_id=11, sales_enquiry_id=5),
            _flow_state(stage_code=STAGE_QUOTATION),
        )

        result = advance_enquiry_on_sales_order_approved(session, 11, user_id=3)

        assert result == 5
        inserts = _calls_for(session, M_INSERT_LOG)
        assert len(inserts) == 1
        params = inserts[0][1]
        assert params["doc_type"] == ENQUIRY_FLOW_DOC_TYPE
        assert params["doc_id"] == 5
        assert params["from_stage_id"] == STAGE_IDS[STAGE_QUOTATION]
        assert params["to_stage_id"] == STAGE_IDS[STAGE_ORDER_CONFIRMED]
        assert params["action"] == ACTION_AUTO
        assert params["linked_doc_type"] == LINKED_DOC_SALES_ORDER
        assert params["linked_doc_id"] == 11
        assert params["action_by"] == 3
        assert params["feedback"]  # the AUTO entry carries a note

        updates = _calls_for(session, M_UPDATE_STAGE_PTR)
        assert len(updates) == 1
        upd = updates[0][1]
        assert upd["sales_enquiry_id"] == 5
        assert upd["current_stage_id"] == STAGE_IDS[STAGE_ORDER_CONFIRMED]
        assert upd["updated_by"] == 3

    def test_advances_via_quotation_fallback(self):
        """No direct link — the enquiry is resolved via the SO's quotation."""
        session = _so_hook_session(
            _so_link(sales_order_id=12, sales_enquiry_id=None, quotation_sales_enquiry_id=7),
            _flow_state(sales_enquiry_id=7, stage_code=STAGE_COSTING_REVIEW),
        )

        result = advance_enquiry_on_sales_order_approved(session, 12, user_id=4)

        assert result == 7
        # The flow-state lookup must have targeted the fallback enquiry id.
        state_calls = _calls_for(session, M_FLOW_STATE)
        assert state_calls and state_calls[0][1]["sales_enquiry_id"] == 7
        inserts = _calls_for(session, M_INSERT_LOG)
        assert len(inserts) == 1
        assert inserts[0][1]["doc_id"] == 7
        assert inserts[0][1]["to_stage_id"] == STAGE_IDS[STAGE_ORDER_CONFIRMED]

    def test_own_column_wins_over_quotation_fallback(self):
        session = _so_hook_session(
            _so_link(sales_enquiry_id=5, quotation_sales_enquiry_id=7),
            _flow_state(sales_enquiry_id=5, stage_code=STAGE_QUOTATION),
        )

        result = advance_enquiry_on_sales_order_approved(session, 11, user_id=1)

        assert result == 5
        assert _calls_for(session, M_FLOW_STATE)[0][1]["sales_enquiry_id"] == 5

    def test_idempotent_when_already_at_order_confirmed(self):
        """Second approval (or re-run) must not double-advance or re-log."""
        session = _so_hook_session(
            _so_link(sales_enquiry_id=5),
            _flow_state(stage_code=STAGE_ORDER_CONFIRMED),
        )

        result = advance_enquiry_on_sales_order_approved(session, 11, user_id=1)

        assert result is None
        assert _calls_for(session, M_INSERT_LOG) == []
        assert _calls_for(session, M_UPDATE_STAGE_PTR) == []

    def test_idempotent_when_past_order_confirmed(self):
        for stage in (STAGE_DESIGN_RELEASE, STAGE_PRODUCTION, STAGE_CLOSED, STAGE_LOST):
            session = _so_hook_session(
                _so_link(sales_enquiry_id=5),
                _flow_state(stage_code=stage),
            )
            result = advance_enquiry_on_sales_order_approved(session, 11, user_id=1)
            assert result is None, f"expected no-op at stage {stage}"
            assert _calls_for(session, M_INSERT_LOG) == []
            assert _calls_for(session, M_UPDATE_STAGE_PTR) == []

    def test_noop_when_sales_order_not_found(self):
        session = _so_hook_session(link_row=None)
        assert advance_enquiry_on_sales_order_approved(session, 999, user_id=1) is None
        assert _calls_for(session, M_FLOW_STATE) == []

    def test_noop_when_no_enquiry_linked(self):
        session = _so_hook_session(
            _so_link(sales_enquiry_id=None, quotation_sales_enquiry_id=None)
        )
        assert advance_enquiry_on_sales_order_approved(session, 11, user_id=1) is None
        assert _calls_for(session, M_FLOW_STATE) == []
        assert _calls_for(session, M_INSERT_LOG) == []

    def test_noop_when_enquiry_not_opened_yet(self):
        """Linked enquiry with no current stage: skip, don't crash."""
        session = _so_hook_session(
            _so_link(sales_enquiry_id=5),
            _flow_state(stage_code=None),
        )
        assert advance_enquiry_on_sales_order_approved(session, 11, user_id=1) is None
        assert _calls_for(session, M_INSERT_LOG) == []

    def test_missing_enquiry_row_raises_404(self):
        session = make_session([
            (M_SO_LINK, _result(fetchone=_so_link(sales_enquiry_id=5))),
            (M_FLOW_STATE, _result(fetchone=None)),
            H_STAGE_BY_CODE,
        ])
        with pytest.raises(HTTPException) as exc_info:
            advance_enquiry_on_sales_order_approved(session, 11, user_id=1)
        assert exc_info.value.status_code == 404

    def test_hook_never_commits(self):
        """Design §4: hooks run inside the caller's transaction — caller commits."""
        session = _so_hook_session(
            _so_link(sales_enquiry_id=5),
            _flow_state(stage_code=STAGE_QUOTATION),
        )
        advance_enquiry_on_sales_order_approved(session, 11, user_id=1)
        session.commit.assert_not_called()
        session.rollback.assert_not_called()
