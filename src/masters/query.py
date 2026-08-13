from sqlalchemy.sql import text
from sqlalchemy.sql import bindparam
from sqlalchemy.sql.elements import TextClause


def get_item_group(co_id: int = None):
    sql = f"""WITH RECURSIVE item_hierarchy AS (-- Anchor member: level 1
  SELECT 
    igm.item_grp_id,
    igm.item_grp_code,
    igm.item_grp_name,
    igm.parent_grp_id,
    igm.active, 
    igm.item_type_id,
    CAST(igm.item_grp_code AS CHAR) AS item_grp_code_display,
    CAST(igm.item_grp_name AS CHAR) AS item_grp_name_display,
    1 AS level
  FROM item_grp_mst igm
  WHERE igm.parent_grp_id IS NULL AND co_id = :co_id 
UNION ALL -- Recursive member
SELECT 
    child.item_grp_id,
    child.item_grp_code,
    child.item_grp_name,
    child.parent_grp_id,
    child.active,
    child.item_type_id,
    CONCAT(parent.item_grp_code_display, '-', child.item_grp_code),
    CONCAT(parent.item_grp_name_display, '-', child.item_grp_name),
    parent.level + 1
  FROM item_grp_mst child
  JOIN item_hierarchy parent ON child.parent_grp_id = parent.item_grp_id
)
SELECT 
  item_grp_id, 
  item_grp_code_display,-- item_grp_name_display based on level
  CASE 
    WHEN level = 1 THEN item_grp_name_display
    WHEN level = 2 THEN SUBSTRING_INDEX(item_grp_name_display, '-', 1)
    ELSE SUBSTRING_INDEX(item_grp_name_display, '-', level - 1)
  END AS item_grp_name_parent,
  -- item_grp_name based on level
  CASE 
    WHEN level = 1 THEN NULL
    ELSE SUBSTRING_INDEX(item_grp_name_display, '-', -1)
  END AS item_sub_grp_name,
  active,
  item_type_id
FROM item_hierarchy where (:search IS NULL OR 
                    item_grp_code_display LIKE :search OR 
                    item_grp_name_display LIKE :search) ;"""
    query = text(sql)
    return query


def get_item_group_drodown(co_id: int = None):
    sql = f"""WITH RECURSIVE item_hierarchy AS (-- Anchor member: start with top-level nodes (no parent)
  SELECT 
    igm.item_grp_id,
    igm.item_grp_code,
    igm.item_grp_name,
    igm.parent_grp_id ,
    CAST(igm.item_grp_code AS CHAR) AS item_grp_code_display,
    CAST(igm.item_grp_name AS CHAR) AS item_grp_name_display
  FROM item_grp_mst igm
  WHERE igm.parent_grp_id IS NULL and igm.co_id =:co_id and (igm.active IN ('Y', '1') OR igm.active IS NULL)
  UNION ALL-- Recursive member: join with children
  SELECT 
    child.item_grp_id,
    child.item_grp_code,
    child.item_grp_name,
    child.parent_grp_id,
    CONCAT(parent.item_grp_code_display, '-', child.item_grp_code),
    CONCAT(parent.item_grp_name_display, '-', child.item_grp_name)
  FROM item_grp_mst child
  JOIN item_hierarchy parent ON child.parent_grp_id = parent.item_grp_id
  WHERE (child.active IN ('Y', '1') OR child.active IS NULL)
) 
SELECT 
  item_grp_id,
  item_grp_code_display,
  item_grp_name_display
FROM item_hierarchy
ORDER BY item_grp_code_display;"""
    query = text(sql)
    return query


def india_gst_applicable():
    sql = """
select cc.india_gst  from co_config cc where cc.co_id =:co_id;
"""
    query = text(sql)
    return query

def check_item_group_code_and_name(co_id: int, item_grp_code: str, item_grp_name: str):
    """
    Check if the item group code and name are valid for the given company.
    Returns a boolean indicating if the code and name are valid.
    """
    sql = """
WITH RECURSIVE all_descendants AS (
    -- Start from the parent where the new item would be added
    SELECT 
        item_grp_id,
        item_grp_code,
        item_grp_name,
        parent_grp_id,
        co_id
    FROM item_grp_mst
    WHERE item_grp_id = null AND co_id = :co_id
    UNION ALL
    -- Recursively get all children under that parent
    SELECT 
        child.item_grp_id,
        child.item_grp_code,
        child.item_grp_name,
        child.parent_grp_id,
        child.co_id
    FROM item_grp_mst child
    JOIN all_descendants parent ON child.parent_grp_id = parent.item_grp_id
    WHERE child.co_id = :co_id
)
-- Final check
SELECT
    NOT EXISTS (
        SELECT 1 FROM all_descendants 
        WHERE item_grp_code = :item_grp_code
    ) AS is_code_valid,
    NOT EXISTS (
        SELECT 1 FROM all_descendants 
        WHERE item_grp_name = :item_grp_name
    ) AS is_name_valid;
"""
    return text(sql)


def get_item_group_details_by_id():
    sql = """
        SELECT * FROM item_grp_mst WHERE item_grp_id = :item_grp_id
    """
    return text(sql)

