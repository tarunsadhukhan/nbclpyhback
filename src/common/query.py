from sqlalchemy.sql import text
from sqlalchemy.sql import bindparam
from sqlalchemy.sql.elements import TextClause

def get_menu_for_user1_query():
    sql="""WITH RECURSIVE MenuHierarchy AS (
        SELECT
          mm.control_desk_menu_id AS id,
          mm.control_desk_menu_name AS title,
          mm.menu_path AS path,
          null AS icon,
          mm.parent_id, mm.control_desk_menu_id mmenu_id
        FROM
          vowconsole3.control_desk_menu mm
        WHERE
          mm.parent_id = 0
        UNION ALL
        SELECT
          mm.control_desk_menu_id AS id,
          mm.control_desk_menu_name AS title,
          mm.menu_path AS path,
          null AS icon,
          mm.parent_id,
          mm.parent_id mmenu_id
        FROM
          vowconsole3.control_desk_menu mm
        INNER JOIN
          MenuHierarchy mh ON mm.parent_id = mh.id
        )
        SELECT mh.id, title,
        CASE WHEN parent_id = 66 THEN concat('store/', path) ELSE path END path, icon, parent_id, mmenu_id,
        null company_id, :userid user_id FROM MenuHierarchy mh ORDER BY mmenu_id"""
    return text(sql)
    
    
def get_menu_for_othuser_query():
    return text("""select k.* from (
WITH RECURSIVE MenuHierarchy AS (
        SELECT
          mm.control_desk_menu_id AS id,
          mm.control_desk_menu_name AS title,
          mm.menu_path AS path,
          null AS icon,
          mm.parent_id, mm.control_desk_menu_id mmenu_id
        FROM
          vowconsole3.control_desk_menu mm
        WHERE
          mm.parent_id = 0
        UNION ALL
        SELECT
          mm.control_desk_menu_id AS id,
          mm.control_desk_menu_name AS title,
          mm.menu_path AS path,
          null AS icon,
          mm.parent_id,
          mm.parent_id mmenu_id
        FROM
          vowconsole3.control_desk_menu mm
        INNER JOIN
          MenuHierarchy mh ON mm.parent_id = mh.id
        )
        SELECT mh.id, title,
        CASE WHEN parent_id = 66 THEN concat('store/', path) ELSE path END path, icon, parent_id, mmenu_id,
        null company_id, :userid user_id FROM MenuHierarchy mh ORDER BY mmenu_id limit 3290 ) k
        join (
        select control_desk_menu_id from control_desk_menu cdm 
        where cdm.control_desk_menu_id in (select con_menu_id from con_role_menu_map crmm where con_role_id = 
        (select curm.con_role_id from con_user_role_mapping curm where curm.con_user_id = :userid) )
        ) g on  k.id=g.control_desk_menu_id """)


def get_attdata_othuser_query():
    return text("""select * from worker_masterk.* from (
WITH RECURSIVE MenuHierarchy AS (
        SELECT
          mm.control_desk_menu_id AS id,
          mm.control_desk_menu_name AS title,
          mm.menu_path AS path,
          null AS icon,
          mm.parent_id, mm.control_desk_menu_id mmenu_id
        FROM
          vowconsole3.control_desk_menu mm
        WHERE
          mm.parent_id = 0
        UNION ALL
        SELECT
          mm.control_desk_menu_id AS id,
          mm.control_desk_menu_name AS title,
          mm.menu_path AS path,
          null AS icon,
          mm.parent_id,
          mm.parent_id mmenu_id
        FROM
          vowconsole3.control_desk_menu mm
        INNER JOIN
          MenuHierarchy mh ON mm.parent_id = mh.id
        )
        SELECT mh.id, title,
        CASE WHEN parent_id = 66 THEN concat('store/', path) ELSE path END path, icon, parent_id, mmenu_id,
        null company_id, :userid user_id FROM MenuHierarchy mh ORDER BY mmenu_id limit 3290 ) k
        join (
        select control_desk_menu_id from vowconsole3.con_user_role_mapping curm 
        left join vowconsole3.con_role_menu_mapping crmm on curm.con_role_id =crmm.con_role_id
        where curm.con_user_id =:userid
        ) g on  k.id=g.control_desk_menu_id """)



""" CREATE TABLE roles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    type VARCHAR(50) NOT NULL,
    has_hrms_access BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_name (name),
    INDEX idx_type (type),
    INDEX idx_hrms_access (has_hrms_access)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
 """


