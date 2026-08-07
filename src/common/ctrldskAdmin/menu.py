from fastapi import Depends, Request, HTTPException,APIRouter
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_db_names,default_engine, get_db
from src.authorization.utils import verify_access_token
from src.common.companyAdmin.schemas import MenuResponse
from src.common.companyAdmin.models import ConMenuMaster, ConUserRoleMapping, ConRoleMenuMap

router = APIRouter()

@router.get("/company_console_menu_items", response_model=MenuResponse)
def compmenuitems(
    request: Request,
    token_data: dict = Depends(verify_access_token),  # Use the new dependency
):
    # Extract subdomain from host header
    host = request.headers.get("host", "")
    subdomain = host.split('.')[0] if '.' in host else "default"
    
    user_id_ck = token_data.get("user_id")
    print(f" Token user_id: {user_id_ck}")  # Debug
    if not user_id_ck:
        raise HTTPException(status_code=403, detail="User ID not found in token")
    print(f"✅ Authorized Request: Subdomain: {subdomain}, Cookie User: {user_id_ck}")

    with Session(default_engine) as session:
        # Get all menu items
        menu_items = session.query(ConMenuMaster).filter(ConMenuMaster.active == True).order_by(ConMenuMaster.order_by).all()
        
        # Separate main menus and submenus
        main_menus = [item for item in menu_items if item.con_menu_parent_id is None or item.con_menu_parent_id == 0]
        sub_menus = [item for item in menu_items if item.con_menu_parent_id is not None and item.con_menu_parent_id > 0]

        # Format the response
        menu_data = []
        for main in main_menus:
            submenu_items = [{
                'id': sub.con_menu_id,
                'title': sub.con_menu_name,
                'path': sub.con_menu_path,
                'icon': sub.con_menu_icon,
            } for sub in sub_menus if sub.con_menu_parent_id == main.con_menu_id]

            menu_data.append({
                'id': main.con_menu_id,
                'title': main.con_menu_name,
                'path': main.con_menu_path,
                'icon': main.con_menu_icon,
                'submenu': submenu_items if submenu_items else None,
            })

    return {
        "data": menu_data
    }

@router.get("/tenant_console_menu_items_roleid", response_model=MenuResponse)
def compmenuitems(
    request: Request,
    token_data: dict = Depends(verify_access_token),
):
    print("\n=== Starting /tenant_console_menu_items_roleid endpoint ===")
    # Extract subdomain from host header
    host = request.headers.get("host", "")
    subdomain = host.split('.')[0] if '.' in host else "default"
    
    user_id = token_data.get("user_id")
    print(f"📌 Token data received: {token_data}")
    print(f"👤 User ID from token: {user_id}")
    
    if not user_id:
        print("❌ Error: No user_id found in token")
        raise HTTPException(status_code=403, detail="User ID not found in token")
    print(f"✅ Authorized Request: Subdomain: {subdomain}, User: {user_id}")

    try:
        with Session(default_engine) as session:
            print("🔄 Starting database session")
            
            # Use raw SQL query with user_id from token
            query = text("""
                SELECT cmm.con_menu_id, cmm.con_menu_name, cmm.con_menu_parent_id, 
                       cmm.con_menu_path, cmm.con_menu_icon 
                FROM con_menu_master cmm 
                WHERE con_menu_id IN (
                    SELECT con_menu_id FROM con_role_menu_map crmm 
                    WHERE con_role_id = (
                        SELECT con_role_id FROM con_user_role_mapping curm 
                        WHERE con_user_id = :user_id
                    )
                ) 
                AND cmm.active = true
                ORDER BY order_by
            """)
            
            print(f"🔍 Executing query for user_id: {user_id}")
            result = session.execute(query, {"user_id": user_id})
            menu_items = result.fetchall()
            print(f"📋 Retrieved {len(menu_items)} menu items")
            
            if not menu_items:
                print("ℹ️ No menu items found, returning empty data")
                return {"data": []}
            
            # Convert result to a list of dictionaries for easier processing
            menu_items = [
                {
                    "id": item.con_menu_id,
                    "title": item.con_menu_name,
                    "path": item.con_menu_path,
                    "icon": item.con_menu_icon,
                    "parent_id": item.con_menu_parent_id
                }
                for item in menu_items
            ]
            
            # Separate main menus and submenus
            main_menus = [item for item in menu_items if item["parent_id"] is None or item["parent_id"] == 0]
            sub_menus = [item for item in menu_items if item["parent_id"] is not None and item["parent_id"] > 0]
            print(f"📋 Found {len(main_menus)} main menus and {len(sub_menus)} submenus")

            # Format the response
            menu_data = []
            for main in main_menus:
                submenu_items = [{
                    'id': sub["id"],
                    'title': sub["title"],
                    'path': sub["path"],
                    'icon': sub["icon"],
                } for sub in sub_menus if sub["parent_id"] == main["id"]]

                menu_data.append({
                    'id': main["id"],
                    'title': main["title"],
                    'path': main["path"],
                    'icon': main["icon"],
                    'submenu': submenu_items if submenu_items else None,
                })
            
            print(f"✅ Successfully built response with {len(menu_data)} menu items")
            return {
                "data": menu_data
            }
    except Exception as e:
        print(f"❌ Error occurred: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        print(f"Error details: {e.__dict__}")
        raise

@router.get("/control-desk-menu", response_model=list)
def get_control_desk_menu(db: Session = Depends(get_db)):
    """
    Fetch control desk menu data with parent menu name and tooltip details using raw SQL query.
    """
    raw_query = text("""
        SELECT 
            cdm.control_desk_menu_id,
            cdm.control_desk_menu_name,
            cdm.active,
            cdm.parent_id,
            CASE 
                WHEN cdm.parent_id > 0 THEN (SELECT parent.control_desk_menu_name 
                                            FROM control_desk_menu parent 
                                            WHERE parent.control_desk_menu_id = cdm.parent_id)
                ELSE ''
            END AS parent_menu_name,
            cdm.menu_type,
            cdm.menu_path,
            cdm.menu_state,
            cdm.report_path,
            cdm.menu_icon_name,
            cdm.order_by
        FROM control_desk_menu cdm
    """)

    result = db.execute(raw_query).fetchall()

    response = []
    for row in result:
        response.append({
            "control_desk_menu_id": row.control_desk_menu_id,
            "control_desk_menu_name": row.control_desk_menu_name,
            "active": row.active,
            "parent_id": row.parent_id,
            "parent_menu_name": row.parent_menu_name,
            "menu_type": row.menu_type,
            "tooltip": {
                "menu_path": row.menu_path,
                "menu_state": row.menu_state,
                "report_path": row.report_path,
                "menu_icon_name": row.menu_icon_name,
                "order_by": row.order_by
            }
        })

    return response