def get_item(co_id: int = None):
    sql = f"""item_id, active, item_grp_id , item_code, tangible, item_name , item_photo , legacy_item_code , hsn_code , uom_id , tax_percentage , 
saleable , consumable , purchaseable , manufacturable , assembly , uom_rounding , rate_rounding 
from item_mst
  WHERE co_id = :co_id 
  AND (:search IS NULL OR 
                    item_grp_code_display LIKE :search OR 
                    item_grp_name_display LIKE :search) ;"""
    query = text(sql)
    return query

def get_item_table(co_id: int = None):
    sql = f"""  WITH RECURSIVE item_hierarchy AS (
  -- Anchor: top-level item groups for company 1
  SELECT 
    igm.item_grp_id,
    igm.item_grp_code,
    igm.item_grp_name,
    igm.parent_grp_id,
    igm.active,
    igm.item_type_id,
    igm.co_id,
    CAST(igm.item_grp_code AS CHAR) AS item_group_code_display,
    CAST(igm.item_grp_name AS CHAR) AS item_group_display,
    1 AS level
  FROM item_grp_mst igm
  WHERE igm.parent_grp_id IS NULL AND igm.co_id = :co_id
  UNION ALL
  -- Recursive part: build full paths for name and code
  SELECT 
    child.item_grp_id,
    child.item_grp_code,
    child.item_grp_name,
    child.parent_grp_id,
    child.active,
    child.item_type_id,
    child.co_id,
    CONCAT(parent.item_group_code_display, '-', child.item_grp_code),
    CONCAT(parent.item_group_display, '-', child.item_grp_name),
    parent.level + 1
  FROM item_grp_mst child 
  JOIN item_hierarchy parent 
    ON child.parent_grp_id = parent.item_grp_id
   AND child.co_id = parent.co_id
)
SELECT
  im.item_id,
  im.item_grp_id,
  ih.item_group_display,
  ih.item_group_code_display,
  im.item_code,
  CONCAT(ih.item_group_code_display, '-', im.item_code) AS full_item_code,
  im.item_name,
  im.active
FROM item_mst im 
INNER JOIN item_hierarchy ih 
  ON im.item_grp_id = ih.item_grp_id
  where (:search IS NULL OR
  ih.item_group_code_display LIKE :search OR
  ih.item_group_display LIKE :search
  OR im.item_code LIKE :search OR
  CONCAT(ih.item_group_code_display, '-', im.item_code) LIKE :search OR
  im.item_name LIKE :search);
"""
    query = text(sql)
    return query


def get_item_table_list_query():
    """Paginated item list for the Item Master grid, over the precomputed
    vw_item_with_group_path view (no inline recursive CTE). Returns the same
    columns the old get_item_table emitted (incl. inactive items) so the grid
    is unchanged. item_group_name_display is aliased to item_group_display to
    match the grid column binding."""
    sql = """SELECT
        item_id,
        item_grp_id,
        item_group_code_display,
        item_group_name_display AS item_group_display,
        item_code,
        full_item_code,
        item_name,
        active
    FROM vw_item_with_group_path
    WHERE co_id = :co_id
      AND (:search_like IS NULL
           OR item_group_code_display LIKE :search_like
           OR item_group_name_display LIKE :search_like
           OR item_code LIKE :search_like
           OR full_item_code LIKE :search_like
           OR item_name LIKE :search_like)
    ORDER BY item_group_code_display ASC, item_code ASC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_item_table_count_query():
    """Total row count for the paginated Item Master grid. WHERE clause must
    stay byte-identical to get_item_table_list_query."""
    sql = """SELECT COUNT(1) AS total
    FROM vw_item_with_group_path
    WHERE co_id = :co_id
      AND (:search_like IS NULL
           OR item_group_code_display LIKE :search_like
           OR item_group_name_display LIKE :search_like
           OR item_code LIKE :search_like
           OR full_item_code LIKE :search_like
           OR item_name LIKE :search_like);"""
    return text(sql)


def get_item_by_id(item_id: int):
    sql = """
  select 
  im.item_id,
  im.active, 
  im.item_grp_id,
  im.item_code, 
  im.item_name,
  im.tangible, 
  im.item_photo,
  im.legacy_item_code ,
  im.hsn_code, 
  im.uom_id,
  um.uom_name ,
  im.tax_percentage,
  im.saleable,
  im.consumable,
  im.purchaseable,
  im.manufacturable,
  im.assembly,
  im.uom_rounding ,
  im.rate_rounding 
  from item_mst im
  left join uom_mst um on um.uom_id = im.uom_id
  where im.item_id = :item_id
  ;"""
    query = text(sql)
    return query


def get_item_group_path(item_grp_id: int):
    sql = """
WITH RECURSIVE item_group_path AS (
  -- Anchor: start from given item group
  SELECT 
    igm.item_grp_id,
    igm.item_grp_code,
    igm.item_grp_name,
    igm.parent_grp_id,
    CAST(igm.item_grp_code AS CHAR) AS item_group_code_display,
    CAST(igm.item_grp_name AS CHAR) AS item_group_display
  FROM item_grp_mst igm
  WHERE igm.item_grp_id = :item_grp_id  -- Replace this with your desired item_grp_id
  UNION ALL
  -- Walk upward to parent, prepend name and code
  SELECT 
    parent.item_grp_id,
    parent.item_grp_code,
    parent.item_grp_name,
    parent.parent_grp_id,
    CONCAT(parent.item_grp_code, '-', child.item_group_code_display),
    CONCAT(parent.item_grp_name, '-', child.item_group_display)
  FROM item_grp_mst parent
  JOIN item_group_path child ON child.parent_grp_id = parent.item_grp_id
)
-- Return only the final merged result
SELECT 
  :item_grp_id as item_grp_id,
  item_group_code_display,
  item_group_display
