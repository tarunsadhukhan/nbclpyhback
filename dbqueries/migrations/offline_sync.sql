-- ============================================================================
-- Offline-First Sync (Android app) — schema migration
--
-- RUN ONCE PER TENANT DATABASE (nbcl, sls, ...). The mobile Flask app picks the
-- database per request from the X-Tenant header / Host subdomain, so a tenant
-- that has not had this applied simply keeps working with offline sync
-- degraded: /sync/face-embeddings returns an empty gallery, the replay guard
-- stands aside, and mark-attendance ignores the extra fields.
--
--   USE nbcl;
--   SOURCE dbqueries/migrations/offline_sync.sql;
--
-- Every statement is additive (ADD COLUMN / CREATE TABLE) — nothing is dropped
-- or rewritten. Re-applying errors with "Duplicate column name"; ignore those.
-- ============================================================================

-- ── 1. Generic idempotency ledger ───────────────────────────────────────────
-- ponytail: ONE table instead of a client_uuid column + unique index on every
-- transaction table. The replay guard (src/mobileapp/src/sync/idempotency.py)
-- works for every mobile POST, present and future, with no per-route change.
CREATE TABLE IF NOT EXISTS sync_client_uuid (
    client_uuid   VARCHAR(36)  NOT NULL,
    endpoint      VARCHAR(160) NOT NULL,
    http_status   INT          NULL,          -- NULL while the request is in flight
    response_json MEDIUMTEXT   NULL,          -- replayed verbatim to the device
    device_id     VARCHAR(64)  NULL,
    captured_at   DATETIME     NULL,          -- device clock at capture
    created_at    DATETIME     NOT NULL,
    PRIMARY KEY (client_uuid),
    KEY idx_scu_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 2. daily_attendance — offline punch bookkeeping ─────────────────────────
ALTER TABLE daily_attendance
    ADD COLUMN client_uuid        VARCHAR(36)  NULL,
    ADD COLUMN entry_source_time  DATETIME     NULL,   -- device clock at punch
    ADD COLUMN sync_received_time DATETIME     NULL,   -- server clock at upload
    ADD COLUMN clock_skew_secs    INT          NULL,   -- device - server, at capture
    ADD COLUMN face_verify_status VARCHAR(12)  NULL,   -- MATCH / MISMATCH / NO_FACE
    ADD COLUMN match_confidence   DECIMAL(5,2) NULL,   -- on-device cosine * 100
    ADD COLUMN needs_review       TINYINT(1)   DEFAULT 0,
    ADD COLUMN dup_of             BIGINT       NULL;

ALTER TABLE daily_attendance
    ADD UNIQUE KEY uq_daily_attendance_uuid (client_uuid);

-- Cross-device duplicate detection leans on this lookup.
ALTER TABLE daily_attendance
    ADD KEY idx_da_dedupe (eb_id, attendance_date, spell_id, is_active);

-- ── 3. employee_face_mst — mobile (MobileFaceNet) embedding space ───────────
ALTER TABLE employee_face_mst
    ADD COLUMN face_embedding_mobile MEDIUMTEXT  NULL,  -- JSON array, L2-normalised
    ADD COLUMN mobile_model_ver      VARCHAR(32) NULL,  -- e.g. "mobilefacenet-v1"
    ADD COLUMN mobile_embed_updated  DATETIME    NULL;

ALTER TABLE employee_face_mst
    ADD KEY idx_efm_mobile_updated (mobile_embed_updated);

-- ── 4. Server-driven client config (thresholds, staleness ladder, min build) ─
-- Lets a mis-tuned face threshold be fixed with a config push instead of
-- reinstalling the APK on a dozen shop-floor devices.
CREATE TABLE IF NOT EXISTS sync_client_config (
    config_key   VARCHAR(64)  NOT NULL,
    config_value VARCHAR(255) NOT NULL,
    updated_at   DATETIME     NULL,
    PRIMARY KEY (config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO sync_client_config (config_key, config_value, updated_at) VALUES
    ('face_accept_threshold',  '0.62', NOW()),
    ('face_review_threshold',  '0.55', NOW()),
    ('face_margin_threshold',  '0.05', NOW()),
    ('perm_stale_warn_days',   '7',    NOW()),
    ('perm_stale_lock_days',   '14',   NOW()),
    ('offline_photo_keep_days','30',   NOW()),
    ('min_app_version',        '1.0',  NOW());
