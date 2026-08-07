-- Item BOM (Bill of Materials) Master Table
-- Stores parent-child relationships between items for assembly visualization
-- Uses adjacency list pattern: each row links one parent item to one child item

CREATE TABLE item_bom (
    bom_id INT NOT NULL AUTO_INCREMENT,
    parent_item_id INT NOT NULL,
    child_item_id INT NOT NULL,
    qty DOUBLE NOT NULL DEFAULT 1,
    uom_id INT NOT NULL,
    co_id INT NOT NULL,
    sequence_no INT DEFAULT 0,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NULL,
    updated_date_time DATETIME NULL,
    PRIMARY KEY (bom_id),
    INDEX idx_bom_parent (parent_item_id, co_id, active),
    INDEX idx_bom_child (child_item_id, co_id, active),
    CONSTRAINT fk_bom_parent FOREIGN KEY (parent_item_id) REFERENCES item_mst(item_id),
    CONSTRAINT fk_bom_child FOREIGN KEY (child_item_id) REFERENCES item_mst(item_id),
    CONSTRAINT fk_bom_uom FOREIGN KEY (uom_id) REFERENCES uom_mst(uom_id),
    CONSTRAINT chk_bom_no_self CHECK (parent_item_id != child_item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rollback:
-- DROP TABLE IF EXISTS item_bom;