FROM item_group_path
ORDER BY LENGTH(item_group_display) DESC
LIMIT 1;"""
    sql = sql.replace(":item_grp_id", str(item_grp_id))
    query = text(sql)
    return query



def get_item_uom_mapping(item_id: int):
    sql = """
SELECT 
  uimm.map_from_id, um.uom_name as map_from_name,
  uimm.map_to_id , um2.uom_name as map_to_name,
uimm.is_fixed, 
uimm.relation_value , 
uimm.rounding  
from uom_item_map_mst uimm 
left join uom_mst um  on um.uom_id = uimm.map_from_id
left join uom_mst um2 on um2.uom_id = uimm.map_to_id
where uimm.item_id = :item_id;"""
    query = text(sql)
    return query




def get_item_minmax_mapping(item_id: int, co_id: int):
    sql = """
SELECT 
  bm.branch_id ,
  bm.branch_name,
  imm.minqty, 
  imm.maxqty, 
  imm.min_order_qty, 
  imm.lead_time
FROM branch_mst bm
LEFT JOIN item_minmax_mst imm 
  ON bm.branch_id = imm.branch_id 
  AND imm.item_id = :item_id
  AND imm.active = 1
WHERE bm.co_id = :co_id;"""
    query = text(sql)
    return query


def get_uom_list():
    sql = """
SELECT um.uom_id, um.uom_name
FROM uom_mst um
WHERE um.active = 1;
"""
    query = text(sql)
    return query

def get_item_make(co_id: int):
    sql = """
WITH RECURSIVE item_group_hierarchy AS (
  -- Anchor: top-level groups
  SELECT 
    igm.item_grp_id,
    igm.item_grp_code,
    igm.item_grp_name,
    igm.parent_grp_id,
    igm.co_id,
    CAST(igm.item_grp_code AS CHAR) AS item_group_code_display,
    CAST(igm.item_grp_name AS CHAR) AS item_group_display,
    1 AS level
  FROM item_grp_mst igm
  WHERE igm.parent_grp_id IS NULL AND igm.co_id = 1
  UNION ALL
  -- Recursive part
  SELECT 
    child.item_grp_id,
    child.item_grp_code,
    child.item_grp_name,
    child.parent_grp_id,
    child.co_id,
    CONCAT(parent.item_group_code_display, '-', child.item_grp_code),
    CONCAT(parent.item_group_display, '-', child.item_grp_name),
    parent.level + 1
  FROM item_grp_mst child
  JOIN item_group_hierarchy parent ON child.parent_grp_id = parent.item_grp_id
  WHERE child.co_id = :co_id AND child.co_id = parent.co_id
)
SELECT 
  im.item_make_id,
  im.item_make_name,
  im.item_grp_id,
  ig.item_group_display,
  ig.item_group_code_display
