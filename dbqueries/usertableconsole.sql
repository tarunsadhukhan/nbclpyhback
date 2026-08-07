CREATE TABLE con_role_menu_map (
    con_role_menu_mapping_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    con_role_id INT,
    con_menu_id INT,
    con_org_id INT, 
    FOREIGN KEY (con_role_id) REFERENCES con_role_master(con_role_id),
    FOREIGN KEY (con_menu_id) REFERENCES con_menu_master(con_menu_id),
    FOREIGN KEY (con_org_id) REFERENCES con_org_master(con_org_id)
);


CREATE TABLE  control_desk_menu  (
   control_desk_menu_id  int NOT NULL AUTO_INCREMENT,
   control_desk_menu_name  varchar(50) NOT NULL,
   active  int NOT NULL DEFAULT '1',
   parent_id  int DEFAULT NULL,
   menu_path  varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL,
   menu_state  varchar(100) DEFAULT NULL,
   report_path  varchar(100) DEFAULT NULL,
   menu_icon_name  longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci,
   order_by  int DEFAULT NULL,
   menu_type  int DEFAULT NULL COMMENT '0 for Portal,1 for App',
  PRIMARY KEY ( control_desk_menu_id ))



  CREATE TABLE portal_menu_mst (
    menu_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    menu_name VARCHAR(255) NOT NULL UNIQUE,
    menu_path VARCHAR(255),
    active BOOLEAN NOT NULL,
    menu_parent_id INT,
    menu_type_id INT,
    menu_icon VARCHAR(255),
    module_id INT
);
   