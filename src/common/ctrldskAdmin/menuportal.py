#from fastapi import Depends, Request, HTTPException, APIRouter, Query,path
import select
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, Path
from typing import List, Optional
from sqlalchemy.sql import text
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlmodel import insert
from src.config.db import get_db_names, default_engine
from src.authorization.utils import verify_access_token
from src.common.ctrldskAdmin.schemas  import MenuResponse, PortalMenuMstSchema
from src.common.ctrldskAdmin.models import PortalMenuMst 
from src.common.ctrldskAdmin.query import get_portal_menu_details 
from src.common.ctrldskAdmin.query import portal_parentmenudetails as get_portal_parentmenudetails, portalmodulename
from src.common.ctrldskAdmin.query import  portalmenutypedetails, get_portalmenuname_by_name,get_menu_by_id_query,orgmodulename 
from .models import ConOrgMaster, ConModuleMasters
import json

router = APIRouter()


@router.get("/portal_menu_details")
def portal_menu_details(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1),
    search: Optional[str] = None,
):
    print("Starting roles_tenant_admin endpointssss")
    query = get_portal_menu_details(search)
    #print(f"  after query Query: {query}")

    try:
        with Session(default_engine) as session:
            offset = (page - 1) * limit

            query = get_portal_menu_details(search)
            #print(f"Executing query for org_id:  search: {search} {query}")
            roles = session.execute(query, {"limit": limit, "offset": offset, "search": f"%{search}%" if search else None}).fetchall()
            print(f"Query returned {len(roles) if roles else 0} results")
    except Exception as query_error:
        print(f"Query execution error: {query_error}")
        raise HTTPException(status_code=500, detail=f"Query execution error: {str(query_error)}")

    try:
        roles = [dict(r._mapping) for r in roles]
        print(f"Converted {len(roles)} rows to dictionaries")
        total = len(roles)
    except Exception as conversion_error:
        print(f"Data conversion error: {conversion_error}")
        raise HTTPException(status_code=500, detail=f"Data conversion error: {str(conversion_error)}")

    response = []
    for row in roles:
        response.append({
            "menu_id": row.get("menu_id"),
            "menu_name": row.get("menu_name"),
            "parent_id": row.get("parent_id"),
            "parent_name": row.get("parent_name"),
            "active": row.get("active"),
            "module_id": row.get("module_id"),
            "module_name": row.get("con_module_name"),
            "tooltip": {
                "menu_path": row.get("menu_path"),
                "menu_icon": row.get("menu_icon")
            }
        })

    return {"data": response, "total": total}


@router.get("/portal_parentmenudetails")
def portal_parentmenudetails():
    print("Starting roles_parent menu endpoint")

    try:
        with Session(default_engine) as session:
            # Use the imported function to get the SQL query
            query = get_portal_parentmenudetails(moduleId=0)

            #print(f"Executing query: {query}")
            roles = session.execute(query).fetchall()
            #print(f"Query returned {len(roles) if roles else 0} results")
    except Exception as query_error:
        print(f"Query execution error: {query_error}")
        raise HTTPException(status_code=500, detail=f"Query execution error: {str(query_error)}")

    try:
        roles = [dict(r._mapping) for r in roles]
        #print(f"Converted {len(roles)} rows to dictionaries")
    except Exception as conversion_error:
        print(f"Data conversion error: {conversion_error}")
        raise HTTPException(status_code=500, detail=f"Data conversion error: {str(conversion_error)}")

    response = []
    for row in roles:
        response.append({
            "pmenu_id": row.get("menu_id"),
            "pmenu_name": row.get("menu_name"),
            "pmodule_id": row.get("module_id"),
        })

    return response


