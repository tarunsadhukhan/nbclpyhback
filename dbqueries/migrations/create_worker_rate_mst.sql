-- Worker Rate Muster: monthly rate parameters per worker (source: WORKER RATE MUSTER.xlsx).
-- One active row per employee (eb_id). Y/N flags stored as CHAR(1) exactly as in the muster.
-- No co_id/branch_id of its own — scope comes from the employee (eb_id), like outsider_rate_approve.
-- Target DB: nbcl
-- Rollback: DROP TABLE worker_rate_mst;

CREATE TABLE IF NOT EXISTS worker_rate_mst (
    worker_rate_id INT PRIMARY KEY AUTO_INCREMENT,
    eb_id BIGINT NOT NULL,
    fbasic DOUBLE NULL,
    fbasic_hr DOUBLE NULL,
    da_all CHAR(1) NOT NULL DEFAULT 'N',
    da_rate DOUBLE NULL,
    hra CHAR(1) NOT NULL DEFAULT 'N',
    hrd CHAR(1) NOT NULL DEFAULT 'N',
    quarter CHAR(1) NOT NULL DEFAULT 'N',
    pf CHAR(1) NOT NULL DEFAULT 'N',
    esi CHAR(1) NOT NULL DEFAULT 'N',
    ptax CHAR(1) NOT NULL DEFAULT 'N',
    is_active INT NOT NULL DEFAULT 1,
    KEY idx_worker_rate_eb (eb_id)
);
