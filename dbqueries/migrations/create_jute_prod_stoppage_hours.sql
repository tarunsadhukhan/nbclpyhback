-- Jute Production — Stoppage Hours event log (per SPEC.md §6).
-- Target tenant DB: dev3.
-- Rollback: DROP TABLE IF EXISTS jute_prod_stoppage_hours;
CREATE TABLE jute_prod_stoppage_hours (
    stoppage_hours_id   INT          NOT NULL AUTO_INCREMENT,
    co_id               INT          NOT NULL,
    branch_id           INT          NULL,
    tran_date           DATE         NOT NULL,
    spell_id            INT          NOT NULL,
    machine_id          INT          NOT NULL,
    stoppage_hours      DECIMAL(5,2) NOT NULL,
    reason_code         VARCHAR(20)  NOT NULL,   -- mechanical | electrical | labor | other (fixed enum, app-enforced)
    remarks             VARCHAR(255) NULL,
    active              TINYINT      NOT NULL DEFAULT 1,
    updated_by          INT          NULL,
    updated_date_time   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (stoppage_hours_id),
    KEY idx_stoppage_co_branch_date        (co_id, branch_id, tran_date),
    KEY idx_stoppage_machine_date_spell    (machine_id, tran_date, spell_id),   -- non-unique (event log): allows many events per machine/date/spell
    KEY idx_stoppage_spell                 (spell_id),
    CONSTRAINT fk_stoppage_machine FOREIGN KEY (machine_id) REFERENCES machine_mst (machine_id),
    CONSTRAINT fk_stoppage_spell   FOREIGN KEY (spell_id)   REFERENCES spell_mst   (spell_id)
);