@router.get("/portalmodulename")
def portal_parentmenudetails():
    print("Starting roles_parent menu endpoint")

    try:
        with Session(default_engine) as session:
            # Use the imported function to get the SQL query
            query = portalmodulename()

            #print(f"Executing query: {query}")
            roles = session.execute(query).fetchall()
            print(f"Query returned {len(roles) if roles else 0} results")
    except Exception as query_error:
        print(f"Query execution error: {query_error}")
        raise HTTPException(status_code=500, detail=f"Query execution error: {str(query_error)}")

    try:
        roles = [dict(r._mapping) for r in roles]
        print(f"Converted {len(roles)} rows to dictionaries")
    except Exception as conversion_error:
        print(f"Data conversion error: {conversion_error}")
        raise HTTPException(status_code=500, detail=f"Data conversion error: {str(conversion_error)}")

    response = []
    for row in roles:
        response.append({
            "module_id": row.get("con_module_id"),
            "module_name": row.get("con_module_name")
        })

    return response

@router.get("/portalmenutypedetails")
def portalmenutypedet():
    print("Starting roles_parent menu endpoint")

    try:
        with Session(default_engine) as session:
            # Use the imported function to get the SQL query
            query = portalmenutypedetails()

            #print(f"Executing query: {query}")
            roles = session.execute(query).fetchall()
            #print(f"Query returned {len(roles) if roles else 0} results")
    except Exception as query_error:
        print(f"Query execution error: {query_error}")
        raise HTTPException(status_code=500, detail=f"Query execution error: {str(query_error)}")

    try:
        roles = [dict(r._mapping) for r in roles]
        print(f"Converted {len(roles)} rows to dictionaries")
    except Exception as conversion_error:
        print(f"Data conversion error: {conversion_error}")
        raise HTTPException(status_code=500, detail=f"Data conversion error: {str(conversion_error)}")

    response = []
    for row in roles:
        response.append({
            "menu_type_id": row.get("menu_type_id"),
            "menu_type": row.get("menu_type")
        })

    return response


@router.get("/portal_allmenu_details")
def create_portal_allmenu_details(
    # org_id: int,
#    token_data: dict = Depends(verify_access_token),
#    db: Session = Depends(get_tenant_db),
):
    try:
        with Session(default_engine) as session:
            print("Starting fetch_portalmenuname_by_id endpoint")

            modules   = session.execute(portalmodulename()).fetchall()
            print(f"Query returned {len(modules) if modules else 0} results")
            moduleId=0
            parentnams = session.execute(get_portal_parentmenudetails()).fetchall()
            # print(f"Query returned {len(parentnams) if parentnams else 0} results")
            menutypes  = session.execute(portalmenutypedetails()).fetchall()
            # print(f"Query returned {len(menutypes) if menutypes else 0} results")
            return {
                "allModules":       [dict(c._mapping) for c in modules],
                "allparentnames":   [dict(s._mapping) for s in parentnams],
                "menutypes":       [dict(ct._mapping) for ct in menutypes],
            }
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in allmenu_data_by_id: {exc}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/portal_allmenu_details_by_id/{co_id}")
def portal_allmenu_details_by_id(
    co_id: int,
    # org_id: int,
#    token_data: dict = Depends(verify_access_token),
#    db: Session = Depends(get_tenant_db),
):
    try:
        with Session(default_engine) as session:
            print("Starting fetch_portalmenuname_by_id endpoint")

            query = get_menu_by_id_query(co_id)
            menu_details = session.execute(query, {"co_id": co_id}).fetchone()
            moduleId= menu_details.module_id

            modules   = session.execute(portalmodulename()).fetchall()
            print(f"Query returned {len(modules) if modules else 0} results")
            query=get_portal_parentmenudetails()
            parentnams = session.execute(query).fetchall()
            # print(f"Query returned {len(parentnams) if parentnams else 0} results")
            menutypes  = session.execute(portalmenutypedetails()).fetchall()
            # print(f"Query returned {len(menutypes) if menutypes else 0} results")
            return {
                "data": dict(menu_details._mapping),
                "allModules":       [dict(c._mapping) for c in modules],
                "allparentnames":   [dict(s._mapping) for s in parentnams],
                "menutypes":       [dict(ct._mapping) for ct in menutypes],
            }
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in allmenu_data_by_id: {exc}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")



