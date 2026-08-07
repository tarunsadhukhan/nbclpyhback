import anyio
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from fastapi import HTTPException, Request, status
from typing import Optional
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

def parse_json_body(request: Request):
    """Read the JSON request body from a sync (def) endpoint.

    Sync endpoints run in the threadpool; request.json() is async-only, so
    run it back on the event loop and block this worker thread until done.
    """
    return anyio.from_thread.run(request.json)

def now_ist() -> datetime:
    """Returns current datetime in IST (UTC+5:30), timezone-naive for MySQL compatibility."""
    return datetime.now(IST).replace(tzinfo=None)

def create_response(data=None, master=None, message="Success", status="success"):
    """
    Standardized API response format.
    
    Example Responses:
    - create_response(data=some_data) -> { "data": [...] }
    - create_response(data=some_data, master=some_master_data) -> { "data": [...], "master": [...] }
    
    """
    response = {"data": data if data else []}  # ✅ Ensures 'data' is always a list
    if master is not None:
        response["master"] = master  # ✅ Adds 'master' only if provided
    return response




def execute_query(db: Session, query: str, params: dict = None, commit: bool = False):
    """
    Executes a SQL query safely with parameter binding.
    
    - `db`: Database session
    - `query`: SQL query (use parameterized queries)
    - `params`: Dictionary of parameters for query execution
    - `commit`: If `True`, commits the transaction (for INSERT/UPDATE/DELETE)

    Returns:
    - Query result (list of dicts for SELECT)
    - None for INSERT/UPDATE/DELETE
    """
    try:
        result = db.execute(text(query), params or {}).mappings().all()
        
        if commit:
            db.commit()

        return result
    except Exception as e:
        db.rollback()  # Rollback in case of failure
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
 

def validate_headers(authorization: Optional[str], xtenantid: Optional[str]):
    """
    Validates Authorization and X_TENANT_ID headers.
    Raises HTTP 400/401 if missing.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid or missing Authorization header")
    if not xtenantid:
        raise HTTPException(status_code=400, detail="Missing X_TENANT_ID header")



def get_current_timestamp():
    """
    Returns the current timestamp in 'YYYY-MM-DD HH:MM:SS' format.
    """
    return now_ist().strftime("%Y-%m-%d %H:%M:%S")

def get_org_id_from_subdomain(subdomain: str, db: Session) -> int:
    """
    Get the organization ID for a given subdomain using raw SQL.

    Args:
        subdomain (str): Subdomain extracted from the request.
        db (Session): SQLAlchemy session.

    Returns:
        int: Organization ID.

    Raises:
        HTTPException: If organization is not found or on DB error.
    """
    try:
        sql = text(
            "SELECT con_org_id "
            "FROM con_org_master "
            "WHERE con_org_shortname = :subdomain"
        )
        org_id = db.execute(sql, {"subdomain": subdomain}).scalar()

        if org_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization with subdomain {subdomain} not found",
            )

        return org_id

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_org_id_from_subdomain: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving organization ID: {str(e)}",
        )