def get_role_for_user111_query():
    return text("""
        SELECT r.* 
        FROM roles r 
        WHERE r.has_hrms_access = true 
        AND :userid = 1
        ORDER BY r.created_at DESC 
        LIMIT :limit OFFSET :offset
    """)

def get_role_for_user1_query(search: str = None):
    return text("""
        select eb_id id,concat(worker_name,eb_no) name,cata_desc type, false has_hrms_access, '2025-03-05' created_at,'2025-03-06' updated_at
        from vowsls.worker_master wm 
        left join vowsls.category_master cm on wm.cata_id =cm.cata_id
        where wm.company_id=2 and wm.active ='Y'
                AND (:search IS NULL OR (
            wm.worker_name LIKE CONCAT('%', :search, '%') OR 
            cata_desc LIKE CONCAT('%', :search, '%')
        ))
        ORDER BY wm.eb_id DESC 
        LIMIT :limit OFFSET :offset
    """)


def get_role_for_user1_query_company(search: str = None, dbm: str = None):
    sql = f"SELECT * FROM {dbm}.roles_mst LIMIT :limit OFFSET :offset"
    query = text(sql)
    return query

def get_roles_tenant_admin(search: str = None, org_id: int = None):
    sql = f"SELECT * FROM con_role_master where con_org_id = :org_id LIMIT :limit OFFSET :offset"
    query = text(sql)
    return query



def get_roles_ctrldsk_admin(search: str = None):
    sql = f"SELECT * FROM con_role_master where ifnull(con_org_id,0) =0 LIMIT :limit OFFSET :offset"
    query = text(sql)
    return query


def get_roles_ctrldsk_full_menu():
    sql = f"SELECT control_desk_menu_id con_menu_id, control_desk_menu_name con_menu_name,case when parent_id=0 then null else parent_id end con_menu_parent_id FROM control_desk_menu cdm  where active =1"
    query = text(sql)
    return query

def get_roles_ctrldsk_menu_by_roleid(role_id: int):
    sql = f"""SELECT cmm.control_desk_menu_id con_menu_id, cmm.control_desk_menu_name con_menu_name, cmm.parent_id con_menu_parent_id, crmm.con_role_id
    FROM control_desk_menu cmm 
    LEFT JOIN con_role_menu_map crmm 
    ON crmm.con_menu_id = cmm.control_desk_menu_id 
    WHERE crmm.con_role_id = :role_id"""
    query = text(sql)
    return query





def get_roles_tenant(search: str = None):
    sql = f"SELECT role_id, role_name, active FROM roles_mst LIMIT :limit OFFSET :offset"
    query = text(sql)
    return query


def get_users_tenant(search: str = None):
    sql = f"SELECT user_id, name , email_id, active FROM user_mst LIMIT :limit OFFSET :offset"
    query = text(sql)
    return query

def get_users_tenant_admin_query(search: str = None, org_id: int = None):
    sql = """
        SELECT 
            cum.con_user_id,
            cum.con_user_name,
            cum.con_user_login_email_id,
            cum.active,
            cum.con_user_type,
            crm.con_role_id,
            crm.con_role_name 
        FROM con_user_master cum 
        JOIN con_user_role_mapping curm ON cum.con_user_id = curm.con_user_id
        JOIN con_role_master crm ON curm.con_role_id = crm.con_role_id
        WHERE cum.con_org_id = :org_id
        AND (:search IS NULL OR 
             cum.con_user_name LIKE :search OR 
             cum.con_user_login_email_id LIKE :search)
        ORDER BY cum.con_user_id
        LIMIT :limit OFFSET :offset
    """
    return text(sql)



def get_users_ctrldesk_admin_query(search: str = None):
    sql = """
        SELECT 
            cum.con_user_id,
            cum.con_user_name,
            cum.con_user_login_email_id,
            cum.active,
            cum.con_user_type,
            crm.con_role_id,
            crm.con_role_name 
        FROM con_user_master cum 
        JOIN con_user_role_mapping curm ON cum.con_user_id = curm.con_user_id
        JOIN con_role_master crm ON curm.con_role_id = crm.con_role_id
        WHERE cum.con_org_id is null
        AND (:search IS NULL OR 
             cum.con_user_name LIKE :search OR 
             cum.con_user_login_email_id LIKE :search)
        ORDER BY cum.con_user_id
        LIMIT :limit OFFSET :offset
    """
    return text(sql)

# from typing import Optional