@router.get("/portalmenuname/{name}/{menu_id}")
def fetch_portalmenuname_by_id(
    name: str,
    menu_id: int,
):
    print(f"Starting fetch_portalmenuname_by_id endpoint with name: {name},{menu_id}")

    try:
        with Session(default_engine) as session:
            # Execute the query with the provided name parameter
            query = get_portalmenuname_by_name(name,menu_id)
            print(f"Executing query: {query}")
            if menu_id == 0:
                result = session.execute(query, {"name": name}).fetchone()
            else:
                result = session.execute(query, {"name": name, "menu_id": menu_id}).fetchone()
            # print(f"Query returned: {result}")

            # Check if the result is None
            if not result:
                return {"data": {"isDuplicate": False}, "count": 0}

            # Convert the result to a dictionary
            response = dict(result._mapping)

            # Determine if the menu name is a duplicate
            is_duplicate = response.get("count", 0) > 0

            return {"data": {"isDuplicate": is_duplicate}}

    except Exception as query_error:
        print(f"Query execution error: {query_error}")
        raise HTTPException(status_code=500, detail=f"Query execution error: {str(query_error)}")



@router.post("/portalmenucreate")
def create_portalmenucreate_data(
    request: Request,
    payload: PortalMenuMstSchema,
    token_data: dict = Depends(verify_access_token),
):
    print("Starting create_portalmenucreate_data endpoint",request)
    print(f"Starting create_portalmenucreate_data endpoint with payload: {payload}")

    """
    Insert a new portal menu record using the ORM model and return its id.
    """
    try:
        with Session(default_engine) as session:
            # Create a new portal menu entry
            new_menu = PortalMenuMst(
                menu_name=payload.menu_name,
                menu_path=payload.menu_path,
                active=payload.active,
                menu_parent_id=payload.menu_parent_id,
                menu_type_id=payload.menu_type_id,
                menu_icon=payload.menu_icon,
                module_id=payload.module_id,
                order_by=payload.order_by,
            )

            session.add(new_menu)
            session.flush()  # Get the ID without committing
            session.commit()


            # Fetch the latest menu
            menusql="""select * from vowconsole3.portal_menu_mst pmm order by pmm.menu_id desc limit 1"""
            menusql = text(menusql)
            with Session(default_engine) as session:
                result = session.execute(menusql).fetchone()
                if result:
                    print(f"Latest menu: {result}")
                    # You can access the latest menu details from the result
                    latest_menu_id = result.menu_id
                    latest_menu_name = result.menu_name
                    # Do something with the latest menu details

            # Fetch all org shortnames with status = 3
            orgsql = """
                select com.con_org_shortname  
                from vowconsole3.con_org_master com 
                where com.con_org_master_status = 3 and com.con_org_shortname="sls"
            """
            print(f"Executing orgsql: {orgsql}")
            orgsql = text(orgsql)
            orgs = session.execute(orgsql).fetchall()
            print(f"Fetched {len(orgs) if orgs else 0} organizations", [org.con_org_shortname for org in orgs])
            if orgs:
                for org in orgs:
                    orgshname = org.con_org_shortname
                    # Prepare the insert SQL for each org
                    menuinssql = f"""
                        insert into {orgshname}.menu_mst 
                        (menu_id, menu_name, menu_path, active, 
                        menu_parent_id, menu_type_id, menu_icon, module_mst_id,order_by)
                        select 
                            menu_id, menu_name, menu_path, active, 
                            menu_parent_id, menu_type_id, menu_icon,
                            module_id,order_by
                        from vowconsole3.portal_menu_mst 
                        where menu_id = {latest_menu_id}
                    """
                    print('menu insert',menuinssql)                     
                    session.execute(text(menuinssql))
                session.commit()

            #end the insert of latest menu            
             
            return {
                "message": f"Portal menu Created successfully for {payload.menu_name}",
                "menu_id": new_menu.menu_id,
                "menu_name": payload.menu_name,
                #"module_name": payload.module_name,
                #"parent_name": payload.parent_name,
            }
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in create_portalmenucreate_data: {exc}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")



