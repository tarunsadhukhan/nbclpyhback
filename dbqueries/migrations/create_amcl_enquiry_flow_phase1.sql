-- =============================================================================
-- Migration: AMCL Enquiry-to-Delivery Flow — Phase 1 schema
-- =============================================================================
-- Date: 2026-07-06
-- Spec: docs/amcl-enquiry-flow-design.md §5.1 (new tables), §5.2 (alterations),
--       §4 (flow_stage_mst seed rows).
-- Applies to: tenant database dev3 (QA) FIRST. Promote to other tenants later
--       via tenant-schema-check + run-migration (always confirm target).
--
-- Creates (in dependency order):
--   1. flow_stage_mst          - generic stage master (module + stage_code), seeded for 'ENQUIRY'
--   2. sales_enquiry           - enquiry header (full standard approval lifecycle, Q4)
--   3. sales_enquiry_dtl       - enquired items (existing item OR free-text new design)
--   4. flow_stage_log          - handoff + feedback trail (generic doc_type/doc_id)
--   5. enquiry_price_check     - Design/Costing -> Procurement pricing consult header
--   6. enquiry_price_check_dtl - per-item price check lines (last-PO prefill snapshot)
--   7. co_menu_iso_map         - ISO document number per (company x menu) (Q2/Q7)
-- Alters:
--   sales_quotation      + sales_enquiry_id (FK)
--   sales_quotation_dtl  + enquiry_dtl_id, cost_snapshot_id, base_cost, overhead_pct, margin_pct
--   sales_order          + committed_delivery_date, advance_amount, advance_note, sales_enquiry_id (FK)
--   item_bom_hdr_mst     + cost_basis_qty (rollup output-qty divisor, §5.2)
-- Seeds: flow_stage_mst 14 rows for module 'ENQUIRY' (§4).
--
-- Conventions: soft delete via active INT DEFAULT 1. Audit = updated_by +
--   updated_date_time ONLY (history via DB triggers — no created_* columns).
--   DOUBLE for qty/rate/amount. Persona: Portal (tenant DB).
--
-- RUNNER NOTE (run-migration skill): statements are split on the semicolon
--   character and any chunk that STARTS with a comment marker is skipped.
--   Therefore every comment block below is terminated by a lone semicolon on
--   its own line, so the statement that follows starts its own chunk. Do not
--   remove the stray semicolons. Comment prose must never contain a mid-line
--   semicolon (it would split the chunk and execute the remainder as SQL).
--
-- Re-runnable: CREATE TABLE IF NOT EXISTS. Seed uses INSERT IGNORE (unique key
--   (module, stage_code)). ALTERs are guarded via information_schema sentinel
--   column checks (MySQL 8 has no ADD COLUMN IF NOT EXISTS).
--
-- Rollback: see trailing comment block at end of file.
;

