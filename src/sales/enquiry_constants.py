"""
Enquiry-module constants — single source of truth for the AMCL enquiry flow
(docs/amcl-enquiry-flow-design.md §4 stage model, §5.1 value sets).

Covers: status IDs, flow stage codes + sequence map, the server-enforced
transition rules (allowed-forward map, actions, MARK_LOST ceiling, the
ENQ_NOTED approval gate), linked-document types, received-via options, and
the enquiry_price_check value sets.

Everything here is immutable (tuples / frozensets / MappingProxyType) —
handlers run concurrently in FastAPI's threadpool, so shared module state
must never be mutable (CLAUDE.md "Sync Handler Policy").
"""

from types import MappingProxyType

# =============================================================================
# ENQUIRY STATUS DEFINITIONS (standard approval lifecycle — decision Q4)
# 21 Draft -> 1 Open -> 20 Pending Approval -> 3 Approved / 4 Rejected;
# 21 -> 6 cancel-draft; reopen 4 -> 1, 6 -> 21; 5 Closed at the end.
# =============================================================================

ENQUIRY_STATUS_IDS = MappingProxyType({
    "DRAFT": 21,
    "OPEN": 1,
    "PENDING_APPROVAL": 20,
    "APPROVED": 3,
    "REJECTED": 4,
    "CLOSED": 5,
    "CANCELLED": 6,
})

ENQUIRY_STATUS_LABELS = MappingProxyType({
    21: "Draft",
    1: "Open",
    20: "Pending Approval",
    3: "Approved",
    4: "Rejected",
    5: "Closed",
    6: "Cancelled",
})

# =============================================================================
# FLOW MODULE / DOC TYPE (flow_stage_mst.module, flow_stage_log.doc_type)
# =============================================================================

FLOW_MODULE_ENQUIRY = "ENQUIRY"          # flow_stage_mst.module seed value
ENQUIRY_FLOW_DOC_TYPE = "SALES_ENQUIRY"  # flow_stage_log.doc_type (only Phase-1 value)

# =============================================================================
# STAGE CODES (flow_stage_mst.stage_code, module='ENQUIRY' — design §4)
# =============================================================================

STAGE_ENQ_NOTED = "ENQ_NOTED"
STAGE_COSTING_REVIEW = "COSTING_REVIEW"
STAGE_PRICE_CHECK = "PRICE_CHECK"
STAGE_QUOTATION = "QUOTATION"
STAGE_ORDER_CONFIRMED = "ORDER_CONFIRMED"
STAGE_DESIGN_RELEASE = "DESIGN_RELEASE"
STAGE_PRODUCTION_PLANNING = "PRODUCTION_PLANNING"
STAGE_PROCUREMENT = "PROCUREMENT"
STAGE_MATERIAL_READY = "MATERIAL_READY"
STAGE_PRODUCTION = "PRODUCTION"
STAGE_FG_HANDOVER = "FG_HANDOVER"
STAGE_READY_FOR_DELIVERY = "READY_FOR_DELIVERY"
STAGE_CLOSED = "CLOSED"
STAGE_LOST = "LOST"

ENQUIRY_STAGE_CODES = (
    STAGE_ENQ_NOTED,
    STAGE_COSTING_REVIEW,
    STAGE_PRICE_CHECK,
    STAGE_QUOTATION,
    STAGE_ORDER_CONFIRMED,
    STAGE_DESIGN_RELEASE,
    STAGE_PRODUCTION_PLANNING,
    STAGE_PROCUREMENT,
    STAGE_MATERIAL_READY,
    STAGE_PRODUCTION,
    STAGE_FG_HANDOVER,
    STAGE_READY_FOR_DELIVERY,
    STAGE_CLOSED,
    STAGE_LOST,
)

# Sequence numbers — MUST match the flow_stage_mst seed
# (dbqueries/migrations/create_amcl_enquiry_flow_phase1.sql §8): gaps of 10,
# LOST = 999 (out-of-band terminal, reachable from any stage with seq <= 50).
STAGE_SEQUENCE = MappingProxyType({
    STAGE_ENQ_NOTED: 10,
    STAGE_COSTING_REVIEW: 20,
    STAGE_PRICE_CHECK: 30,
    STAGE_QUOTATION: 40,
    STAGE_ORDER_CONFIRMED: 50,
    STAGE_DESIGN_RELEASE: 60,
    STAGE_PRODUCTION_PLANNING: 70,
    STAGE_PROCUREMENT: 80,
    STAGE_MATERIAL_READY: 90,
    STAGE_PRODUCTION: 100,
    STAGE_FG_HANDOVER: 110,
    STAGE_READY_FOR_DELIVERY: 120,
    STAGE_CLOSED: 130,
    STAGE_LOST: 999,
})

# Terminal stages — no transitions out of these (is_terminal = 1 in the seed).
TERMINAL_STAGES = frozenset({STAGE_CLOSED, STAGE_LOST})

# =============================================================================
# ALLOWED FORWARD TRANSITIONS (design §4)
# - PRICE_CHECK is optional/skippable: QUOTATION and ORDER_CONFIRMED are
#   reachable from both COSTING_REVIEW and PRICE_CHECK.
# - ORDER_CONFIRMED directly from COSTING_REVIEW / PRICE_CHECK = the
#   direct-order path (customer PO / tender, no quotation — decision Q3).
# - PRICE_CHECK -> COSTING_REVIEW is the respond-price-check return leg.
# - After ORDER_CONFIRMED the chain is linear through CLOSED.
# =============================================================================