@router.post("/portalmenuedit")
def create_portalmenucreate_data(
    request: Request,
    payload: PortalMenuMstSchema,
    token_data: dict = Depends(verify_access_token),
):

    try:
        with Session(default_engine) as session:
            # Extract co_id from the payload
            menu_id = payload.dict().get("menu_id")
            if menu_id is None:
                raise HTTPException(status_code=400, detail="menu_id is required in the payload")
            
            # Convert menu_id to int if it's a string
            if isinstance(menu_id, str):
                try:
                    menu_id = int(menu_id)
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid menu_id format")

            # Get the existing menu
            menu = session.query(PortalMenuMst).filter(PortalMenuMst.menu_id == menu_id).first()
            if menu is None:
                raise HTTPException(status_code=404, detail="Menu not found")

            # Update the menu fields
            menu.menu_name = payload.menu_name
            menu.menu_path = payload.menu_path
            menu.active = payload.active
            menu.menu_parent_id = payload.menu_parent_id
            menu.menu_type_id = payload.menu_type_id
            menu.menu_icon = payload.menu_icon
            menu.module_id = payload.module_id
            menu.order_by = payload.order_by

            session.commit()
            
            return {"message": "Menu updated successfully for {payload.menu_name}", "menu_id": menu.menu_id}
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in edit_menu_data: {exc}")
        import traceback; traceback.print_exc()
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")



@router.get("/orgmodulemapdetails")
def get_roles(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1),
    search: Optional[str] = None,
    #token_data: dict = Depends(verify_access_token),  # Use the new dependency
):
    print("Starting roles_tenant_admin endpoint")
    try:
       # user_id_ck = token_data.get("user_id")  
   

        offset = (page - 1) * limit
        print(f"Calculated offset: {offset} for page: {page} and limit: {limit}")
        #subdomain = extract_subdomain_from_request(request)
    except HTTPException as he:
        print(f"HTTP Exception in get_roles: {str(he)}")


            
    try:
        with Session(default_engine) as session:
            
            # org_id = get_org_id_from_subdomain(subdomain, session)
            # Create query with org_id
            query = orgmodulename(search)
            print(f"Executing query for org_id:  search: {search}")
            modules = session.execute(query, {"limit": limit, "offset": offset, "search": f"%{search}%" if search else None}).fetchall()
            # roles = result.fetchall()
            print(f"Query returned {len(modules) if modules else 0} results")
    except Exception as query_error:
        print(f"Query execution error: {query_error}")
        raise HTTPException(status_code=500, detail=f"Query execution error: {str(query_error)}")

    try: 
        modules = [dict(r._mapping) for r in modules]
        print(f"Converted {len(modules)} rows to dictionaries")
        total = len(modules)
    except Exception as conversion_error:
        print(f"Data conversion error: {conversion_error}")
        raise HTTPException(status_code=500, detail=f"Data conversion error: {str(conversion_error)}")
       
    return { "data": modules, "total": total }



@router.get("/orgmodulemapdetails1")
def get_orgmodulemapdetails(
    # org_id: int,
#    token_data: dict = Depends(verify_access_token),
#    db: Session = Depends(get_tenant_db),
):
    try:
        with Session(default_engine) as session:
            print("Starting fetch_portalmenuname_by_id endpoint")

            modules   = session.execute(orgmodulename()).fetchall()
            print(f"Converted {len(modules)} rows to dictionaries")
            total = len(modules)
            
            roles = [dict(r._mapping) for r in roles]
            print(f"Converted {len(roles)} rows to dictionaries")
            total = len(roles)


            return {
                "data":       [dict(c._mapping) for c in modules],
            }
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in allmenu_data_by_id: {exc}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")



