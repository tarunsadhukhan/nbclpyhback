from datetime import datetime, timedelta
# from sqlmodel import Session, select
# from passlib.context import CryptContext
# import jwt
import os
from fastapi import Depends, Query, Request, HTTPException,APIRouter, Header
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_db_names,default_engine
from src.authorization.utils import verify_access_token
from collections import defaultdict
from src.common.query import get_menu_for_user1_query, get_menu_for_othuser_query,get_total_count_query,get_role_for_user1_query, get_role_for_user1_query_company
# Example definition for get_menu_for_othuser_query (replace with actual implementation)
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

from fastapi import Request, Query, Cookie, HTTPException
from sqlalchemy.sql import text
from sqlalchemy.orm import Session


class RoleBase(BaseModel):
    name: str
    type: str
    has_hrms_access: bool = False


# control desk menu
@router.get("/console_menu_items")
def compmenuitems(
    request: Request,
    subdomain: str = Query(...),
    user_id: str = Query(...),
    token_data: dict = Depends(verify_access_token),  # Use the new dependency
):
    subdomain = request.headers.get("X-Subdomain", "default")
    print(subdomain)

    user_id_from_cookie = token_data.get("user_id")
    print(f"Query user_id: {user_id}, Token user_id: {user_id_from_cookie}")  # Debug
    if not user_id_from_cookie:
        raise HTTPException(status_code=403, detail="User ID not found in token")

    if str(user_id) != str(user_id_from_cookie):
        print(f"User ID mismatch: Query user_id={user_id}, Token user_id={user_id_from_cookie}")  # Debug
        raise HTTPException(status_code=403, detail="Unauthorized access via cookie")

    print(f"✅ Authorized Request: Subdomain: {subdomain}, User ID: {user_id}, Cookie User: {user_id_from_cookie}")
    host = subdomain.strip()
    print(host)

    print(request)
    params = {}
    print('starting ', user_id)  
    if int(user_id) == 1:
        sql_query = get_menu_for_user1_query()
        params = {"userid": user_id} 
    else:
        sql_query = get_menu_for_othuser_query()
        params = {"userid": user_id} 

    print("sqluery display for menu", sql_query, params)
        
        
    
    with Session(default_engine) as session:
        # user = session.execute(text(sql_query), params if params else {}).fetchall()
        user = session.execute(sql_query, params if params else {}).fetchall()
        # print('queruserr', sql_query, user)


    column_names = ['id', 'title', 'path', 'icon', 'parent_id', 'mmenu_id', 'company_id', 'user_id']
    results = [dict(zip(column_names, row)) for row in user]
    print('results', results)

    mainMenus = [item for item in results if item['parent_id'] == 0]
    subMenus = [item for item in results if item['parent_id'] != 0]

    print('main', mainMenus)
    print('sub', subMenus)

    menuData = []
    for main in mainMenus:
        submenuItems = [{
            'id': sub['id'],
            'title': sub['title'],
            'path': sub['path'],
            'icon': sub['icon'],
        } for sub in subMenus if sub['parent_id'] == main['id']]

        menuData.append({
            'id': main['id'],
            'title': main['title'],
            'path': main['path'],
            'icon': main['icon'],
            'submenu': submenuItems if submenuItems else None,
        })
        print('menuData other user', menuData)
    return {
        "data": menuData
    }



@router.get("/companyfyyear")
def companiesfyyear(
    request: Request
    
   
 ):

    

    db_data = get_db_names(request)  # ✅ Fetch the full dictionary
    print('DEBUG: db_data =', db_data)  # ✅ Print full response for debugging

    dbs = db_data["db_engines"]  # ✅ Extract database engines
    dbn = db_data["db_names_array"]  # ✅ Extract database names

    print("DEBUG: db_engines =", dbs)  # ✅ Debugging
    print("DEBUG: db_names_array =", dbn)  # ✅ Debugging

    # ✅ Assign dynamic variables based on available database names
    dbfl1 = dbn[0] if len(dbn) > 0 else None
    dbfl2 = dbn[1] if len(dbn) > 1 else None

    print(f"Assigned dbfl1: {dbfl1}, dbfl2: {dbfl2}")  # ✅ Debugging
    print(request)
    
    
    
    
    if not isinstance(db_data, dict) or "db_engines" not in db_data:
        return {
            "access_token": "",
            "token_type": "",
            "status_code": 500,  # Internal Server Error
            "message": "Database connection failed: Invalid database configuration"
        }
       
    
    


    
    print('2nd ',request)
    if "default" not in dbs:
        return {
            "access_token": "",
            "token_type": "",
            "status_code": 500,  # Internal Server Error
            "message": "Database connection failed: Default database missing"
        }
        
        
        #raise HTTPException(status_code=500, detail="Default database connection missing")
    print('3ndddssdsdsd ',request)
    print ('Hosthdshdshd') 
    subdomain = request.headers.get("subdomain")
    host = subdomain.strip() if subdomain else None
    if not host:
           return {
             "access_token": "",
            "token_type": "",
            "status_code": 400,  # Internal Server Error
            "message": "Invalid Subdoman"   
        }
     
        #raise HTTPException(status_code=400, detail="Invalid subdomain")
    
    
    print('hhhs',host)
   
    #engine = create_engine(dbs["default"])
    with Session(default_engine) as session:
        query = text("""select hdr_id id,display_label years from dbfl1.academic_years where company_id=:cmpid order by from_date desc""")
        print('querr', query)
        cmpid=2
        user = session.execute(query, {"cmpid": cmpid}).fetchall()
        print('queruserr', query, user)

        if not user:
            return {
                "data": [],
                "status_code": 401,  # Unauthorized
                "message": "No Data Found"
            }
    return {
        "data": user,
        "status_code": 200,  # Success
        "message": "Login successful"
    }
        




