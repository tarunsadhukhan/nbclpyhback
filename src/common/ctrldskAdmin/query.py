from sqlalchemy.sql import text
from sqlalchemy.sql import bindparam
from sqlalchemy.sql.elements import TextClause

def get_portal_menu_details(search: str = None):
    print(f" query get_portal_menu_details called with search: {search} ")
    sql = """
        SELECT 
            menu.menu_id,
            menu.menu_name,
            menu.menu_parent_id AS parent_id,
            menu.module_id,
            cmm.con_module_name,
            CASE 
                WHEN menu.menu_parent_id > 0 THEN (SELECT parent.menu_name 
                                                  FROM vowconsole3.portal_menu_mst parent 
                                                  WHERE parent.menu_id = menu.menu_parent_id)
                ELSE ''
            END AS parent_name,
            menu.active,
            menu.menu_path,
            menu.menu_icon,
            menu.module_id
        FROM vowconsole3.portal_menu_mst menu
        LEFT JOIN vowconsole3.con_module_masters cmm ON menu.module_id = cmm.con_module_id 
        WHERE cmm.active = 1
    """

    # Add search filter if search is provided
    if search:
        sql += " AND menu.menu_name LIKE :search "

    sql += " ORDER BY menu.order_by "

    return text(sql)





def portal_parentmenudetails():
    #print(f" query portal_parentmenudetails called with moduleId: {moduleId} ")
    sql = """SELECT 
                menu.menu_id,
                menu.menu_name,
                menu.module_id
            FROM vowconsole3.portal_menu_mst menu
            WHERE menu.menu_parent_id = 0 AND menu.active = 1"""
    sql += " ORDER BY module_id, menu.order_by"""
    #print(f"SQL Query: {sql}{moduleId}")
    
    return text(sql)





def portalmodulename():
    print(f" query portalmodulename called ")
    sql="""SELECT 
                menu.con_module_id,
                menu.con_module_name
                FROM vowconsole3.con_module_masters menu
                where  menu.active = 1
                order by menu.con_module_name            
"""
    return text(sql)



def portalmenutypedetails():
    print(f" query portalmenutypedetails called ")
    sql="""SELECT * 
                FROM vowconsole3.menu_type_mst
            
"""
    return text(sql)

def get_portalmenuname_by_name(name: str = None, menu_id: int = None):
    print(f" query get_portalmenuname_by_name called with name: {name} ")
    if menu_id == 0:
        sql = """SELECT count(*) as count 
                FROM vowconsole3.portal_menu_mst menu
                where menu.menu_name = :name            
        """
    else:
        sql = """SELECT count(*) as count 
                FROM vowconsole3.portal_menu_mst menu
                where menu.menu_name = :name and menu.menu_id != :menu_id            
        """
    return text(sql)



def get_menu_by_id_query(co_id: int):
    sql = f"""select menu_id,menu_name,menu_path,active,menu_parent_id,menu_type_id,
    menu_icon,module_id,order_by
    from vowconsole3.portal_menu_mst
    where menu_id = :co_id;"""
    query = text(sql)
    return query



def orgmodulename(search: str = None):
    print(f" query orgmodulename called ")
    sql="""SELECT 
            com.con_org_id AS org_id,
            com.con_org_name AS org_name,
            GROUP_CONCAT(cmm.con_module_name SEPARATOR '/') AS module_selected
            FROM 
            vowconsole3.con_org_master com
            LEFT JOIN JSON_TABLE(
            com.con_modules_selected,
            '$[*]' COLUMNS (
            module_id VARCHAR(10) PATH '$'
            )
        ) AS jt ON TRUE
        LEFT JOIN con_module_masters cmm 
        ON cmm.con_module_id = jt.module_id
        WHERE 
        com.con_org_master_status = 3
        GROUP BY 
        com.con_org_id, com.con_org_name
"""
    return text(sql)

 

# text(f"""
#             SELECT 
#                 menu.menu_id,
#                 menu.menu_name,
#                 menu.menu_parent_id AS parent_id,
#                 CASE 
#                     WHEN menu.menu_parent_id > 0 THEN (SELECT parent.menu_name 
#                                                       FROM {dbname}.portal_menu_mst parent 
#                                                       WHERE parent.menu_id = menu.menu_parent_id)
#                     ELSE ''
#                 END AS parent_name,
#                 menu.active,
#                 menu.menu_path,
#                 menu.menu_icon,
#                 menu.module_id
#             FROM {dbname}.portal_menu_mst menu
#         """)