@router.get("/admin_ctrldsk_module_by_orgid/{role_id}")
def get_admin_tenant_menu_by_roleid(
    _: dict = Depends(verify_access_token), 
    role_id: int = Path(..., description="Org ID to filter menus"),  
):
    try:
        with Session(default_engine) as session:
            # Fetch menus for the given role_id
            menu_query = text("""
                SELECT 
    mm.con_module_id con_menu_id,
    mm.con_module_name con_menu_name,null con_menu_parent_id,
    CASE 
        WHEN JSON_CONTAINS(com.con_modules_selected, JSON_QUOTE(CAST(mm.con_module_id AS CHAR))) THEN com.con_org_id
        ELSE NULL
    END AS con_role_id
FROM 
    con_module_masters mm
LEFT JOIN 
    con_org_master com  ON com.con_org_id = :role_id
WHERE 
    mm.active = 1
            """).bindparams(role_id=role_id)
            menu_result = session.execute(menu_query).fetchall()
            print(f"Menu query returned {len(menu_result)} results")

            # Fetch role name for the given role_id
            role_query = text("""
                SELECT con_org_name con_role_name 
                FROM con_org_master 
                WHERE con_org_id = :role_id
            """).bindparams(role_id=role_id)
            role_result = session.execute(role_query).fetchone()
            print(f"Role query returned: {role_result}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query execution error: {str(e)}")


    try:
        # Convert menu query results to dictionaries
        menus = [dict(row._mapping) for row in menu_result]  # row._mapping works across SQLAlchemy versions
        role_name = role_result[0] if role_result else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Data conversion error: {str(e)}")
    return {"data": menus, "roleName": role_name}


@router.get("/admin_ctrldsk_dropdown_org")
def getOrgsFull(
    token_data: dict = Depends(verify_access_token),  # Use the new dependency  
    ):
    try:
        with Session(default_engine) as session:

            query =text(f"select con_org_id con_role_id,con_org_name con_role_name FROM con_org_master where con_org_master_status = 3 and active = 1")
            # text(f"SELECT con_menu_id, con_menu_name, con_menu_parent_id FROM con_menu_master where active =1")
            print(f"Executing query: {query}")
            result = session.execute(query).fetchall()
            print(f"Query returned {len(result) if result else 0} results")
            orgs = [dict(r._mapping) for r in result]
            return orgs

    except HTTPException as he:
        print(f"HTTP Exception in get_users_tenant_admin: {str(he)}")
        raise
    except Exception as e:
        print(f"Unexpected error in get_users_tenant_admin: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


class EditOrgTenantAdminRequest(BaseModel):
    roleId: int
    roleName: str
    selectedMenuIds: List[str]
    menuAccessList: List[dict]


@router.put("/edit_org_module_map_ctrldesk")
def edit_org_module_ctrldesk(
    request: Request,
    role_data: EditOrgTenantAdminRequest,
    token_data: dict = Depends(verify_access_token),
):
    """
    Edit existing role menu mappings

    Args:
        role_data: Role data including role ID, role name, selected menu IDs, and menu access list
        token_data: Authentication token data

    Returns:
        Dict with status and updated role data
    """
    print("Starting edit_org_module_map endpoint")
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        print(f"Authenticated user ID: {user_id}")
        print(f"Editing role ID: {role_data.roleId}")
        print(f"New selected menu IDs: {role_data.selectedMenuIds}")
        print(f"Menu Access List: {role_data.menuAccessList}")

        with Session(default_engine) as session:
            try:
                # First verify if role exists
                role = session.query(ConOrgMaster).filter(
                    ConOrgMaster.con_org_id == role_data.roleId
                ).first()

                if not role:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Role with ID {role_data.roleId} not found"
                    )
                print(f"Found role: {role.con_org_name} (ID: {role.con_modules_selected})")
                # Update con_selected_modules in con_org_master
                print (f"Updating con_selected_modules for role ID {role_data.selectedMenuIds}")
                print(f"Updating con_selected_modules for role ID {role_data.roleId}")
                moduleselected=role_data.selectedMenuIds
                print(f"Roleselected JSON: {moduleselected}")
                # Assign the correct JSON format to con_modules_selected
                # Convert selectedMenuIds to a JSON string of string IDs
                role.con_modules_selected = moduleselected
                session.commit()
                # Delete existing menu mappings for this role
 
                # Insert new menu mappings with access types
  
                return {
                    "status": "success",
                    "message": "Role menu mappings updated successfully",
                    "data": {
                        "role_id": role_data.roleId,
                        "role_name": role_data.roleName,
                        "mapped_menu_count": len(role_data.selectedMenuIds)
                    }
                }

            except Exception as db_error:
                session.rollback()
                print(f"Database error: {str(db_error)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to update role menu mappings: {str(db_error)}"
                )

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error in edit_role_tenant_admin: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