ALLOWED_FORWARD = MappingProxyType({
    STAGE_ENQ_NOTED: (STAGE_COSTING_REVIEW,),
    STAGE_COSTING_REVIEW: (STAGE_PRICE_CHECK, STAGE_QUOTATION, STAGE_ORDER_CONFIRMED),
    STAGE_PRICE_CHECK: (STAGE_COSTING_REVIEW, STAGE_QUOTATION, STAGE_ORDER_CONFIRMED),
    STAGE_QUOTATION: (STAGE_ORDER_CONFIRMED,),
    STAGE_ORDER_CONFIRMED: (STAGE_DESIGN_RELEASE,),
    STAGE_DESIGN_RELEASE: (STAGE_PRODUCTION_PLANNING,),
    STAGE_PRODUCTION_PLANNING: (STAGE_PROCUREMENT,),
    STAGE_PROCUREMENT: (STAGE_MATERIAL_READY,),
    STAGE_MATERIAL_READY: (STAGE_PRODUCTION,),
    STAGE_PRODUCTION: (STAGE_FG_HANDOVER,),
    STAGE_FG_HANDOVER: (STAGE_READY_FOR_DELIVERY,),
    STAGE_READY_FOR_DELIVERY: (STAGE_CLOSED,),
    STAGE_CLOSED: (),
    STAGE_LOST: (),
})

# =============================================================================
# TRANSITION ACTIONS (flow_stage_log.action — design §5.1; value set enforced
# in code, no DB CHECK, so Phase 2 can extend without DDL)
# =============================================================================

ACTION_CREATE = "CREATE"        # written by open_enquiry (from_stage NULL -> ENQ_NOTED)
ACTION_FORWARD = "FORWARD"      # to a stage in ALLOWED_FORWARD[current]
ACTION_SEND_BACK = "SEND_BACK"  # to any strictly earlier stage; feedback mandatory
ACTION_HOLD = "HOLD"            # freezes the stage (hold_flag = 1); stage unchanged
ACTION_RESUME = "RESUME"        # unfreezes (hold_flag = 0); stage unchanged
ACTION_MARK_LOST = "MARK_LOST"  # terminal before order confirmation (seq <= 50)
ACTION_CLOSE = "CLOSE"          # terminal at the end of the chain
ACTION_AUTO = "AUTO"            # system transition (linked-document approval hooks)

ENQUIRY_ACTIONS = frozenset({
    ACTION_CREATE,
    ACTION_FORWARD,
    ACTION_SEND_BACK,
    ACTION_HOLD,
    ACTION_RESUME,
    ACTION_MARK_LOST,
    ACTION_CLOSE,
    ACTION_AUTO,
})

# MARK_LOST is allowed only from stages with sequence <= 50 (i.e. up to and
# including ORDER_CONFIRMED — "terminal before order confirmation", design §4).
MARK_LOST_MAX_SEQUENCE = 50

# Approval gate (decision Q4): FORWARD out of ENQ_NOTED into COSTING_REVIEW
# requires the enquiry itself to be Approved (status 3).
FORWARD_GATE_STATUS_ID = ENQUIRY_STATUS_IDS["APPROVED"]

# =============================================================================
# CANONICAL MENU (approval permission checks)
# The approval hierarchy for enquiries lives on the Customer Enquiry menu.
# Entry points carry their own menu_id (Enquiry Flow Board = a separate menu,
# BOM costing review links in with its menu, direct URLs carry none) — the
# client's menu_id must never decide which menu's approval config applies.
# Resolve the canonical menu server-side via menu_mst.menu_path.
# =============================================================================

ENQUIRY_MENU_PATH = "sales/enquiry"

# =============================================================================
# LINKED DOCUMENT TYPES (flow_stage_log.linked_doc_type — design §5.1)
# =============================================================================

LINKED_DOC_QUOTATION = "QUOTATION"
LINKED_DOC_SALES_ORDER = "SALES_ORDER"
LINKED_DOC_PRICE_CHECK = "PRICE_CHECK"

LINKED_DOC_TYPES = (
    # Phase 1
    LINKED_DOC_QUOTATION,
    LINKED_DOC_SALES_ORDER,
    LINKED_DOC_PRICE_CHECK,
    # Phase 2 (reserved — written by the execution-leg hooks, design §8)
    "WORK_ORDER",
    "INDENT",
    "PO",
    "MATERIAL_REQUEST",
    "ISSUE",
    "FG_RECEIPT",
    "DELIVERY_ORDER",
    "INVOICE",
)

LINKED_DOC_TYPE_SET = frozenset(LINKED_DOC_TYPES)

# =============================================================================
# HEADER FIELD VALUE SETS (mirror the DB CHECK constraints in the migration)
# =============================================================================

# sales_enquiry.received_via
RECEIVED_VIA_OPTIONS = ("email", "phone", "visit", "tender", "other")

# sales_enquiry.close_reason
CLOSE_REASONS = ("won", "lost", "cancelled")

# =============================================================================
# PRICE CHECK VALUE SETS (enquiry_price_check / enquiry_price_check_dtl)
# =============================================================================

# enquiry_price_check.pc_status
PC_STATUS_PENDING = "pending"
PC_STATUS_RESPONDED = "responded"
PC_STATUS_CANCELLED = "cancelled"
PRICE_CHECK_STATUSES = (PC_STATUS_PENDING, PC_STATUS_RESPONDED, PC_STATUS_CANCELLED)

# enquiry_price_check_dtl.rate_source
RATE_SOURCES = ("last_po", "supplier_quote", "estimate")