@router.get("/roles_sls")
def get_roles(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1),
    search: Optional[str] = None,
    token_data: dict = Depends(verify_access_token),  # Use the new dependency
):
    user_id_ck = token_data.get("user_id")  
    offset = (page - 1) * limit
    try:
            db = get_db_names(request)  # ✅ Fetch the full dictionary
    except Exception as db_error:
            raise HTTPException(status_code=500, detail=f"Database configuration error: {str(db_error)}")
        # Check if db is properly structured
    if not isinstance(db, dict) or "db" not in db:
            raise HTTPException(status_code=500, detail="Invalid database configuration structure")
    dbm = db.get("db")  # Get the database name
    try:
            if user_id_ck == 1:
                query = get_role_for_user1_query(search, dbm)
            else:
                query = get_role_for_user1_query_company(search, dbm)
    except Exception as query_error:
            raise HTTPException(status_code=500, detail=f"Query generation error: {str(query_error)}")
            
        # Execute the main query
    try:
            with Session(default_engine) as session:
                print(f"Executing query with  limit={limit}, offset={offset}, search={search}")
                roles = session.execute(
                    query, { "limit": limit, "offset": offset, "search": f"%{search}%" if search else None}
                ).fetchall()
                print(f"Query returned {len(roles) if roles else 0} results")
    except Exception as query_exec_error:
            raise HTTPException(status_code=500, detail=f"Database query error: {str(query_exec_error)}")

        # Convert roles to a list of dictionaries
    try:
            roles = [dict(r._mapping) for r in roles]
            print(f"Converted {len(roles)} rows to dictionaries")
    except Exception as conversion_error:
            print(f"Data conversion error: {conversion_error}")
            raise HTTPException(status_code=500, detail=f"Data conversion error: {str(conversion_error)}")

    except HTTPException:
        # Re-raise HTTP exceptions to maintain their status codes
        raise
    except Exception as e:
        # Catch any other exceptions
        print(f"Unexpected error in get_roles: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    # Get total count
    try:
        with Session(default_engine) as session:
            count_query = get_total_count_query(user_id_ck, search)
            cmpid = 2
            total_result = session.execute(count_query, {"cmpid": cmpid, "search": f"%{search}%" if search else None}).fetchone()
            print(f"Total count query result: {total_result}")

        # Extract the count value
        total = total_result[0] if total_result else 0
        print(f"Total records: {total}")

    except Exception as count_error:
        print(f"Error retrieving total count: {count_error}")
        total = 0  # Default to 0 if count query fails

    return {
        "data": roles,
        "total": total
    }
  

@router.get("/roles")
def get_roles(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1),
    user_id: int = Query(1),
    search: Optional[str] = None,
):
    try:
        offset = (page - 1) * limit

        # Get the appropriate query based on user_id
        if user_id == 1:
            query = get_role_for_user1_query(search)
        else:
            query = get_menu_for_othuser_query()

        # Execute the main query
        with Session(default_engine) as session:
            cmpid = 2
            roles = session.execute(
            query, {"cmpid": cmpid, "limit": limit, "offset": offset, "search": f"%{search}%" if search else None}
            ).fetchall()
            print("queruserr", query, roles)

        # Convert roles to a list of dictionaries
        roles = [dict(r._mapping) for r in roles]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Get total count
    with Session(default_engine) as session:
        count_query = get_total_count_query(user_id,search)
        cmpid = 2
        total_result = session.execute(count_query, {"cmpid": cmpid, "search": f"%{search}%" if search else None}).fetchone()
        print("total", total_result)

    # total = total_result[0] if total_result else 0
    total = total_result[0] if total_result else 0


    return {
        "data": roles,
        "total": total
    }