# def get_roles_co_console(search: Optional[str], org_id: int) -> TextClause:
#     # """
#     # Generate SQL query for retrieving roles for a specific organization.
    
#     # Args:
#     #     search: Optional search term
#     #     org_id: Organization ID
        
#     # Returns:
#     #     SQLAlchemy TextClause query
#     # """
#     # query = """
#     #     SELECT *
#     #     FROM vowconsole3.con_role_master 
#     #     WHERE con_org_id = :org_id 
#     # """
    
#     # if search:
#     #     query += " AND con_role_name LIKE :search"
        
#     # query += """
#     #     ORDER BY created_date_time DESC
#     #     LIMIT :limit OFFSET :offset
#     # """
#     sql = f"SELECT * FROM con_roles_master where con_org_id = :org_id LIMIT :limit OFFSET :offset"
#     query = text(sql)
    
#     return text(query)




# select * from sls.roles_mst
# OFFSET :offset




# def get_menu_for_othuser_query():
#     return text("""
#         SELECT r.* 
#         FROM roles r 
#         WHERE r.has_hrms_access = false 
#         OR :userid != 1
#         ORDER BY r.created_at DESC 
#         LIMIT :limit OFFSET :offset
#     """)

def get_total_count_query(user_id: int,search: str = None):
    if user_id == 1:
        return text("""
            SELECT COUNT(*) as total 
            FROM (select eb_id id,concat(worker_name,eb_no) name,cata_desc type, false has_hrms_access, '2025-03-05' created_at,'2025-03-06' updated_at
        from vowsls.worker_master wm 
        left join vowsls.category_master cm on wm.cata_id =cm.cata_id
        where wm.company_id=2 and wm.active ='Y'
                    AND (:search IS NULL OR (
            wm.worker_name LIKE CONCAT('%', :search, '%') OR 
            cata_desc LIKE CONCAT('%', :search, '%')
        ))
            )  r 
        """)
    else:
        return text("""
            SELECT COUNT(*) as total 
            FROM roles r 
            WHERE r.has_hrms_access = false 
            OR :userid != 1
        """)
    

def get_orgs_all_query(search: str = None, limit: int = None, offset: int = None):
    sql = f"""select com.con_org_id, com.con_org_name, com.con_org_email_id, 
    com.con_org_shortname, com.con_org_master_status, csm.con_status_name
    from con_org_master com 
    left join con_status_master csm on com.con_org_master_status = csm.con_status_id
    WHERE (:search IS NULL OR 
             com.con_org_name LIKE :search OR 
             com.con_org_email_id LIKE :search OR
             com.con_org_shortname LIKE :search OR
             csm.con_status_name LIKE :search)
        ORDER BY com.con_org_id
        LIMIT :limit OFFSET :offset;"""
    query = text(sql)
    return query

def get_orgs_all_count_query(search: str = None):
    sql = f"""select count(*) as total from con_org_master com 
    where 
    (:search IS NULL OR 
                    com.con_org_name LIKE :search OR 
                    com.con_org_email_id LIKE :search
                      ) 
                      ;"""
    query = text(sql)
    return query

def get_org_by_id_query(org_id: int):
    sql = f"""select com.con_org_id , 
com.con_org_name, 
com.con_org_shortname,
com.con_org_contact_person ,
com.con_org_email_id,
com.con_org_mobile ,
com.con_org_address ,
com.con_org_pincode , 
com.con_org_state_id ,
com.con_org_remarks ,
com.active,
com.con_org_master_status,
com.con_modules_selected, 
com.con_org_main_url
from con_org_master com 
where com.con_org_id = :org_id;"""
    query = text(sql)
    return query

def get_org_modules_query(org_id: int):
    sql = f"""SELECT module_id
FROM con_org_master com
JOIN JSON_TABLE(
  com.con_modules_selected,
  '$[*]' COLUMNS (module_id VARCHAR(255) PATH '$')
) AS modules
WHERE com.con_org_id = :org_id;"""
    query = text(sql)
    return query

def all_countries_query():
    sql = f"""SELECT country_id, country_name FROM con_country_master;"""
    query = text(sql)
    return query

def all_states_query():
    sql = f"""SELECT state_id, state_name, country_id FROM con_state_master;"""
    query = text(sql)
    return query

def get_all_modules_query():
    sql = f"""SELECT con_module_id, con_module_name FROM con_module_masters;"""
    query = text(sql)
    return query

def get_all_status_query():
    sql = f"""SELECT con_status_id, con_status_name FROM con_status_master;"""
    query = text(sql)
    return query



