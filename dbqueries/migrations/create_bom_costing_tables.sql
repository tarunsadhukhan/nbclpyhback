-- Migration: Create BOM Costing Tables
-- Purpose: Creates 5 tables + 1 view for BOM costing sheet functionality:
--   1. bom_hdr           - Versioned BOM header linking items to costing versions
--   2. cost_element_mst  - Self-referencing cost element taxonomy tree
--   3. bom_cost_entry    - Cost values per BOM version per cost element
--   4. std_rate_card     - Reusable standard rates (machine, labor, power, etc.)
--   5. bom_cost_snapshot - Cached rollup snapshots of computed costs
--   6. vw_bom_cost_summary - Reporting view pivoting cost entries into fixed columns
-- Also seeds default cost element hierarchy with co_id = 0 (template).
-- Date: 2026-03-30
-- Run against: TENANT database (e.g., dev3, sls)

-- ═══════════════════════════════════════════════════════════════════
-- Table 1: bom_hdr — Versioned BOM Header
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS item_bom_hdr_mst (
    bom_hdr_id         INT          NOT NULL AUTO_INCREMENT,
    item_id            INT          NOT NULL,
    bom_version        INT          NOT NULL DEFAULT 1,
    version_label      VARCHAR(50)  NULL,
    status_id          INT          NOT NULL DEFAULT 21,
    effective_from     DATE         NULL,
    effective_to       DATE         NULL,
    is_current         INT          NOT NULL DEFAULT 0,
    remarks            TEXT         NULL,
    co_id              INT          NOT NULL,
    active             INT          NOT NULL DEFAULT 1,
    updated_by         INT          NOT NULL,
    updated_date_time  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (bom_hdr_id),

    CONSTRAINT uk_bom_hdr_item_version_co
        UNIQUE (item_id, bom_version, co_id),

    CONSTRAINT fk_bom_hdr_item
        FOREIGN KEY (item_id) REFERENCES item_mst(item_id),

    CONSTRAINT fk_bom_hdr_status
        FOREIGN KEY (status_id) REFERENCES status_mst(status_id),

    INDEX idx_bom_hdr_item_co (item_id, co_id, active),
    INDEX idx_bom_hdr_current (item_id, co_id, is_current),
    INDEX idx_bom_hdr_status (status_id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ═══════════════════════════════════════════════════════════════════
-- Table 2: cost_element_mst — Cost Element Taxonomy Tree
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cost_element_mst (
    cost_element_id    INT          NOT NULL AUTO_INCREMENT,
    element_code       VARCHAR(30)  NOT NULL,
    element_name       VARCHAR(100) NOT NULL,
    parent_element_id  INT          NULL,
    element_level      INT          NOT NULL DEFAULT 0,
    element_type       VARCHAR(30)  NOT NULL COMMENT 'material | conversion | overhead',
    default_basis      VARCHAR(30)  NULL     COMMENT 'per_unit | per_machine_hour | per_kg | per_batch | per_month_allocated | fixed | percentage | per_hour | per_kwh',
    is_leaf            INT          NOT NULL DEFAULT 0 COMMENT '1 = leaf (accepts cost values), 0 = category node',
    sort_order         INT          NOT NULL DEFAULT 0,
    element_desc       TEXT         NULL,
    co_id              INT          NOT NULL,
    active             INT          NOT NULL DEFAULT 1,
    updated_by         INT          NOT NULL,
    updated_date_time  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (cost_element_id),

    CONSTRAINT uk_cost_element_code_co
        UNIQUE (element_code, co_id),

    CONSTRAINT fk_cost_element_parent
        FOREIGN KEY (parent_element_id) REFERENCES cost_element_mst(cost_element_id),

    CONSTRAINT chk_cost_element_type
        CHECK (element_type IN ('material', 'conversion', 'overhead')),

    CONSTRAINT chk_cost_element_basis
        CHECK (default_basis IS NULL OR default_basis IN (
            'per_unit', 'per_machine_hour', 'per_kg', 'per_batch',
            'per_month_allocated', 'fixed', 'percentage', 'per_hour', 'per_kwh'
        )),

    INDEX idx_cost_element_parent (parent_element_id),
    INDEX idx_cost_element_co_active (co_id, active),
    INDEX idx_cost_element_type (element_type, co_id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ═══════════════════════════════════════════════════════════════════
-- Table 3: bom_cost_entry — Cost Values per BOM Version
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS bom_cost_entry (
    bom_cost_entry_id  INT          NOT NULL AUTO_INCREMENT,
    bom_hdr_id         INT          NOT NULL,
    cost_element_id    INT          NOT NULL,
    amount             DOUBLE       NOT NULL DEFAULT 0,
    source             VARCHAR(30)  NOT NULL DEFAULT 'manual' COMMENT 'calculated | assumed | manual | imported | standard',
    qty                DOUBLE       NULL,
    rate               DOUBLE       NULL,
    basis_override     VARCHAR(30)  NULL     COMMENT 'overrides cost_element_mst.default_basis for this entry',
    effective_date     DATE         NOT NULL,
    entered_by         INT          NULL,
    remarks            TEXT         NULL,
    co_id              INT          NOT NULL,
    active             INT          NOT NULL DEFAULT 1,
    updated_by         INT          NOT NULL,
    updated_date_time  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (bom_cost_entry_id),

    CONSTRAINT uk_bom_cost_entry
        UNIQUE (bom_hdr_id, cost_element_id, effective_date),

    CONSTRAINT fk_bom_cost_entry_hdr
        FOREIGN KEY (bom_hdr_id) REFERENCES item_bom_hdr_mst(bom_hdr_id),

    CONSTRAINT fk_bom_cost_entry_element
        FOREIGN KEY (cost_element_id) REFERENCES cost_element_mst(cost_element_id),

    CONSTRAINT fk_bom_cost_entry_entered_by
        FOREIGN KEY (entered_by) REFERENCES user_mst(user_id),

    CONSTRAINT chk_bom_cost_entry_source
        CHECK (source IN ('calculated', 'assumed', 'manual', 'imported', 'standard')),

    INDEX idx_bom_cost_entry_hdr_co (bom_hdr_id, co_id, active),
    INDEX idx_bom_cost_entry_element (cost_element_id),
    INDEX idx_bom_cost_entry_effective (effective_date, co_id),
    INDEX idx_bom_cost_entry_entered_by (entered_by)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ═══════════════════════════════════════════════════════════════════
-- Table 4: std_rate_card — Standard Rate Cards
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS std_rate_card (
    std_rate_card_id   INT          NOT NULL AUTO_INCREMENT,
    rate_type          VARCHAR(30)  NOT NULL COMMENT 'machine_hour | labor_hour | power_kwh | floor_space_sqft | overhead_pct',
    reference_id       INT          NULL     COMMENT 'Polymorphic FK: machine_mst, dept_mst, or cost_element_mst depending on reference_type',
    reference_type     VARCHAR(30)  NULL     COMMENT 'machine | dept | cost_element',
    rate               DOUBLE       NOT NULL DEFAULT 0,
    uom                VARCHAR(30)  NULL     COMMENT 'Unit label: hr, kwh, sqft, pct, etc.',
    valid_from         DATE         NOT NULL,
    valid_to           DATE         NULL,
    co_id              INT          NOT NULL,
    active             INT          NOT NULL DEFAULT 1,
    updated_by         INT          NOT NULL,
    updated_date_time  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (std_rate_card_id),

    CONSTRAINT chk_std_rate_card_type
        CHECK (rate_type IN ('machine_hour', 'labor_hour', 'power_kwh', 'floor_space_sqft', 'overhead_pct')),

    CONSTRAINT chk_std_rate_card_ref_type
        CHECK (reference_type IS NULL OR reference_type IN ('machine', 'dept', 'cost_element')),

    CONSTRAINT chk_std_rate_card_date_range
        CHECK (valid_to IS NULL OR valid_to >= valid_from),

    INDEX idx_std_rate_card_type_co (rate_type, co_id, active),
    INDEX idx_std_rate_card_ref (reference_type, reference_id),
    INDEX idx_std_rate_card_valid (valid_from, valid_to, co_id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ═══════════════════════════════════════════════════════════════════
-- Table 5: bom_cost_snapshot — Cost Rollup Snapshots
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS bom_cost_snapshot (
    bom_cost_snapshot_id INT        NOT NULL AUTO_INCREMENT,
    bom_hdr_id           INT        NOT NULL,
    material_cost        DOUBLE     NOT NULL DEFAULT 0,
    conversion_cost      DOUBLE     NOT NULL DEFAULT 0,
    overhead_cost        DOUBLE     NOT NULL DEFAULT 0,
    total_cost           DOUBLE     NOT NULL DEFAULT 0,
    cost_per_unit        DOUBLE     NOT NULL DEFAULT 0,
    detail_snapshot      JSON       NULL     COMMENT 'Full element-level breakdown as JSON array',
    computed_at          DATETIME   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    computed_by          INT        NULL,
    is_current           INT        NOT NULL DEFAULT 0 COMMENT '1 = latest active snapshot for this BOM version',
    status               VARCHAR(30) NOT NULL DEFAULT 'draft' COMMENT 'draft | approved | superseded',
    co_id                INT        NOT NULL,
    active               INT        NOT NULL DEFAULT 1,
    updated_by           INT        NOT NULL,
    updated_date_time    TIMESTAMP  NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (bom_cost_snapshot_id),

    CONSTRAINT fk_bom_cost_snapshot_hdr
        FOREIGN KEY (bom_hdr_id) REFERENCES item_bom_hdr_mst(bom_hdr_id),

    CONSTRAINT fk_bom_cost_snapshot_computed_by
        FOREIGN KEY (computed_by) REFERENCES user_mst(user_id),

    CONSTRAINT chk_bom_cost_snapshot_status
        CHECK (status IN ('draft', 'approved', 'superseded')),

    INDEX idx_bom_cost_snapshot_hdr_co (bom_hdr_id, co_id, active),
    INDEX idx_bom_cost_snapshot_current (bom_hdr_id, co_id, is_current),
    INDEX idx_bom_cost_snapshot_status (status, co_id),
    INDEX idx_bom_cost_snapshot_computed_by (computed_by)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ═══════════════════════════════════════════════════════════════════
-- View: vw_bom_cost_summary — Reporting View
-- ═══════════════════════════════════════════════════════════════════

DROP VIEW IF EXISTS vw_bom_cost_summary;

CREATE VIEW vw_bom_cost_summary AS
SELECT
    bh.bom_hdr_id,
    bh.item_id,
    im.item_code,
    im.item_name,
    bh.bom_version,
    bh.version_label,
    bh.status_id,
    bce.co_id,
    bce.effective_date,

    -- Material cost subtotal (leaf entries only)
    SUM(CASE WHEN ce.element_type = 'material' THEN bce.amount ELSE 0 END) AS material_cost,

    -- Conversion cost subtotal
    SUM(CASE WHEN ce.element_type = 'conversion' THEN bce.amount ELSE 0 END) AS conversion_cost,

    -- Overhead cost subtotal
    SUM(CASE WHEN ce.element_type = 'overhead' THEN bce.amount ELSE 0 END) AS overhead_cost,

    -- Grand total
    SUM(bce.amount) AS total_cost,

    -- Count of cost entries
    COUNT(*) AS entry_count

FROM bom_cost_entry bce
INNER JOIN cost_element_mst ce
    ON bce.cost_element_id = ce.cost_element_id
INNER JOIN item_bom_hdr_mst bh
    ON bce.bom_hdr_id = bh.bom_hdr_id
INNER JOIN item_mst im
    ON bh.item_id = im.item_id
WHERE bce.active = 1
  AND ce.active = 1
  AND bh.active = 1
GROUP BY
    bh.bom_hdr_id,
    bh.item_id,
    im.item_code,
    im.item_name,
    bh.bom_version,
    bh.version_label,
    bh.status_id,
    bce.co_id,
    bce.effective_date;

-- ═══════════════════════════════════════════════════════════════════
-- Seed Data: Default Cost Element Hierarchy (co_id = 0 = template)
-- Application should copy these to the actual tenant co_id on setup.
-- ═══════════════════════════════════════════════════════════════════

-- Level 0: Root categories
INSERT INTO cost_element_mst
    (element_code, element_name, parent_element_id, element_level, element_type, default_basis, is_leaf, sort_order, element_desc, co_id, updated_by)
VALUES
    ('MAT',  'Material Cost',   NULL, 0, 'material',   NULL, 0, 100, 'All raw material and component costs',       0, 0),
    ('CONV', 'Conversion Cost', NULL, 0, 'conversion', NULL, 0, 200, 'All manufacturing conversion costs',          0, 0),
    ('OH',   'Overhead Cost',   NULL, 0, 'overhead',   NULL, 0, 300, 'Factory and administrative overhead costs',   0, 0);

-- Level 1: Material children
INSERT INTO cost_element_mst
    (element_code, element_name, parent_element_id, element_level, element_type, default_basis, is_leaf, sort_order, element_desc, co_id, updated_by)
SELECT 'MP_DIRECT', 'Direct Material (from BOM)', ce.cost_element_id, 1, 'material', 'per_unit', 1, 110,
       'Sum of child item costs from BOM explosion', 0, 0
FROM cost_element_mst ce WHERE ce.element_code = 'MAT' AND ce.co_id = 0;

INSERT INTO cost_element_mst
    (element_code, element_name, parent_element_id, element_level, element_type, default_basis, is_leaf, sort_order, element_desc, co_id, updated_by)
SELECT 'MP_PROCESS', 'Process Material Loss / Scrap', ce.cost_element_id, 1, 'material', 'percentage', 1, 120,
       'Material wastage and scrap allowance as percentage', 0, 0
FROM cost_element_mst ce WHERE ce.element_code = 'MAT' AND ce.co_id = 0;

INSERT INTO cost_element_mst
    (element_code, element_name, parent_element_id, element_level, element_type, default_basis, is_leaf, sort_order, element_desc, co_id, updated_by)
SELECT 'MP_PACKING', 'Packing Material', ce.cost_element_id, 1, 'material', 'per_unit', 1, 130,
       'Packing and packaging material cost per unit', 0, 0
FROM cost_element_mst ce WHERE ce.element_code = 'MAT' AND ce.co_id = 0;

-- Level 1: Conversion children
INSERT INTO cost_element_mst
    (element_code, element_name, parent_element_id, element_level, element_type, default_basis, is_leaf, sort_order, element_desc, co_id, updated_by)
SELECT 'CV_MACHINE', 'Machine Cost', ce.cost_element_id, 1, 'conversion', 'per_machine_hour', 1, 210,
       'Machine running cost per machine-hour', 0, 0
FROM cost_element_mst ce WHERE ce.element_code = 'CONV' AND ce.co_id = 0;

INSERT INTO cost_element_mst
    (element_code, element_name, parent_element_id, element_level, element_type, default_basis, is_leaf, sort_order, element_desc, co_id, updated_by)
SELECT 'CV_LABOR', 'Direct Labor', ce.cost_element_id, 1, 'conversion', 'per_hour', 1, 220,
       'Direct labor cost per labor-hour', 0, 0
FROM cost_element_mst ce WHERE ce.element_code = 'CONV' AND ce.co_id = 0;

INSERT INTO cost_element_mst
    (element_code, element_name, parent_element_id, element_level, element_type, default_basis, is_leaf, sort_order, element_desc, co_id, updated_by)
SELECT 'CV_POWER', 'Power / Electricity', ce.cost_element_id, 1, 'conversion', 'per_kwh', 1, 230,
       'Electricity cost per kWh consumption', 0, 0
FROM cost_element_mst ce WHERE ce.element_code = 'CONV' AND ce.co_id = 0;

INSERT INTO cost_element_mst
    (element_code, element_name, parent_element_id, element_level, element_type, default_basis, is_leaf, sort_order, element_desc, co_id, updated_by)
SELECT 'CV_TOOLING', 'Tooling & Dies', ce.cost_element_id, 1, 'conversion', 'per_batch', 1, 240,
       'Tooling amortization per batch', 0, 0
FROM cost_element_mst ce WHERE ce.element_code = 'CONV' AND ce.co_id = 0;

-- Level 1: Overhead children
INSERT INTO cost_element_mst
    (element_code, element_name, parent_element_id, element_level, element_type, default_basis, is_leaf, sort_order, element_desc, co_id, updated_by)
SELECT 'OH_FACTORY', 'Factory Overhead', ce.cost_element_id, 1, 'overhead', 'per_month_allocated', 1, 310,
       'Factory rent, maintenance, indirect labor allocated monthly', 0, 0
FROM cost_element_mst ce WHERE ce.element_code = 'OH' AND ce.co_id = 0;

INSERT INTO cost_element_mst
    (element_code, element_name, parent_element_id, element_level, element_type, default_basis, is_leaf, sort_order, element_desc, co_id, updated_by)
SELECT 'OH_ADMIN', 'Administrative Overhead', ce.cost_element_id, 1, 'overhead', 'percentage', 1, 320,
       'Admin and office overhead as percentage of conversion cost', 0, 0
FROM cost_element_mst ce WHERE ce.element_code = 'OH' AND ce.co_id = 0;

INSERT INTO cost_element_mst
    (element_code, element_name, parent_element_id, element_level, element_type, default_basis, is_leaf, sort_order, element_desc, co_id, updated_by)
SELECT 'OH_DEPREC', 'Depreciation', ce.cost_element_id, 1, 'overhead', 'per_month_allocated', 1, 330,
       'Asset depreciation allocated monthly', 0, 0
FROM cost_element_mst ce WHERE ce.element_code = 'OH' AND ce.co_id = 0;

-- Rollback:
-- DROP VIEW IF EXISTS vw_bom_cost_summary;
-- DROP TABLE IF EXISTS bom_cost_snapshot;
-- DROP TABLE IF EXISTS bom_cost_entry;
-- DROP TABLE IF EXISTS std_rate_card;
-- DELETE FROM cost_element_mst WHERE co_id = 0;
-- DROP TABLE IF EXISTS cost_element_mst;
-- DROP TABLE IF EXISTS item_bom_hdr_mst;
