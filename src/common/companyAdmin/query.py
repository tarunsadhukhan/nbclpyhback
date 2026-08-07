from sqlalchemy.sql import text
from sqlalchemy.sql import bindparam
from sqlalchemy.sql.elements import TextClause

def get_co_all_query(search: str = None, limit: int = None, offset: int = None):
    sql = f"""select cm.co_id, cm.co_name, cm.co_prefix,  cm.co_email_id 
from co_mst cm
    WHERE (:search IS NULL OR 
             cm.co_name LIKE :search OR
             cm.co_prefix LIKE :search OR
             cm.co_email_id LIKE :search) 
        ORDER BY cm.co_id
        LIMIT :limit OFFSET :offset;"""
    query = text(sql)
    return query

def get_co_all_count_query(search: str = None):
    sql = f"""select count(*) as total from co_mst cm 
    where 
    (:search IS NULL OR 
                    cm.co_name LIKE :search OR 
                    cm.co_prefix LIKE :search OR 
                    cm.co_email_id LIKE :search
                      ) 
                      ;"""
    query = text(sql)
    return query

def get_co_by_id_query(co_id: int):
    sql = f"""select cm.co_id, cm.co_name, cm.co_prefix, cm.co_address1 , cm.co_address2, cm.co_zipcode ,
cm.country_id, cm.state_id, sm.state as state_name, cm.co_cin_no, cm.co_email_id , cm.co_pan_no , cm.alert_email_id
from co_mst cm
    left join state_mst sm on sm.state_id = cm.state_id
    WHERE cm.co_id = :co_id;"""
    query = text(sql)
    return query

def get_country_query():
    sql = f"""select cm.country_id, cm.country from country_mst cm;"""
    query = text(sql)
    return query

def get_state_query():
    sql = f"""select sm.state_id, sm.state, sm.country_id from state_mst sm;"""
    query = text(sql)
    return query



def get_department_all_query(search: str = None, limit: int = None, offset: int = None):
    sql = f"""select dept_id,dept_desc,order_id,dm.dept_code,dm.branch_id,bm.branch_name,bm.co_id,cm.co_name  
    from dept_mst dm 
			left join branch_mst bm on dm.branch_id =bm.branch_id
			left join co_mst cm on cm.co_id =bm.co_id
    WHERE (:search IS NULL OR 
             dm.dept_desc LIKE :search )
        ORDER BY dm.dept_desc
        LIMIT :limit OFFSET :offset;"""
    query = text(sql)
    return query

def get_department_all_count_query(search: str = None):
    sql = f"""select count(*) as total from dept_mst dm left join branch_mst bm on bm.branch_id = dm.branch_id
    where (:search IS NULL OR 
                    dm.dept_desc LIKE :search ) 
                      ;"""
    query = text(sql)
    return query


def get_subdepartment_all_query(search: str = None, limit: int = None, offset: int = None):
    sql = f"""select sdm.sub_dept_id,sdm.sub_dept_code,sdm.sub_dept_desc,sdm.dept_id,dept_desc,order_no,dm.dept_code,
			dm.branch_id,bm.branch_name,bm.co_id,cm.co_name  
    from sub_dept_mst sdm
    left join dept_mst dm on sdm.dept_id=dm.dept_id
			left join branch_mst bm on dm.branch_id =bm.branch_id
			left join co_mst cm on cm.co_id =bm.co_id
    WHERE (:search IS NULL OR 
             sdm.sub_dept_desc LIKE :search )
        ORDER BY sdm.sub_dept_desc
        LIMIT :limit OFFSET :offset;"""
    query = text(sql)
    return query

def get_subdepartment_all_count_query(search: str = None):
    sql = f"""select count(*) as total from sub_dept_mst sdm
left join dept_mst dm on sdm.dept_id =dm.dept_id 
left join branch_mst bm on bm.branch_id = dm.branch_id
    where (:search IS NULL OR 
                    sdm.sub_dept_desc LIKE :search ) 
                      ;"""
    query = text(sql)
    return query



def get_branch_all_query(search: str = None):
    sql = f"""select bm.co_id as co_id, cm.co_name as co_name , bm.branch_id, bm.branch_name , bm.active
from branch_mst bm left join co_mst cm on cm.co_id = bm.co_id
    WHERE (:search IS NULL OR
             bm.branch_name LIKE :search OR
             co_name LIKE :search)
        ORDER BY bm.branch_id;"""
    query = text(sql)
    return query


def get_branch_by_id_query(branch_id: int):
    sql = f"""select bm.branch_id, 
bm.branch_name, 
bm.branch_prefix,
bm.branch_address1 , 
bm.branch_address2 , 
bm.branch_zipcode, 
bm.country_id , 
bm.state_id, 
bm.gst_no, 
bm.contact_no , 
bm.contact_person, 
bm.branch_email, 
bm.active, 
bm.gst_verified
from branch_mst bm
    WHERE bm.branch_id = :branch_id;"""
    query = text(sql)
    return query



def get_co_all_query_nosearch():
    sql = f"""select cm.co_id , cm.co_name from co_mst cm 
        """
    query = text(sql)
    return query

def get_branch_query_nosearch():
    sql = f"""select bm.branch_id, bm.branch_name, bm.co_id from branch_mst bm
    """
    query = text(sql)
    return query


def get_department_by_id_query(dept_id: int):
    sql = f"""select dm.*,bm.co_id from dept_mst dm 
left join branch_mst bm on dm.branch_id =bm.branch_id
    WHERE dm.dept_id = :dept_id;"""
    query = text(sql)
    return query

def get_co_config_by_id_query(co_id: int):
    sql = f"""select co_id ,
    currency_id ,
    india_gst ,
    india_tds ,
    india_tcs,
    back_date_allowable,
    indent_required,
    po_required ,
    material_inspection,
    quotation_required,
    do_required ,
    gst_linked  from co_config cc where co_id= :co_id ;"""
    query = text(sql)
    return query