
-- CREATE country_mst TABLE
CREATE TABLE country_mst (
    country_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    country VARCHAR(255) NOT NULL UNIQUE
);

-- CREATE state_mst TABLE
CREATE TABLE state_mst (
    state_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    state VARCHAR(255) NOT NULL UNIQUE,
    country_id INT NOT NULL,
    FOREIGN KEY (country_id) REFERENCES country_mst(country_id)
);

-- CREATE city_mst TABLE
CREATE TABLE city_mst (
    city_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    city_name VARCHAR(255),
    state_id INT,
    FOREIGN KEY (state_id) REFERENCES state_mst(state_id)
);

-- SAMPLE DATA INSERTS

-- Countries
INSERT INTO country_mst (country) VALUES 
('India'),
('USA');

-- States (assuming India is country_id = 1)
INSERT INTO state_mst (state, country_id) VALUES 
('West Bengal', 1),
('Maharashtra', 1),
('California', 2);

-- Cities (assuming state_ids as follows: WB=1, MH=2, CA=3)
INSERT INTO city_mst (city_name, state_id) VALUES 
('Kolkata', 1),
('Howrah', 1),
('Mumbai', 2),
('Pune', 2),
('San Francisco', 3),
('Los Angeles', 3);

CREATE TABLE co_mst (
    co_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    co_name VARCHAR(255) NOT NULL UNIQUE,
    co_prefix VARCHAR(25) NOT NULL UNIQUE,
    co_address1 VARCHAR(255) NOT NULL,
    co_address2 VARCHAR(255) NOT NULL,
    co_zipcode INT NOT NULL,
    country_id INT NOT NULL,
    state_id INT NOT NULL,
    city_id INT NOT NULL,
    co_logo VARCHAR(255),
    auto_datetime_insert DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by_con_user INTEGER,
    co_cin_no VARCHAR(25),
    co_email_id VARCHAR(255),
    co_pan_no VARCHAR(25),
    s3bucket_name VARCHAR(255),
    s3folder_name VARCHAR(255),
    tally_sync VARCHAR(255),
    alert_email_id VARCHAR(255),
    branch_prefix VARCHAR(100),
    FOREIGN KEY (country_id) REFERENCES country_mst(country_id),
    FOREIGN KEY (state_id) REFERENCES state_mst(state_id),
    FOREIGN KEY (city_id) REFERENCES city_mst(city_id)
);

-- CREATE TABLE branch_mst
CREATE TABLE branch_mst (
    branch_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    branch_name VARCHAR(255) NOT NULL UNIQUE,
    co_id INT NOT NULL,
    branch_address1 VARCHAR(255),
    branch_address2 VARCHAR(255),
    branch_zipcode INT,
    country_id INT,
    city_id INT,
    state_id INT,
    gst_no VARCHAR(25),
    contact_no INT,
    contact_person VARCHAR(255),
    branch_email VARCHAR(255),
    active BOOLEAN,
    gst_verified BOOLEAN,
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (country_id) REFERENCES country_mst(country_id),
    FOREIGN KEY (state_id) REFERENCES state_mst(state_id),
    FOREIGN KEY (city_id) REFERENCES city_mst(city_id)
);


CREATE TABLE user_mst (
    user_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    email_id VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255),
    password VARCHAR(255),
    refresh_token VARCHAR(255),
    active BOOLEAN NOT NULL,
    created_by_con_user INTEGER,
    created_date_time DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- CREATE module_mst TABLE
CREATE TABLE module_mst (
    module_mst_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    module_name VARCHAR(255) NOT NULL UNIQUE,
    module_type INT,
    active BOOLEAN
);

-- TABLE: access_type
CREATE TABLE access_type (
    access_type_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    access_type VARCHAR(25) NOT NULL UNIQUE
);

-- TABLE: roles_mst
CREATE TABLE roles_mst (
    role_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    role_name VARCHAR(255) NOT NULL UNIQUE,
    active BOOLEAN,
    created_by_con_user INTEGER,
    created_date_time DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- TABLE: menu_type_mst
CREATE TABLE menu_type_mst (
    menu_type_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    menu_type VARCHAR(25) NOT NULL UNIQUE
);

-- TABLE: menu_mst
CREATE TABLE menu_mst (
    menu_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    menu_name VARCHAR(255) NOT NULL UNIQUE,
    menu_path VARCHAR(255),
    active BOOLEAN NOT NULL,
    menu_parent_id INT,
    menu_type_id INT,
    menu_icon VARCHAR(255),
    FOREIGN KEY (menu_type_id) REFERENCES menu_type_mst(menu_type_id)
);

-- TABLE: role_menu_map
CREATE TABLE role_menu_map (
    role_menu_mapping_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    role_id INT,
    menu_id INT,
    access_type_id INT,
    FOREIGN KEY (role_id) REFERENCES roles_mst(role_id),
    FOREIGN KEY (menu_id) REFERENCES menu_mst(menu_id),
    FOREIGN KEY (access_type_id) REFERENCES access_type(access_type_id)
);

-- TABLE: user_role_map
CREATE TABLE user_role_map (
    user_role_map_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    role_id INT NOT NULL,
    co_id INT NOT NULL,
    branch_id INT NOT NULL,
    created_by_con_user INT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user_mst(user_id),
    FOREIGN KEY (role_id) REFERENCES roles_mst(role_id),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id)
);

CREATE TABLE approval_mst (
    approval_mst_id INT NOT NULL AUTO_INCREMENT,
    menu_id INT NOT NULL,
    user_id INT NOT NULL,
    branch_id INT NOT NULL,
    approval_level INT NOT NULL,
    max_amount_single DOUBLE,
    day_max_amount DOUBLE,
    month_max_amount DOUBLE,
    PRIMARY KEY (approval_mst_id),
    FOREIGN KEY (menu_id) REFERENCES menu_mst(menu_id),
    FOREIGN KEY (user_id) REFERENCES user_mst(user_id),
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id)
);