FROM item_make im
LEFT JOIN item_group_hierarchy ig ON ig.item_grp_id = im.item_grp_id
where (:search IS NULL OR
  ig.item_group_code_display LIKE :search OR
  ig.item_group_display LIKE :search
  OR im.item_make_name LIKE :search);"""
    query = text(sql)
    return query

  
  
def get_dept_master(co_id: int = None, branch_ids: list = None):
  print("Getting department master for co_id:", co_id, "branch_ids:", branch_ids)
  sql = """
  SELECT 
    dm.dept_id AS id,
    dm.dept_id AS dept_master_id,
    dm.dept_code,
    dm.dept_desc AS dept_name,
    dm.order_id,
    dm.Worker_staff AS worker_staff,
    1 AS active,
    bm.branch_name AS branch_display,
    dm.branch_id
  FROM dept_mst dm
  JOIN branch_mst bm ON dm.branch_id = bm.branch_id
  WHERE (:search IS NULL OR dm.dept_code LIKE :search OR dm.dept_desc LIKE :search)
    {branch_filter}
  ORDER BY dm.order_id IS NULL, dm.order_id, dm.dept_desc
  """
  branch_filter = ""

  if branch_ids:
    # use an expanding bind placeholder without surrounding parentheses
    # SQLAlchemy will expand the Python list into the proper comma-separated placeholder list
    branch_filter = "AND dm.branch_id IN :branch_ids"

  sql = sql.format(branch_filter=branch_filter)
  #print("Generated SQL:", sql )
  query = text(sql)

  # if branch_ids will be used, attach an expanding bind so SQLAlchemy expands the Python list
  if branch_ids:
    query = query.bindparams(bindparam("branch_ids", expanding=True))

  return query



def dept_master_validate_table(co_id: int = None, branch_ids: int = None):
  sql = """
  SELECT 
    dm.dept_id AS id,
    dm.dept_id AS dept_master_id,
    dm.dept_code,
    dm.dept_desc AS dept_name,
    1 AS active,
  FROM dept_mst dm
  WHERE 1=1
    {branch_filter}
  """
  branch_filter = ""

  if branch_ids:
    # use an expanding bind placeholder without surrounding parentheses
    # SQLAlchemy will expand the Python list into the proper comma-separated placeholder list
    branch_filter = "AND dm.branch_id IN :branch_ids"

  sql = sql.format(branch_filter=branch_filter)
  #print("Generated SQL:", sql )
  query = text(sql)

  # if branch_ids will be used, attach an expanding bind so SQLAlchemy expands the Python list
  if branch_ids:
    query = query.bindparams(bindparam("branch_ids", expanding=True))

  return query




def dept_master_create_setup( branch_ids: list = None):
  print("Getting branch master for co_id:",  "branch_ids:", branch_ids)
  sql = """
  SELECT 
  bm.branch_id,bm.branch_name
  FROM  branch_mst bm 
  WHERE bm.branch_id IN :branch_ids
  """
  branch_filter = ""

  #if branch_ids:
    # use an expanding bind placeholder without surrounding parentheses
    # SQLAlchemy will expand the Python list into the proper comma-separated placeholder list
    #branch_filter = "AND bm.branch_id IN :branch_ids"

  #sql = sql.format(branch_filter=branch_filter)
  #print("Generated SQL:", sql )
  query = text(sql)

  # if branch_ids will be used, attach an expanding bind so SQLAlchemy expands the Python list
  if branch_ids:
    query = query.bindparams(bindparam("branch_ids", expanding=True))

  return query


#type SubDeptRow = { id?: string | number; subdept_code?: string; subdept_name?: string; dept_name?: string; branch_display?: string; active?: number | boolean | string; order_by?: number | string };

def get_subdept_master(co_id: int = None, branch_ids: list = None):
  print("Getting sub-department master for co_id:", co_id, "branch_ids:", branch_ids)
  sql = """
  select sdm.sub_dept_id id,sdm.sub_dept_code subdept_code,sdm.sub_dept_desc subdept_name,dm.dept_desc dept_name,
  bm.branch_name branch_display,1 active,dm.dept_id,bm.branch_id,sdm.order_no order_by  from sub_dept_mst sdm 
  left join dept_mst dm on dm.dept_id =sdm.dept_id
  left join branch_mst bm on bm.branch_id =dm.branch_id
  WHERE (:search IS NULL OR dm.dept_code LIKE :search OR dm.dept_desc LIKE :search)
    {branch_filter}
  ORDER BY sdm.order_no IS NULL, sdm.order_no, sdm.sub_dept_desc
  """
  branch_filter = ""

  if branch_ids:
    # use an expanding bind placeholder without surrounding parentheses
    # SQLAlchemy will expand the Python list into the proper comma-separated placeholder list
    branch_filter = "AND dm.branch_id IN :branch_ids"

  sql = sql.format(branch_filter=branch_filter)
  #print("Generated SQL:", sql )
  query = text(sql)

  # if branch_ids will be used, attach an expanding bind so SQLAlchemy expands the Python list
  if branch_ids:
    query = query.bindparams(bindparam("branch_ids", expanding=True))

  return query




def get_branch_list(co_id: int = None, branch_ids: list = None):
    sql = """
    SELECT bm.branch_id, bm.branch_name, bm.branch_address1, bm.branch_address2,
           bm.branch_zipcode, bm.state_id, sm.state_code, sm.state AS state_name,
           bm.gst_no, bm.contact_no
    FROM branch_mst bm
    LEFT JOIN state_mst sm ON sm.state_id = bm.state_id
    WHERE 1=1
    """
    filters = []
    print('branch ids', branch_ids,'co id', co_id)
    if co_id:
        filters.append("AND bm.co_id = :co_id")
    if branch_ids:
        filters.append("AND bm.branch_id IN :branch_ids")
    
    sql += "\n  ".join(filters)
    q = text(sql)
    
    if branch_ids:
        q = q.bindparams(bindparam("branch_ids", expanding=True))
    
    return q

def get_dept_list( branch_ids: list = None):
    sql = """
    SELECT dm.dept_id AS dept_id, dm.dept_desc AS dept_name, dm.branch_id
    FROM dept_mst dm
    WHERE 1=1
      {branch_filter}
    """
    branch_filter = "AND dm.branch_id IN :branch_ids" if branch_ids else ""
    sql = sql.format( branch_filter=branch_filter)
    q = text(sql)
    if branch_ids:
        q = q.bindparams(bindparam("branch_ids", expanding=True))
    return q

# ...existing code...
def get_mechine_type_list():
    sql = """
    SELECT mm.machine_type_id AS id, mm.machine_type_name AS mechine_type, mm.active
    FROM machine_type_mst mm
    WHERE mm.active=1
    """
    sql = sql
    q = text(sql)
    return q


def get_proj_party_list(co_id: int = None, branch_ids: list = None):
    # base SQL (no Python-format placeholders)
    sql = """
    SELECT party_id, supp_name party_name
    FROM party_mst pm
    WHERE FIND_IN_SET("2", REPLACE(REPLACE(party_type_id, "{", ""), "}", "")) > 0
    """
    # append branch filter if provided (use SQLAlchemy bind :branch_ids)
    if branch_ids:
        sql += "\n  AND pm.branch_id IN :branch_ids"

    query = text(sql)

    # attach expanding bind only when branch_ids is a list
    if branch_ids:
        query = query.bindparams(bindparam("branch_ids", expanding=True))

    return query



def get_mechine_type_master_query():
  print("Getting machine type master query")
  sql = """
  select mtm.machine_type_id id, mtm.machine_type_name mechine_type, active
  from machine_type_mst mtm
  WHERE (:search IS NULL OR mtm.machine_type_name LIKE :search )
  """
  query = text(sql)
  return query



def get_mechine_master(co_id: int = None, branch_ids: list = None):
  print("Getting machine master for co_id:", co_id, "branch_ids:", branch_ids)
  sql = """
  select mm.machine_id id,
         mm.mech_code mechine_code,
         mm.machine_name mechine_name,
         mm.machine_type_id,
         mtm.machine_type_name mechine_type_name,
         mm.dept_id,
         dm.dept_desc dept_name,
         bm.branch_id,
         bm.branch_name branch_display,
         mm.remarks,
         mm.active,
         mm.mech_posting_code,
         mm.mech_shr_code,
         mm.line_no,
         mm.no_of_mechines
  from machine_mst mm 
  left join machine_type_mst mtm on mm.machine_type_id = mtm.machine_type_id  
  left join dept_mst dm on dm.dept_id = mm.dept_id 
  left join branch_mst bm on bm.branch_id = dm.branch_id
  WHERE (
    :search IS NULL OR
    mm.mech_code LIKE :search OR
    mm.machine_name LIKE :search OR
    mtm.machine_type_name LIKE :search OR
    dm.dept_code LIKE :search OR
    dm.dept_desc LIKE :search OR
    bm.branch_name LIKE :search
  )
    {branch_filter}
  """
 
  branch_filter = ""

  if branch_ids:
    # use an expanding bind placeholder without surrounding parentheses
    # SQLAlchemy will expand the Python list into the proper comma-separated placeholder list
    branch_filter = "AND dm.branch_id IN :branch_ids"

  sql = sql.format(branch_filter=branch_filter)
  query = text(sql)

  # if branch_ids will be used, attach an expanding bind so SQLAlchemy expands the Python list
  if branch_ids:
    query = query.bindparams(bindparam("branch_ids", expanding=True))

  return query
  

def get_mechine_master_view(co_id: int = None, mechine_master_id = None):
    sql = """
    select mm.machine_id id,
           mm.mech_code mechine_code,
           mm.machine_name mechine_name,
           mm.machine_type_id,
           mtm.machine_type_name mechine_type_name,
           mm.dept_id,
           dm.dept_desc dept_name,
           bm.branch_id,
           bm.branch_name branch_display,
           mm.remarks,
           mm.active,
           mm.mech_posting_code,
           mm.mech_shr_code,
           mm.line_no,
           mm.no_of_mechines
    from machine_mst mm
    left join machine_type_mst mtm on mm.machine_type_id = mtm.machine_type_id
    left join dept_mst dm on dm.dept_id = mm.dept_id
    left join branch_mst bm on bm.branch_id = dm.branch_id
    WHERE 1=1
      {id_filter}
    """
    id_filter = ""
    if mechine_master_id is not None:
        # if a list/tuple, use IN with expanding bind; otherwise use simple equality
        if isinstance(mechine_master_id, (list, tuple)):
            id_filter = "AND mm.machine_id IN :mechine_master_id"
        else:
            id_filter = "AND mm.machine_id = :mechine_master_id"

    sql = sql.format(id_filter=id_filter)
    query = text(sql)
    return query
  
  
  
def get_project_master(co_id: int = None, branch_ids: list = None):
  print("Getting project master for co_id:", co_id, "branch_ids:", branch_ids)
  sql = """
  select pm.project_id id,pm.project_id, pm.prj_name,pm.prj_desc,pm.branch_id,bm.branch_name branch_display,pm.branch_id,bm.branch_name,pm.dept_id,dm.dept_desc dept_name,pm2.supp_name ,
  pm.prj_start_dt,pm.prj_end_dt ,  pm.status_id,sm.status_name,pm.active  from project_mst pm 
  left join branch_mst bm on pm.branch_id =bm.branch_id
  left join dept_mst dm on dm.dept_id =pm.dept_id
  left join status_mst sm on pm.status_id =sm.status_id
  left join party_mst pm2 on pm.party_id =pm2.party_id
  WHERE (:search IS NULL OR dm.dept_desc LIKE :search OR pm.prj_name LIKE :search)
    {branch_filter}
  """
  branch_filter = ""

  if branch_ids:
    # use an expanding bind placeholder without surrounding parentheses
    # SQLAlchemy will expand the Python list into the proper comma-separated placeholder list
    branch_filter = "AND pm.branch_id IN :branch_ids"

  sql = sql.format(branch_filter=branch_filter)
  #print("Generated SQL:", sql )
  query = text(sql)

  # if branch_ids will be used, attach an expanding bind so SQLAlchemy expands the Python list
  if branch_ids:
    query = query.bindparams(bindparam("branch_ids", expanding=True))

  return query



def get_party_table(co_id: int):
    sql = """