-- =============================================================================
-- 1. flow_stage_mst — stage master (generic by module, 'ENQUIRY' in Phase 1)
--    dept_hint is a display label ONLY (NOT an FK — dept_mst rows are
--    tenant/branch-specific, design §5.1). Unique (module, stage_code).
-- =============================================================================
;
CREATE TABLE IF NOT EXISTS flow_stage_mst (
    stage_id          INT          NOT NULL AUTO_INCREMENT,
    module            VARCHAR(30)  NOT NULL,                 -- 'ENQUIRY' (other flows may reuse later)
    stage_code        VARCHAR(30)  NOT NULL,
    stage_name        VARCHAR(100) NOT NULL,
    dept_hint         VARCHAR(50)  NULL,                     -- display label only, NOT an FK
    sequence_no       INT          NOT NULL DEFAULT 0,       -- gaps of 10, and 999 = out-of-band terminal (LOST)
    is_terminal       INT          NOT NULL DEFAULT 0,
    active            INT          NOT NULL DEFAULT 1,
    PRIMARY KEY (stage_id),
    CONSTRAINT uk_flow_stage_module_code UNIQUE (module, stage_code),
    INDEX idx_flow_stage_module_seq (module, sequence_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 2. sales_enquiry — enquiry header (§5.1).
--    Company scope derived via branch (matches sales tables — no co_id,
--    consistent with sales_quotation). Full standard approval lifecycle:
--    21 Draft -> 1 Open -> 20 Pending -> 3 Approved / 4 Rejected. 21->6 cancel.
--    5 Closed at the end ("Lost" = status 5 + close_reason='lost' + stage LOST).
--    current_stage_id is a denormalized pointer (source of truth = latest
--    flow_stage_log row). stage_since drives days-in-stage on the board.
-- =============================================================================
;
CREATE TABLE IF NOT EXISTS sales_enquiry (
    sales_enquiry_id       INT           NOT NULL AUTO_INCREMENT,
    enquiry_no             VARCHAR(50)   NULL,               -- minted at open (prefix ENQ, per branch + FY)
    enquiry_date           DATE          NULL,               -- date received
    received_via           VARCHAR(20)   NULL,               -- email / phone / visit / tender / other
    branch_id              INT           NULL,
    party_id               INT           NULL,               -- customer (nullable at Draft for new prospects, required before Open, app-enforced)
    contact_person         VARCHAR(255)  NULL,
    contact_detail         VARCHAR(255)  NULL,               -- phone/email as given on the enquiry
    customer_ref_no        VARCHAR(100)  NULL,               -- customer's enquiry / tender reference
    expected_delivery_date DATE          NULL,
    enquiry_desc           VARCHAR(1000) NULL,
    internal_note          VARCHAR(1000) NULL,
    current_stage_id       INT           NULL,               -- FK flow_stage_mst (NULL until opened)
    stage_since            DATETIME      NULL,               -- when current stage was entered (aging)
    hold_flag              INT           NOT NULL DEFAULT 0, -- 1 = on hold
    status_id              INT           NULL DEFAULT 21,    -- 21 Draft (standard lifecycle)
    approval_level         INT           NULL DEFAULT 0,     -- level counter within status 20
    close_reason           VARCHAR(20)   NULL,               -- won / lost / cancelled
    lost_remarks           VARCHAR(500)  NULL,
    project_id             INT           NULL,               -- optional (auto-create at ORDER_CONFIRMED, Q5)
    active                 INT           NOT NULL DEFAULT 1,
    updated_by             INT           NOT NULL,
    updated_date_time      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (sales_enquiry_id),
    INDEX idx_sales_enquiry_no (enquiry_no),
    INDEX idx_sales_enquiry_branch (branch_id),
    INDEX idx_sales_enquiry_party (party_id),
    INDEX idx_sales_enquiry_stage (current_stage_id, hold_flag, active),   -- flow-board query
    INDEX idx_sales_enquiry_status (status_id),
    CONSTRAINT fk_sales_enquiry_branch  FOREIGN KEY (branch_id)        REFERENCES branch_mst (branch_id),
    CONSTRAINT fk_sales_enquiry_party   FOREIGN KEY (party_id)         REFERENCES party_mst (party_id),
    CONSTRAINT fk_sales_enquiry_stage   FOREIGN KEY (current_stage_id) REFERENCES flow_stage_mst (stage_id),
    CONSTRAINT fk_sales_enquiry_status  FOREIGN KEY (status_id)        REFERENCES status_mst (status_id),
    CONSTRAINT fk_sales_enquiry_project FOREIGN KEY (project_id)       REFERENCES project_mst (project_id),
    CONSTRAINT chk_sales_enquiry_received_via
        CHECK (received_via IS NULL OR received_via IN ('email', 'phone', 'visit', 'tender', 'other')),
    CONSTRAINT chk_sales_enquiry_close_reason
        CHECK (close_reason IS NULL OR close_reason IN ('won', 'lost', 'cancelled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 3. sales_enquiry_dtl — enquired items (§5.1).
--    item_id NULL when the item does not exist yet (new design) — then
--    item_desc_freetext is mandatory (app-enforced). cost_snapshot_id +
--    confirmed_cost_per_unit are written by the costing-confirm action
--    (immutable evidence even if the snapshot is recomputed later).
--    Per spec this dtl carries only `active` (no updated_by/updated_date_time).
-- =============================================================================
;
CREATE TABLE IF NOT EXISTS sales_enquiry_dtl (
    enquiry_dtl_id          INT          NOT NULL AUTO_INCREMENT,
    sales_enquiry_id        INT          NOT NULL,
    item_id                 INT          NULL,               -- NULL = item does not exist yet
    item_desc_freetext      VARCHAR(500) NULL,               -- mandatory when item_id IS NULL (app-enforced)
    is_new_item             INT          NOT NULL DEFAULT 0, -- 1 = design must create item + BOM
    design_change           INT          NOT NULL DEFAULT 0, -- 1 = existing item, design change requested
    qty                     DOUBLE       NULL,
    uom_id                  INT          NULL,
    target_price            DOUBLE       NULL,               -- customer's target, if stated
    bom_hdr_id              INT          NULL,               -- BOM/costing version confirmed by costing
    cost_snapshot_id        INT          NULL,               -- confirmed cost basis (costing-confirm action)
    confirmed_cost_per_unit DOUBLE       NULL,               -- copied at confirmation
    costing_confirmed_by    INT          NULL,
    costing_confirmed_date  DATETIME     NULL,
    remarks                 VARCHAR(500) NULL,
    active                  INT          NOT NULL DEFAULT 1,
    PRIMARY KEY (enquiry_dtl_id),
    INDEX idx_enquiry_dtl_hdr (sales_enquiry_id, active),
    INDEX idx_enquiry_dtl_item (item_id),
    INDEX idx_enquiry_dtl_bom (bom_hdr_id),
    INDEX idx_enquiry_dtl_snapshot (cost_snapshot_id),
    CONSTRAINT fk_enquiry_dtl_hdr      FOREIGN KEY (sales_enquiry_id)     REFERENCES sales_enquiry (sales_enquiry_id),
    CONSTRAINT fk_enquiry_dtl_item     FOREIGN KEY (item_id)              REFERENCES item_mst (item_id),
    CONSTRAINT fk_enquiry_dtl_uom      FOREIGN KEY (uom_id)               REFERENCES uom_mst (uom_id),
    CONSTRAINT fk_enquiry_dtl_bom      FOREIGN KEY (bom_hdr_id)           REFERENCES item_bom_hdr_mst (bom_hdr_id),
    CONSTRAINT fk_enquiry_dtl_snapshot FOREIGN KEY (cost_snapshot_id)     REFERENCES bom_cost_snapshot (bom_cost_snapshot_id),
    CONSTRAINT fk_enquiry_dtl_conf_by  FOREIGN KEY (costing_confirmed_by) REFERENCES user_mst (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 4. flow_stage_log — the handoff + feedback trail (§5.1).
--    Deliberately GENERIC (doc_type + doc_id, no FK to the document) so the
--    same mechanism can track other flows later without schema change.
--    Phase 1 writes only doc_type = 'SALES_ENQUIRY'. `action` and
--    `linked_doc_type` value sets are enforced in src/sales/enquiry_constants.py
--    (no DB CHECK — Phase 2 extends the sets without DDL).
--    feedback is mandatory when action = 'SEND_BACK' (app-enforced).
-- =============================================================================
;
CREATE TABLE IF NOT EXISTS flow_stage_log (
    stage_log_id     BIGINT        NOT NULL AUTO_INCREMENT,
    doc_type         VARCHAR(30)   NOT NULL,                 -- 'SALES_ENQUIRY' (only value in Phase 1)
    doc_id           INT           NOT NULL,                 -- sales_enquiry_id (generic: no FK by design)
    from_stage_id    INT           NULL,                     -- NULL on the creation entry
    to_stage_id      INT           NOT NULL,
    action           VARCHAR(20)   NOT NULL,                 -- CREATE / FORWARD / SEND_BACK / HOLD / RESUME / MARK_LOST / CLOSE / AUTO
    feedback         VARCHAR(1000) NULL,                     -- mandatory on SEND_BACK (app-enforced)
    linked_doc_type  VARCHAR(30)   NULL,                     -- QUOTATION / SALES_ORDER / PRICE_CHECK / (Phase 2 values)
    linked_doc_id    INT           NULL,
    action_by        INT           NOT NULL,                 -- user_id
    action_date_time DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stage_log_id),
    INDEX idx_flow_stage_log_doc (doc_type, doc_id, stage_log_id),   -- timeline + latest-entry lookup
    CONSTRAINT fk_flow_stage_log_from FOREIGN KEY (from_stage_id) REFERENCES flow_stage_mst (stage_id),
    CONSTRAINT fk_flow_stage_log_to   FOREIGN KEY (to_stage_id)   REFERENCES flow_stage_mst (stage_id),
    CONSTRAINT fk_flow_stage_log_user FOREIGN KEY (action_by)     REFERENCES user_mst (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 5. enquiry_price_check — Design/Costing -> Procurement pricing consult (§5.1).
--    Internal and lightweight (no approval workflow). pc_status:
--    pending / responded / cancelled.
-- =============================================================================
;
CREATE TABLE IF NOT EXISTS enquiry_price_check (
    price_check_id      INT          NOT NULL AUTO_INCREMENT,
    sales_enquiry_id    INT          NOT NULL,
    request_note        VARCHAR(500) NULL,                   -- what costing wants checked
    pc_status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    requested_by        INT          NULL,
    requested_date_time DATETIME     NULL,
    responded_by        INT          NULL,
    responded_date_time DATETIME     NULL,
    response_note       VARCHAR(500) NULL,                   -- procurement's overall feedback
    active              INT          NOT NULL DEFAULT 1,
    updated_by          INT          NOT NULL,
    updated_date_time   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (price_check_id),
    INDEX idx_price_check_enquiry (sales_enquiry_id, active),
    INDEX idx_price_check_status (pc_status, active),        -- procurement pending worklist
    CONSTRAINT fk_price_check_enquiry FOREIGN KEY (sales_enquiry_id) REFERENCES sales_enquiry (sales_enquiry_id),
    CONSTRAINT fk_price_check_req_by  FOREIGN KEY (requested_by)     REFERENCES user_mst (user_id),
    CONSTRAINT fk_price_check_resp_by FOREIGN KEY (responded_by)     REFERENCES user_mst (user_id),
    CONSTRAINT chk_price_check_status CHECK (pc_status IN ('pending', 'responded', 'cancelled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 6. enquiry_price_check_dtl (§5.1). last_po_rate / last_po_date /
--    last_supplier_id are AUTO-PREFILLED at request time from
--    get_last_purchase_rates_by_item_group (snapshot = evidence-stable answer).
--    Per spec this dtl carries no active/audit columns.
-- =============================================================================
;
CREATE TABLE IF NOT EXISTS enquiry_price_check_dtl (
    price_check_dtl_id INT          NOT NULL AUTO_INCREMENT,
    price_check_id     INT          NOT NULL,
    enquiry_dtl_id     INT          NULL,                    -- link to the enquiry line, when applicable
    item_id            INT          NOT NULL,
    last_po_rate       DOUBLE       NULL,                    -- prefilled snapshot at request time
    last_po_date       DATE         NULL,
    last_supplier_id   INT          NULL,
    confirmed_rate     DOUBLE       NULL,                    -- procurement's answer
    rate_source        VARCHAR(20)  NULL,                    -- last_po / supplier_quote / estimate
    supplier_id        INT          NULL,                    -- if a specific supplier was consulted
    remarks            VARCHAR(500) NULL,
    PRIMARY KEY (price_check_dtl_id),
    INDEX idx_pc_dtl_hdr (price_check_id),
    INDEX idx_pc_dtl_enquiry_line (enquiry_dtl_id),
    INDEX idx_pc_dtl_item (item_id),
    CONSTRAINT fk_pc_dtl_hdr          FOREIGN KEY (price_check_id)   REFERENCES enquiry_price_check (price_check_id),
    CONSTRAINT fk_pc_dtl_enquiry_line FOREIGN KEY (enquiry_dtl_id)   REFERENCES sales_enquiry_dtl (enquiry_dtl_id),
    CONSTRAINT fk_pc_dtl_item         FOREIGN KEY (item_id)          REFERENCES item_mst (item_id),
    CONSTRAINT fk_pc_dtl_last_supp    FOREIGN KEY (last_supplier_id) REFERENCES party_mst (party_id),
    CONSTRAINT fk_pc_dtl_supp         FOREIGN KEY (supplier_id)      REFERENCES party_mst (party_id),
    CONSTRAINT chk_pc_dtl_rate_source
        CHECK (rate_source IS NULL OR rate_source IN ('last_po', 'supplier_quote', 'estimate'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 7. co_menu_iso_map — ISO document numbers (Q2/Q7, design §5.1). Generic and
--    reusable across all modules/tenants (NOT AMCL-specific): document
--    view/print headers look up by the page's menu_id + selected co_id;
--    if a row exists the ISO number is shown, otherwise the space stays blank.
-- =============================================================================
;
CREATE TABLE IF NOT EXISTS co_menu_iso_map (
    iso_map_id        INT         NOT NULL AUTO_INCREMENT,
    co_id             INT         NOT NULL,
    menu_id           INT         NOT NULL,                  -- the document type (each transaction type is a menu)
    iso_doc_no        VARCHAR(50) NOT NULL,
    active            INT         NOT NULL DEFAULT 1,
    updated_by        INT         NOT NULL,
    updated_date_time DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (iso_map_id),
    CONSTRAINT uk_co_menu_iso UNIQUE (co_id, menu_id),
    INDEX idx_co_menu_iso_menu (menu_id),
    CONSTRAINT fk_co_menu_iso_co   FOREIGN KEY (co_id)   REFERENCES co_mst (co_id),
    CONSTRAINT fk_co_menu_iso_menu FOREIGN KEY (menu_id) REFERENCES menu_mst (menu_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 8. Seed flow_stage_mst — module 'ENQUIRY', 14 rows per design §4.
--    Sequence gaps of 10 (10..130). LOST has no position in the forward chain
--    (reachable from any stage <= 50): sequence_no 999 = out-of-band terminal.
--    dept_hint values are the AMCL display labels from the §4 table (Q2);
--    NULL where the table shows none (CLOSED, LOST). Idempotent via
--    INSERT IGNORE against unique (module, stage_code).
-- =============================================================================
;
INSERT IGNORE INTO flow_stage_mst (module, stage_code, stage_name, dept_hint, sequence_no, is_terminal, active) VALUES
    ('ENQUIRY', 'ENQ_NOTED',           'Enquiry Noted',                     'Sales/Marketing',  10,  0, 1),
    ('ENQUIRY', 'COSTING_REVIEW',      'Design & Costing Review',           'Design & Costing', 20,  0, 1),
    ('ENQUIRY', 'PRICE_CHECK',         'Procurement Price Check',           'Purchase',         30,  0, 1),
    ('ENQUIRY', 'QUOTATION',           'Quotation & Customer Follow-up',    'Sales/Marketing',  40,  0, 1),
    ('ENQUIRY', 'ORDER_CONFIRMED',     'Order Confirmed',                   'Sales/Marketing',  50,  0, 1),
    ('ENQUIRY', 'DESIGN_RELEASE',      'Design Release / Work Order',       'Design',           60,  0, 1),
    ('ENQUIRY', 'PRODUCTION_PLANNING', 'Production Planning (BOM to Indent)', 'PPC',            70,  0, 1),
    ('ENQUIRY', 'PROCUREMENT',         'Procurement in Progress',           'Purchase',         80,  0, 1),
    ('ENQUIRY', 'MATERIAL_READY',      'Materials Ready / Production Start', 'PPC',             90,  0, 1),
    ('ENQUIRY', 'PRODUCTION',          'Production in Progress',            'Production',       100, 0, 1),
    ('ENQUIRY', 'FG_HANDOVER',         'Finished Goods to Stores / Packing', 'Stores',          110, 0, 1),
    ('ENQUIRY', 'READY_FOR_DELIVERY',  'Ready for Delivery',                'Stores -> Sales',  120, 0, 1),
    ('ENQUIRY', 'CLOSED',              'Closed',                            NULL,               130, 1, 1),
    ('ENQUIRY', 'LOST',                'Lost / Regret',                     NULL,               999, 1, 1);

-- =============================================================================
-- 9. ALTER sales_quotation — quote traces to enquiry (§5.2).
--    Guarded on sentinel column sales_enquiry_id (re-runnable no-op when present).
-- =============================================================================
;
SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'sales_quotation'
      AND column_name = 'sales_enquiry_id'
);
SET @ddl := IF(@col_exists = 0,
    'ALTER TABLE sales_quotation ADD COLUMN sales_enquiry_id INT NULL, ADD INDEX idx_sales_quotation_enquiry (sales_enquiry_id), ADD CONSTRAINT fk_sales_quotation_enquiry FOREIGN KEY (sales_enquiry_id) REFERENCES sales_enquiry (sales_enquiry_id)',
    'DO 0');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- =============================================================================
-- 10. ALTER sales_quotation_dtl — auto-pricing cost basis on the quote line
--     (§5.2): rate prefilled = base_cost x (1 + overhead_pct/100) x
--     (1 + margin_pct/100), editable. Logical references only (no FK
--     constraints), mirroring sales_order_dtl.quotation_lineitem_id
--     loose-coupling. Guarded on sentinel column enquiry_dtl_id.
-- =============================================================================
;
SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'sales_quotation_dtl'
      AND column_name = 'enquiry_dtl_id'
);
SET @ddl := IF(@col_exists = 0,
    'ALTER TABLE sales_quotation_dtl ADD COLUMN enquiry_dtl_id INT NULL, ADD COLUMN cost_snapshot_id INT NULL, ADD COLUMN base_cost DOUBLE NULL, ADD COLUMN overhead_pct DOUBLE NULL, ADD COLUMN margin_pct DOUBLE NULL, ADD INDEX idx_sales_quotation_dtl_enq_line (enquiry_dtl_id)',
    'DO 0');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- =============================================================================
-- 11. ALTER sales_order — G8 + decision Q3 (§5.2): committed delivery date +
--     advance commitment fields, and the SO's own enquiry link for the
--     direct/tender path (order without a quotation).
--     Guarded on sentinel column sales_enquiry_id.
-- =============================================================================
;
SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'sales_order'
      AND column_name = 'sales_enquiry_id'
);
SET @ddl := IF(@col_exists = 0,
    'ALTER TABLE sales_order ADD COLUMN committed_delivery_date DATE NULL, ADD COLUMN advance_amount DOUBLE NULL, ADD COLUMN advance_note VARCHAR(255) NULL, ADD COLUMN sales_enquiry_id INT NULL, ADD INDEX idx_sales_order_enquiry (sales_enquiry_id), ADD CONSTRAINT fk_sales_order_enquiry FOREIGN KEY (sales_enquiry_id) REFERENCES sales_enquiry (sales_enquiry_id)',
    'DO 0');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- =============================================================================
-- 12. ALTER item_bom_hdr_mst — cost_basis_qty (§5.2): output-qty divisor for
--     the cost rollup (fixes bom_cost_snapshot.cost_per_unit = total_cost with
--     no divisor). Rollup divides by this. Default 1 preserves current numbers.
--     Guarded on sentinel column cost_basis_qty.
-- =============================================================================
;
SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'item_bom_hdr_mst'
      AND column_name = 'cost_basis_qty'
);
SET @ddl := IF(@col_exists = 0,
    'ALTER TABLE item_bom_hdr_mst ADD COLUMN cost_basis_qty DOUBLE NOT NULL DEFAULT 1',
    'DO 0');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- =============================================================================
-- ROLLBACK (run manually, in this order — FKs from altered tables must go
-- before the new tables they reference, then tables in reverse dependency order):
--
--   ALTER TABLE item_bom_hdr_mst DROP COLUMN cost_basis_qty;
--   ALTER TABLE sales_order DROP FOREIGN KEY fk_sales_order_enquiry;
--   ALTER TABLE sales_order DROP INDEX idx_sales_order_enquiry;
--   ALTER TABLE sales_order DROP COLUMN sales_enquiry_id, DROP COLUMN advance_note, DROP COLUMN advance_amount, DROP COLUMN committed_delivery_date;
--   ALTER TABLE sales_quotation_dtl DROP INDEX idx_sales_quotation_dtl_enq_line;
--   ALTER TABLE sales_quotation_dtl DROP COLUMN margin_pct, DROP COLUMN overhead_pct, DROP COLUMN base_cost, DROP COLUMN cost_snapshot_id, DROP COLUMN enquiry_dtl_id;
--   ALTER TABLE sales_quotation DROP FOREIGN KEY fk_sales_quotation_enquiry;
--   ALTER TABLE sales_quotation DROP INDEX idx_sales_quotation_enquiry;
--   ALTER TABLE sales_quotation DROP COLUMN sales_enquiry_id;
--   DROP TABLE IF EXISTS co_menu_iso_map;
--   DROP TABLE IF EXISTS enquiry_price_check_dtl;
--   DROP TABLE IF EXISTS enquiry_price_check;
--   DROP TABLE IF EXISTS flow_stage_log;
--   DROP TABLE IF EXISTS sales_enquiry_dtl;
--   DROP TABLE IF EXISTS sales_enquiry;
--   DROP TABLE IF EXISTS flow_stage_mst;
-- =============================================================================
