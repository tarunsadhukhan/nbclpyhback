"""
Worker Category Master API endpoints.

Provides CRUD operations for the category_mst table.
Fields: cata_code (category code), cata_desc (category name), branch_id.
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.mst import CategoryMst
from datetime import datetime
import re
from src.common.utils import parse_json_body

router = APIRouter()


# ─── SQL Queries ────────────────────────────────────────────────────


def parse_branch_ids(raw):
    """Parse branch_id param (comma-separated or JSON array) into list of ints."""
    if not raw:
        return None
    try:
        import json
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [int(x) for x in parsed]
        return [int(parsed)]
    except Exception:
        pass
    cleaned = re.sub(r"^[\[\(]+|[\]\)]+$", "", str(raw)).strip()
    if not cleaned:
        return None
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    out = []
    for p in parts:
        m = re.search(r"-?\d+", p)
        if m:
            out.append(int(m.group(0)))
    return out if out else None


def get_category_list_query(branch_ids=None):
    branch_filter = ""
    if branch_ids:
        placeholders = ",".join(str(int(b)) for b in branch_ids)
        branch_filter = f"AND c.branch_id IN ({placeholders})"
    return text(f"""
        SELECT
            c.cata_id,
            c.cata_code,
            c.cata_desc,
            c.branch_id,
            c.updated_by,
            c.updated_date_time,
            b.branch_name
        FROM category_mst c
        LEFT JOIN branch_mst b ON b.branch_id = c.branch_id
        WHERE (:search IS NULL OR c.cata_code LIKE :search
               OR c.cata_desc LIKE :search)
        {branch_filter}
        ORDER BY c.cata_id DESC
    """)


def get_category_by_id_query():
    return text("""
        SELECT
            c.cata_id,
            c.cata_code,
            c.cata_desc,
            c.branch_id,
            c.updated_by,
            c.updated_date_time,
            b.branch_name
        FROM category_mst c
        LEFT JOIN branch_mst b ON b.branch_id = c.branch_id
        WHERE c.cata_id = :cata_id
    """)


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/get_category_table")
def get_category_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get paginated list of worker categories."""
    try:
        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        raw_branch_ids = request.query_params.get("branch_id")
        branch_ids = parse_branch_ids(raw_branch_ids)

        query = get_category_list_query(branch_ids=branch_ids)
        result = db.execute(query, {
            "search": search_param,
        }).fetchall()

        all_data = [dict(row._mapping) for row in result]
        total = len(all_data)
        start_idx = (page - 1) * limit
        paginated_data = all_data[start_idx:start_idx + limit]

        return {
            "data": paginated_data,
            "total": total,
            "page": page,
            "limit": limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_category_by_id/{cata_id}")
def get_category_by_id(
    cata_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get a single category record by ID."""
    try:
        query = get_category_by_id_query()
        result = db.execute(query, {
            "cata_id": cata_id,
        }).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Category not found")

        return {"data": dict(result._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/category_create_setup")
def category_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get dropdown options needed for category creation (branches)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_query = text("""
            SELECT branch_id, branch_name FROM branch_mst
            WHERE co_id = :co_id AND active = 1
            ORDER BY branch_name
        """)
        branches = db.execute(branch_query, {"co_id": int(co_id)}).fetchall()

        return {
            "branches": [dict(r._mapping) for r in branches],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/category_create")
def category_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new worker category record."""
    try:
        body = parse_json_body(request)

        cata_code = body.get("cata_code")
        if not cata_code:
            raise HTTPException(status_code=400, detail="Category code (cata_code) is required")

        cata_desc = body.get("cata_desc")
        if not cata_desc:
            raise HTTPException(status_code=400, detail="Category name (cata_desc) is required")

        # Check duplicate code
        dup_query = text("""
            SELECT COUNT(*) AS cnt FROM category_mst
            WHERE cata_code = :cata_code
        """)
        dup_result = db.execute(dup_query, {
            "cata_code": cata_code,
        }).fetchone()

        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Category with this code already exists",
            )

        user_id = token_data.get("user_id") if token_data else None

        new_cat = CategoryMst(
            cata_code=cata_code,
            cata_desc=cata_desc,
            branch_id=int(body["branch_id"]) if body.get("branch_id") else None,
            updated_by=str(user_id) if user_id else None,
            updated_date_time=datetime.now(),
        )
        db.add(new_cat)
        db.commit()
        db.refresh(new_cat)

        return {
            "message": "Category created successfully",
            "cata_id": new_cat.cata_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/category_edit/{cata_id}")
def category_edit(
    cata_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing worker category record."""
    try:
        body = parse_json_body(request)

        cata_code = body.get("cata_code")
        if not cata_code:
            raise HTTPException(status_code=400, detail="Category code (cata_code) is required")

        cata_desc = body.get("cata_desc")
        if not cata_desc:
            raise HTTPException(status_code=400, detail="Category name (cata_desc) is required")

        existing = db.query(CategoryMst).filter(
            CategoryMst.cata_id == cata_id,
        ).first()

        if not existing:
            raise HTTPException(status_code=404, detail="Category not found")

        # Check duplicate code (excluding current record)
        dup_query = text("""
            SELECT COUNT(*) AS cnt FROM category_mst
            WHERE cata_code = :cata_code AND cata_id != :cata_id
        """)
        dup_result = db.execute(dup_query, {
            "cata_code": cata_code,
            "cata_id": cata_id,
        }).fetchone()

        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Category with this code already exists",
            )

        user_id = token_data.get("user_id") if token_data else None

        existing.cata_code = cata_code
        existing.cata_desc = cata_desc
        existing.branch_id = int(body["branch_id"]) if body.get("branch_id") else existing.branch_id
        existing.updated_by = str(user_id) if user_id else existing.updated_by
        existing.updated_date_time = datetime.now()

        db.commit()

        return {"message": "Category updated successfully", "cata_id": cata_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