select 
pm.party_id , 
pm.active ,
pm.supp_code , 
pm.supp_name, 
pm.party_type_id , 
pm.supp_contact_person , 
pm.supp_email_id 
from party_mst pm
where pm.co_id = :co_id 
and (:search is NULL OR pm.supp_name LIKE :search OR pm.supp_code LIKE :search);
"""
    query = text(sql)
    return query

def get_party_types():
    sql = """
SELECT 
  ptm.party_types_mst_id,
  ptm.party_types_mst_name,
  ptm.module_id
FROM party_type_mst ptm;
"""
    query = text(sql)
    return query

def get_country_list():
    sql = """
SELECT 
  cm.country_id,
  cm.country
FROM country_mst cm;
"""
    query = text(sql)
    return query

def get_state_list():
    sql = """
SELECT 
  sm.state_id,
  sm.state,
  sm.country_id
FROM state_mst sm
"""
    query = text(sql)
    return query

def get_entity_list():
    sql = """
select etm.entity_type_id , etm.entity_type_name  from entity_type_mst etm ;
"""
    query = text(sql)
    return query

def get_party_by_id(party_id: int):
    sql = """
SELECT  
pm.party_id , 
pm.active , 
pm.supp_name ,
pm.supp_code ,
pm.phone_no,
pm.cin ,
pm.supp_contact_person ,
pm.supp_contact_designation ,
pm.supp_email_id ,
pm.party_pan_no , 
pm.entity_type_id ,
etm.entity_type_name ,
pm.msme_certified ,
pm.co_id ,
cm.country,
pm.party_type_id 
from party_mst pm 
left join country_mst cm on cm.country_id =pm.country_id 
left join entity_type_mst etm on etm.entity_type_id = pm.entity_type_id 
where pm.party_id = :party_id
; 
"""
    query = text(sql)
    return query

def get_party_branch_by_party_id(party_id: int):
    sql = """
