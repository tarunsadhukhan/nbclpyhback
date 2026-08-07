-- Create jute_yarn_type_mst table
CREATE TABLE IF NOT EXISTS jute_yarn_type_mst (
    jute_yarn_type_id INT AUTO_INCREMENT PRIMARY KEY,
    jute_yarn_type_name VARCHAR(255) NULL,
    co_id INT NULL,
    updated_by INT NULL,
    updated_date_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_co_id (co_id),
    INDEX idx_name (jute_yarn_type_name)
);

-- Create yarn_quality_master table
CREATE TABLE IF NOT EXISTS yarn_quality_master (
    yarn_quality_id INT AUTO_INCREMENT PRIMARY KEY,
    quality_code VARCHAR(20) NULL,
    jute_yarn_type_id INT NULL,
    twist_per_inch FLOAT NULL,
    std_count FLOAT NULL,
    std_doff INT NULL,
    std_wt_doff FLOAT NULL,
    is_active INT DEFAULT 1,
    branch_id INT NULL,
    co_id INT NULL,
    updated_by INT NULL,
    updated_date_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_quality_code (quality_code),
    INDEX idx_jute_yarn_type_id (jute_yarn_type_id),
    INDEX idx_co_id (co_id),
    INDEX idx_branch_id (branch_id),
    FOREIGN KEY (jute_yarn_type_id) REFERENCES jute_yarn_type_mst(jute_yarn_type_id)
);
