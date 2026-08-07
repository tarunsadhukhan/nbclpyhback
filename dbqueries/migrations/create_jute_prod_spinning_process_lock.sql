-- Migration: jute_prod_spinning_process_lock — one lock header per (co, branch, date, spell).
-- Mirror of jute_prod_weaving_process_lock (see create_jute_prod_weaving_process_lock.sql).
-- Rollback: DROP TABLE jute_prod_spinning_process_lock;
CREATE TABLE jute_prod_spinning_process_lock (
  spinning_process_lock_id INT PRIMARY KEY AUTO_INCREMENT,
  co_id                INT NOT NULL,
  branch_id            INT NULL,
  tran_date            DATE NOT NULL,
  spell_id             INT NOT NULL,
  is_locked            TINYINT NOT NULL DEFAULT 1,
  reprocess_needed     TINYINT NOT NULL DEFAULT 0,
  processed_by         INT NULL,
  processed_date_time  TIMESTAMP NULL,
  active               TINYINT NOT NULL DEFAULT 1,
  updated_by           INT NULL,
  updated_date_time    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_slock_unit (co_id, tran_date, spell_id)
);
