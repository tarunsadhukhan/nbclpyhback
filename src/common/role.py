from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.config.database import get_db

router = APIRouter()

class RoleBase(BaseModel):
    name: str
    type: str
    has_hrms_access: bool = False

def get_menu_for_user1_query():
    return text("""
        SELECT r.* 
        FROM roles r 
        WHERE r.has_hrms_access = true 
        AND :userid = 1
        ORDER BY r.created_at DESC 
        LIMIT :limit OFFSET :offset
    """)

def get_menu_for_othuser_query():
    return text("""
        SELECT r.* 
        FROM roles r 
        WHERE r.has_hrms_access = false 
        OR :userid != 1
        ORDER BY r.created_at DESC 
        LIMIT :limit OFFSET :offset
    """)

def get_total_count_query(user_id: int):
    if user_id == 1:
        return text("""
            SELECT COUNT(*) as total 
            FROM roles r 
            WHERE r.has_hrms_access = true 
            AND :userid = 1
        """)
    else:
        return text("""
            SELECT COUNT(*) as total 
            FROM roles r 
            WHERE r.has_hrms_access = false 
            OR :userid != 1
        """)

@router.get("")
def get_roles(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1),
    user_id: int = Query(1),
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        offset = (page - 1) * limit
        params = {"userid": user_id, "limit": limit, "offset": offset}

        # Get the appropriate query based on user_id
        if user_id == 1:
            sql_query = get_menu_for_user1_query()
        else:
            sql_query = get_menu_for_othuser_query()

        # Execute the main query
        roles = db.execute(sql_query, params).fetchall()
        
        # Get total count
        count_query = get_total_count_query(user_id)
        total_result = db.execute(count_query, {"userid": user_id}).fetchone()
        total = total_result[0] if total_result else 0

        return {
            "data": [dict(r._mapping) for r in roles],
            "total": total
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("")
def create_role(role: RoleBase, db: Session = Depends(get_db)):
    try:
        query = text("""
            INSERT INTO roles (name, type, has_hrms_access) 
            VALUES (:name, :type, :has_hrms_access)
        """)
        
        result = db.execute(query, {
            "name": role.name,
            "type": role.type,
            "has_hrms_access": role.has_hrms_access
        })
        db.commit()
        
        # Get the created role
        created_role = db.execute(
            text("SELECT * FROM roles WHERE id = :id"),
            {"id": result.lastrowid}
        ).fetchone()
        
        return dict(created_role._mapping)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{role_id}")
def update_role(role_id: int, role: RoleBase, db: Session = Depends(get_db)):
    try:
        query = text("""
            UPDATE roles 
            SET name = :name, type = :type, has_hrms_access = :has_hrms_access 
            WHERE id = :id
        """)
        
        db.execute(query, {
            "id": role_id,
            "name": role.name,
            "type": role.type,
            "has_hrms_access": role.has_hrms_access
        })
        db.commit()
        
        # Get the updated role
        updated_role = db.execute(
            text("SELECT * FROM roles WHERE id = :id"),
            {"id": role_id}
        ).fetchone()
        
        if not updated_role:
            raise HTTPException(status_code=404, detail="Role not found")
            
        return dict(updated_role._mapping)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))