SELECT
  pbm.active,
  pbm.party_mst_branch_id,
  pbm.gst_no,
  pbm.address,
  pbm.address_additional,
  pbm.zip_code,
  pbm.state_id,
  sm.state,
  pbm.contact_no,
  pbm.contact_person
FROM party_branch_mst pbm
LEFT JOIN state_mst sm ON sm.state_id = pbm.state_id
WHERE pbm.party_id = :party_id;
"""
    query = text(sql)
    return query

def get_warehouse_list(branch_ids: list = None):
    """Return warehouse hierarchy rows filtered by optional branch list and search."""
    branch_filter_anchor = "AND wm.branch_id IN :branch_ids" if branch_ids else ""
    branch_filter_recursive = "AND child.branch_id IN :branch_ids" if branch_ids else ""

    sql = """
WITH RECURSIVE warehouse_hierarchy AS (
  -- Anchor: Top-level warehouses across optional branch scope
  SELECT 
    wm.warehouse_id,
    wm.branch_id,
    wm.warehouse_name,
    wm.warehouse_type,
    wm.parent_warehouse_id,
    CAST(wm.warehouse_name AS CHAR) AS warehouse_path,
    1 AS level
  FROM warehouse_mst wm
  WHERE wm.parent_warehouse_id IS NULL
    {branch_filter_anchor}
  UNION ALL
  -- Recursive: bring in child warehouses within the same scope
  SELECT 
    child.warehouse_id,
    child.branch_id,
    child.warehouse_name,
    child.warehouse_type,
    child.parent_warehouse_id,
    CONCAT(parent.warehouse_path, '-', child.warehouse_name),
    parent.level + 1
  FROM warehouse_mst child
  JOIN warehouse_hierarchy parent 
    ON child.parent_warehouse_id = parent.warehouse_id
    {branch_filter_recursive}
)
SELECT 
  wh.warehouse_id,
  wh.branch_id,
  wh.warehouse_name,
  wh.warehouse_type,
  wh.parent_warehouse_id,
  wh.warehouse_path,
  wh.level,
  bm.branch_name
FROM warehouse_hierarchy wh
LEFT JOIN branch_mst bm ON bm.branch_id = wh.branch_id
WHERE (
  :search IS NULL OR
  wh.warehouse_path LIKE :search OR
  wh.warehouse_name LIKE :search OR
  wh.warehouse_type LIKE :search OR
  bm.branch_name LIKE :search
)
ORDER BY wh.branch_id, wh.warehouse_path;
"""

    sql = sql.format(
        branch_filter_anchor=branch_filter_anchor,
        branch_filter_recursive=branch_filter_recursive,
    )

    query = text(sql)
    if branch_ids:
        query = query.bindparams(bindparam("branch_ids", expanding=True))
    return query




def cost_factor_table(branch_ids: list):
    sql = """
SELECT 
cfm.branch_id,
cfm.cost_factor_id ,
cfm.dept_id ,
dm.dept_desc ,
cfm.cost_factor_name ,
cfm.cost_factor_desc 
from cost_factor_mst cfm 
left join dept_mst dm on dm.dept_id = cfm.dept_id 
where cfm.branch_id in :branch_ids 
and (:search is null or cfm.cost_factor_name LIKE :search);
"""
    query = text(sql).bindparams(bindparam('branch_ids', expanding=True))
    return query

def get_dept_list_by_branch_id(branch_ids: list):
    sql = """
SELECT 
  dm.dept_id,
  dm.dept_desc,
  dm.branch_id
FROM dept_mst dm
WHERE dm.branch_id IN :branch_ids;
"""
    query = text(sql).bindparams(bindparam('branch_ids', expanding=True))
    return query

def cost_factor_table_by_id(cost_factor_id: int):
    sql = """
