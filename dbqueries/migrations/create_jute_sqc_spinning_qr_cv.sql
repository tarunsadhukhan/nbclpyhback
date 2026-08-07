-- R-08-15 Yarn QR & CV %  (header + detail). Layered on R-08-16 count data.
-- observed_count / mr_pct are NOT stored here; they are read from R-08-16's
-- already-saved values in jute_sqc_spinning_count (AVG per item_id) at read time.
-- Rollback:
--   DROP TABLE IF EXISTS jute_sqc_spinning_qr_cv_dtl;
--   DROP TABLE IF EXISTS jute_sqc_spinning_qr_cv;

CREATE TABLE IF NOT EXISTS jute_sqc_spinning_qr_cv (
    spinning_sqc_qr_cv_id INT NOT NULL AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    branch_id             INT NULL,
    entry_date            DATE NOT NULL,
    mc_id                 INT NULL,
    item_id               INT NOT NULL,
    active                INT NOT NULL DEFAULT 1,
    updated_by            INT NULL,
    updated_date_time     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (spinning_sqc_qr_cv_id),
    KEY idx_qrcv_co (co_id),
    KEY idx_qrcv_date (entry_date),
    KEY idx_qrcv_item (item_id)
);

CREATE TABLE IF NOT EXISTS jute_sqc_spinning_qr_cv_dtl (
    spinning_sqc_qr_cv_dtl_id INT NOT NULL AUTO_INCREMENT,
    spinning_sqc_qr_cv_id     INT NOT NULL,
    spindle_no                INT NOT NULL,
    reading_no                SMALLINT NOT NULL,
    reading_val               DECIMAL(10,3) NULL,
    PRIMARY KEY (spinning_sqc_qr_cv_dtl_id),
    KEY idx_qrcv_dtl_hdr (spinning_sqc_qr_cv_id)
);