SELECT 
cfm.branch_id,
bm.branch_name,
cfm.cost_factor_id ,
cfm.dept_id ,
dm.dept_desc ,
cfm.cost_factor_name ,
cfm.cost_factor_desc 
from cost_factor_mst cfm 
left join dept_mst dm on dm.dept_id = cfm.dept_id 
left join branch_mst bm on bm.branch_id = cfm.branch_id
where cfm.cost_factor_id = :cost_factor_id;
"""
    query = text(sql)
    return query


# =============================================================================
# YARN QUALITY MASTER QUERIES
# =============================================================================

def get_yarn_type_list(co_id: int = None):
    """Get list of yarn types from item_grp_mst where item_type_id=4.

    DEPRECATED for yarn quality: a yarn IS an item (item_mst, item_type_id=4); the
    yarn dropdown is now served by get_yarn_qualities_query (juteProduction). Kept for
    backward compatibility / legacy callers.
    """
    sql = """
    SELECT
      ig.item_grp_id,
      ig.item_grp_name,
      ig.item_grp_code
    FROM item_grp_mst ig
    WHERE ig.co_id = :co_id
      AND ig.item_type_id = 4
      AND ig.parent_grp_id IS NULL
    ORDER BY ig.item_grp_name
    """
    query = text(sql)
    return query


# =============================================================================
# ITEM BOM MASTER QUERIES
# =============================================================================

def get_bom_items_with_children(co_id: int = None):
    """List items that have at least one active BOM child (for the BOM index page).
    Returns lifecycle bom_status from item_bom_hdr_mst. Costing fields live on the
    separate BOM Costing page and are intentionally excluded here."""
    sql = """
    SELECT
      im.item_id,
      im.item_code,
      vip.full_item_code,
      im.item_name,
      bh.bom_hdr_id,
      bh.bom_status
    FROM item_mst im
    INNER JOIN item_bom ib ON ib.parent_item_id = im.item_id AND ib.co_id = :co_id AND ib.active = 1
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN item_bom_hdr_mst bh
        ON bh.item_id = im.item_id AND bh.co_id = :co_id AND bh.active = 1 AND bh.is_current = 1
    WHERE (:search IS NULL OR im.item_code LIKE :search OR im.item_name LIKE :search OR vip.full_item_code LIKE :search)
    GROUP BY im.item_id, im.item_code, vip.full_item_code, im.item_name, bh.bom_hdr_id, bh.bom_status
    ORDER BY im.item_code;
    """
    return text(sql)


def get_bom_children_query():
    """Get direct children of a parent item (one level, active only)."""
    sql = """
    SELECT
      ib.bom_id,
      ib.parent_item_id,
      ib.child_item_id,
      ib.additional_description,
      ib.qty,
      ib.uom_id,
      um.uom_name,
      ib.sequence_no,
      im.item_code AS child_item_code,
      vip.full_item_code AS child_full_item_code,
      im.item_name AS child_item_name,
      im.assembly AS child_is_assembly,
      EXISTS(
        SELECT 1 FROM item_bom ib2
        WHERE ib2.parent_item_id = ib.child_item_id
        AND ib2.co_id = :co_id AND ib2.active = 1
      ) AS has_children
    FROM item_bom ib
    INNER JOIN item_mst im ON im.item_id = ib.child_item_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = ib.child_item_id
    LEFT JOIN uom_mst um ON um.uom_id = ib.uom_id
    WHERE ib.parent_item_id = :parent_item_id
      AND ib.co_id = :co_id
      AND ib.active = 1
    ORDER BY ib.sequence_no, ib.bom_id;
    """
    return text(sql)


def get_full_bom_tree_query():
    """Walk full BOM subtree from a root item in one recursive CTE.

    Returns flat rows ordered by depth + parent + sequence so the caller can
    assemble a tree in a single pass without N+1 queries. Depth capped at 15.
    """
    sql = """
    WITH RECURSIVE bom_cte AS (
      SELECT ib.bom_id, ib.parent_item_id, ib.child_item_id, ib.additional_description,
             ib.qty, ib.uom_id, ib.sequence_no, 1 AS depth
      FROM item_bom ib
      WHERE ib.parent_item_id = :root_item_id
        AND ib.co_id = :co_id
        AND ib.active = 1
      UNION ALL
      SELECT ib.bom_id, ib.parent_item_id, ib.child_item_id, ib.additional_description,
             ib.qty, ib.uom_id, ib.sequence_no, b.depth + 1
      FROM item_bom ib
      INNER JOIN bom_cte b ON ib.parent_item_id = b.child_item_id
      WHERE ib.co_id = :co_id
        AND ib.active = 1
        AND b.depth < 15
    )
    SELECT
      b.bom_id,
      b.parent_item_id,
      b.child_item_id,
      b.additional_description,
      b.qty,
      b.uom_id,
      um.uom_name,
      b.sequence_no,
      im.item_code AS child_item_code,
      vip.full_item_code AS child_full_item_code,
      im.item_name AS child_item_name,
      im.assembly AS child_is_assembly,
      b.depth
    FROM bom_cte b
    INNER JOIN item_mst im ON im.item_id = b.child_item_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = b.child_item_id
    LEFT JOIN uom_mst um ON um.uom_id = b.uom_id
    ORDER BY b.depth, b.parent_item_id, b.sequence_no, b.bom_id;
    """
    return text(sql)


def get_bom_node_by_id_query():
    """Fetch a single enriched BOM node row — used after add to return the
    full node payload for FE optimistic splice."""
    sql = """
    SELECT
      ib.bom_id,
      ib.parent_item_id,
      ib.child_item_id,
      ib.additional_description,
      ib.qty,
      ib.uom_id,
      um.uom_name,
      ib.sequence_no,
      im.item_code AS child_item_code,
      vip.full_item_code AS child_full_item_code,
      im.item_name AS child_item_name,
      im.assembly AS child_is_assembly
    FROM item_bom ib
    INNER JOIN item_mst im ON im.item_id = ib.child_item_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = ib.child_item_id
    LEFT JOIN uom_mst um ON um.uom_id = ib.uom_id
    WHERE ib.bom_id = :bom_id
      AND ib.co_id = :co_id;
    """
    return text(sql)


def get_bom_parents_query():
    """Where-used: get all parent assemblies that contain a given child item."""
    sql = """
    SELECT
      ib.bom_id,
      ib.parent_item_id,
      im.item_code AS parent_item_code,
      vip.full_item_code AS parent_full_item_code,
      im.item_name AS parent_item_name,
      ib.qty,
      ib.uom_id,
      um.uom_name
    FROM item_bom ib
    INNER JOIN item_mst im ON im.item_id = ib.parent_item_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = ib.parent_item_id
    LEFT JOIN uom_mst um ON um.uom_id = ib.uom_id
    WHERE ib.child_item_id = :child_item_id
      AND ib.co_id = :co_id
      AND ib.active = 1
    ORDER BY im.item_code;
    """
    return text(sql)


def get_items_for_bom_dropdown(search: str | None = None):
    """Get items list for BOM component selection dropdown."""
    search_clause = ""
    if search:
        search_clause = (
            "AND (im.item_code LIKE :search "
            "OR im.item_name LIKE :search "
            "OR vip.full_item_code LIKE :search)"
        )
    sql = f"""
    SELECT
      im.item_id,
      im.item_code,
      MIN(vip.full_item_code) AS full_item_code,
      im.item_name,
      im.uom_id,
      um.uom_name
    FROM item_mst im
    LEFT JOIN uom_mst um ON um.uom_id = im.uom_id
    LEFT JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    WHERE ig.co_id = :co_id
      AND im.active = 1
      {search_clause}
    GROUP BY im.item_id, im.item_code, im.item_name, im.uom_id, um.uom_name
    ORDER BY COALESCE(MIN(vip.full_item_code), im.item_code)
    LIMIT 200;
    """
    return text(sql)


def get_bom_uom_list():
    """Get active UOM list for BOM dropdowns."""
    sql = """
    SELECT uom_id, uom_name
    FROM uom_mst
    WHERE active = 1
    ORDER BY uom_name;
    """
    return text(sql)


def get_item_search_list_query():
    """
    Get paginated searchable item list for item selection dialog.
    Returns items with their group hierarchy path, default UOM, HSN code, and tax info.
    Used by procurement and sales modules for item selection.
    """
    sql = """SELECT
        im.item_id,
        im.item_grp_id,
        vip.item_group_code_display AS item_grp_code,
        vip.item_group_name_display AS item_grp_name,
        im.item_code,
        vip.full_item_code,
        im.item_name,
        im.uom_id,
        um.uom_name,
        im.hsn_code,
        im.tax_percentage,
        im.purchaseable,
        im.saleable
    FROM item_mst AS im
    INNER JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN uom_mst AS um ON um.uom_id = im.uom_id
    WHERE vip.co_id = :co_id
        AND im.active = 1
        AND (
            :search_like IS NULL
            OR im.item_code LIKE :search_like
            OR im.item_name LIKE :search_like
            OR vip.item_group_code_display LIKE :search_like
            OR vip.item_group_name_display LIKE :search_like
            OR vip.full_item_code LIKE :search_like
            OR im.hsn_code LIKE :search_like
        )
    ORDER BY vip.item_group_code_display ASC, im.item_code ASC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_item_search_count_query():
    """
    Get total count for paginated item search.
    """
    sql = """SELECT COUNT(1) AS total
    FROM item_mst AS im
    INNER JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    WHERE vip.co_id = :co_id
        AND im.active = 1
        AND (
            :search_like IS NULL
            OR im.item_code LIKE :search_like
            OR im.item_name LIKE :search_like
            OR vip.item_group_code_display LIKE :search_like
            OR vip.item_group_name_display LIKE :search_like
            OR vip.full_item_code LIKE :search_like
            OR im.hsn_code LIKE :search_like
        );"""
    return text(sql)


def get_item_makes_by_group_ids_query():
    """
    Get item makes for a set of item group IDs.
    Used after item selection to populate make options.
    """
    sql = """SELECT
        imk.item_make_id,
        imk.item_make_name,
        imk.item_grp_id
    FROM item_make AS imk
    WHERE imk.item_grp_id IN :item_grp_ids
    ORDER BY imk.item_make_name;"""
    return text(sql).bindparams(bindparam("item_grp_ids", expanding=True))


def get_item_uoms_by_item_ids_query():
    """
    Get UOM mappings for a set of item IDs.
    Used after item selection to populate UOM options.
    """
    sql = """SELECT
        uimm.item_id,
        uimm.map_from_id,
        um_from.uom_name AS map_from_name,
        uimm.map_to_id,
        um_to.uom_name AS uom_name,
        uimm.relation_value,
        uimm.rounding
    FROM uom_item_map_mst AS uimm
    INNER JOIN item_mst AS im ON im.item_id = uimm.item_id
    LEFT JOIN uom_mst AS um_to ON um_to.uom_id = uimm.map_to_id
    LEFT JOIN uom_mst AS um_from ON um_from.uom_id = uimm.map_from_id
    WHERE uimm.item_id IN :item_ids
        AND im.active = 1
    ORDER BY uimm.item_id, um_to.uom_name;"""
    return text(sql).bindparams(bindparam("item_ids", expanding=True))

