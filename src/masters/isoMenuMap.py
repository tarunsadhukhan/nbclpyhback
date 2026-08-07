"""ISO document-number map (`co_menu_iso_map`) — small master router.

Design: docs/amcl-enquiry-flow-design.md §5.1 (co_menu_iso_map) + §6 (decision
Q2/Q7). One ISO document number per (company x menu) — generic and reusable
across all modules/tenants (NOT AMCL-specific). Each transaction type is a
menu, so document view/print headers look up the map by the page's menu_id +
selected co_id: if an active row exists the ISO number is shown, otherwise the
space stays blank.

Persona: Portal (tenant DB) — `Depends(get_tenant_db)` +
`get_current_user_with_refresh`. Registered in src/main.py under
`/api/isoMenuMap` (registration is owned by main.py, not this file).

Endpoints:
    GET  /get_iso_map_table  — mapped rows (joined menu_mst for menu_name) +
                               a `master` list of portal page menus for the
                               dropdown
    POST /iso_map_save       — upsert by (co_id, menu_id); iso_doc_no <= 50
                               chars; empty string deactivates the mapping
    POST /iso_map_delete     — soft delete (active = 0)

Shared helper for other routers / print endpoints:
    get_iso_doc_no(db, co_id, menu_id) -> str | None
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body, now_ist

logger = logging.getLogger(__name__)

router = APIRouter()

ISO_DOC_NO_MAX_LEN = 50


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _to_int(value, field_name: str, required: bool = False) -> int | None:
    """Coerce a payload/query value to int with a 400 on bad input."""
    if value is None or value == "":
        if required:
            raise HTTPException(status_code=400, detail=f"{field_name} is required")
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")


# =============================================================================
# QUERIES (inline by design — this master owns its own SQL)
# =============================================================================

def get_iso_map_table_query():
    """Active ISO mappings for a company, joined to menu_mst for display.

    Binds: :co_id, :search (LIKE pattern or None).
    """
    sql = """SELECT
        cim.iso_map_id,
        cim.co_id,
        cim.menu_id,
        mm.menu_name,
        mm.menu_path,
        cim.iso_doc_no,
        cim.active,
        cim.updated_by,
        cim.updated_date_time
    FROM co_menu_iso_map AS cim
    JOIN menu_mst AS mm ON mm.menu_id = cim.menu_id
    WHERE cim.co_id = :co_id
        AND cim.active = 1
        AND (:search IS NULL
             OR mm.menu_name LIKE :search
             OR cim.iso_doc_no LIKE :search)
    ORDER BY mm.menu_name;"""
    return text(sql)


def get_menu_dropdown_query():
    """Active portal page menus for the mapping dropdown.

    Only leaf pages (menu_path set) qualify — parent/folder menus are not
    document types. No binds.
    """
    sql = """SELECT
        mm.menu_id,
        mm.menu_name,
        mm.menu_path
    FROM menu_mst AS mm
    WHERE mm.active = 1
        AND mm.menu_path IS NOT NULL
        AND TRIM(mm.menu_path) <> ''
    ORDER BY mm.menu_name;"""
    return text(sql)


def get_iso_map_by_co_menu_query():
    """Mapping row for a (co_id, menu_id) pair regardless of active flag —
    the unique key makes at most one row, which drives the upsert decision.

    Binds: :co_id, :menu_id.
    """
    sql = """SELECT
        iso_map_id,
        iso_doc_no,
        active
    FROM co_menu_iso_map
    WHERE co_id = :co_id
        AND menu_id = :menu_id;"""
    return text(sql)


def get_iso_map_by_id_query():
    """Mapping row by primary key. Binds: :iso_map_id."""
    sql = """SELECT
        iso_map_id,
        co_id,
        menu_id,
        iso_doc_no,
        active
    FROM co_menu_iso_map
    WHERE iso_map_id = :iso_map_id;"""
    return text(sql)


def menu_exists_query():
    """Existence check for an active menu. Binds: :menu_id."""
    sql = """SELECT menu_id
    FROM menu_mst
    WHERE menu_id = :menu_id
        AND active = 1;"""
    return text(sql)


def insert_iso_map_query():
    """Insert a new mapping. Binds: :co_id, :menu_id, :iso_doc_no,
    :updated_by, :updated_date_time.
    """
    sql = """INSERT INTO co_menu_iso_map
        (co_id, menu_id, iso_doc_no, active, updated_by, updated_date_time)
    VALUES
        (:co_id, :menu_id, :iso_doc_no, 1, :updated_by, :updated_date_time);"""
    return text(sql)


def update_iso_map_query():
    """Update an existing mapping (also reactivates it). Binds: :iso_map_id,
    :iso_doc_no, :updated_by, :updated_date_time.
    """
    sql = """UPDATE co_menu_iso_map
    SET iso_doc_no = :iso_doc_no,
        active = 1,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE iso_map_id = :iso_map_id;"""
    return text(sql)


def soft_delete_iso_map_query():
    """Soft delete (active = 0). Binds: :iso_map_id, :updated_by,
    :updated_date_time.
    """
    sql = """UPDATE co_menu_iso_map
    SET active = 0,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE iso_map_id = :iso_map_id;"""
    return text(sql)


def get_iso_doc_no_query():
    """Active ISO number for a (co_id, menu_id) pair — the shared render
    lookup. Binds: :co_id, :menu_id.
    """
    sql = """SELECT iso_doc_no
    FROM co_menu_iso_map
    WHERE co_id = :co_id
        AND menu_id = :menu_id
        AND active = 1;"""
    return text(sql)


# =============================================================================
# SHARED LOOKUP HELPER (for document get_*_by_id / print endpoints)
# =============================================================================

def get_iso_doc_no(db: Session, co_id, menu_id) -> str | None:
    """ISO document number for a (company, menu/document-type) pair.

    The one shared BE lookup (design §5.1/§6): document view/print endpoints
    call this with the page's menu_id + the selected co_id and render the
    result when present — None means the space stays blank.

    Deliberately never raises: an unmapped/invalid pair (or a lookup hiccup)
    must not break a document view or print, so failures degrade to None.
    """
    if co_id is None or menu_id is None:
        return None
    try:
        co_id_int = int(co_id)
        menu_id_int = int(menu_id)
    except (TypeError, ValueError):
        return None
    try:
        result = db.execute(
            get_iso_doc_no_query(),
            {"co_id": co_id_int, "menu_id": menu_id_int},
        ).fetchone()
    except Exception:
        logger.warning(
            "ISO doc-no lookup failed for co_id=%s menu_id=%s",
            co_id_int, menu_id_int, exc_info=True,
        )
        return None
    if not result:
        return None
    iso_doc_no = dict(result._mapping).get("iso_doc_no")
    return iso_doc_no if iso_doc_no else None


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/get_iso_map_table")
def get_iso_map_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None,
):
    """Active ISO mappings for a company + the menu dropdown master.

    `data` = mapped rows (joined menu_mst for menu_name); `master` = active
    portal page menus so the FE dropdown can offer unmapped document types.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        co_id = _to_int(co_id, "co_id", required=True)

        search_param = f"%{search}%" if search else None

        rows = db.execute(
            get_iso_map_table_query(),
            {"co_id": int(co_id), "search": search_param},
        ).fetchall()
        data = [dict(r._mapping) for r in rows]

        menu_rows = db.execute(get_menu_dropdown_query()).fetchall()
        menus = [dict(r._mapping) for r in menu_rows]

        return {"data": data, "master": menus}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching ISO map table")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/iso_map_save")
def iso_map_save(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Upsert the ISO number for a (co_id, menu_id) pair.

    Payload: {co_id, menu_id, iso_doc_no}. iso_doc_no is trimmed and must be
    <= 50 chars; an empty string clears the mapping (soft-deactivates the
    existing row) so the document header goes back to blank.
    """
    try:
        payload = parse_json_body(request)
        co_id = _to_int(payload.get("co_id"), "co_id", required=True)
        menu_id = _to_int(payload.get("menu_id"), "menu_id", required=True)

        iso_doc_no = payload.get("iso_doc_no")
        if iso_doc_no is None:
            iso_doc_no = ""
        if not isinstance(iso_doc_no, str):
            raise HTTPException(status_code=400, detail="iso_doc_no must be a string")
        iso_doc_no = iso_doc_no.strip()
        if len(iso_doc_no) > ISO_DOC_NO_MAX_LEN:
            raise HTTPException(
                status_code=400,
                detail=f"iso_doc_no must be at most {ISO_DOC_NO_MAX_LEN} characters",
            )

        user_id = _to_int(token_data.get("user_id"), "user_id", required=True)
        updated_at = now_ist()

        existing_row = db.execute(
            get_iso_map_by_co_menu_query(),
            {"co_id": int(co_id), "menu_id": int(menu_id)},
        ).fetchone()
        existing = dict(existing_row._mapping) if existing_row else None

        # Empty string clears the mapping (design: blank when unmapped).
        if iso_doc_no == "":
            if existing and existing.get("active") == 1:
                db.execute(soft_delete_iso_map_query(), {
                    "iso_map_id": int(existing["iso_map_id"]),
                    "updated_by": int(user_id),
                    "updated_date_time": updated_at,
                })
                db.commit()
                return {
                    "data": {
                        "iso_map_id": int(existing["iso_map_id"]),
                        "co_id": int(co_id),
                        "menu_id": int(menu_id),
                        "iso_doc_no": None,
                        "action": "deactivated",
                    },
                    "message": "ISO document number cleared.",
                }
            # Nothing active to clear — idempotent no-op.
            return {
                "data": {
                    "iso_map_id": int(existing["iso_map_id"]) if existing else None,
                    "co_id": int(co_id),
                    "menu_id": int(menu_id),
                    "iso_doc_no": None,
                    "action": "unchanged",
                },
                "message": "No active ISO mapping to clear.",
            }

        # Non-empty save: the menu must be a real, active document type.
        menu_row = db.execute(
            menu_exists_query(), {"menu_id": int(menu_id)}
        ).fetchone()
        if not menu_row:
            raise HTTPException(status_code=400, detail="Invalid menu_id — menu not found or inactive")

        if existing:
            db.execute(update_iso_map_query(), {
                "iso_map_id": int(existing["iso_map_id"]),
                "iso_doc_no": iso_doc_no,
                "updated_by": int(user_id),
                "updated_date_time": updated_at,
            })
            iso_map_id = int(existing["iso_map_id"])
            action = "updated"
        else:
            result = db.execute(insert_iso_map_query(), {
                "co_id": int(co_id),
                "menu_id": int(menu_id),
                "iso_doc_no": iso_doc_no,
                "updated_by": int(user_id),
                "updated_date_time": updated_at,
            })
            iso_map_id = result.lastrowid
            action = "created"

        db.commit()
        return {
            "data": {
                "iso_map_id": iso_map_id,
                "co_id": int(co_id),
                "menu_id": int(menu_id),
                "iso_doc_no": iso_doc_no,
                "action": action,
            },
            "message": "ISO document number saved.",
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error saving ISO map entry")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/iso_map_delete")
def iso_map_delete(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft delete an ISO mapping (active = 0). Payload: {iso_map_id}."""
    try:
        payload = parse_json_body(request)
        iso_map_id = _to_int(payload.get("iso_map_id"), "iso_map_id", required=True)
        user_id = _to_int(token_data.get("user_id"), "user_id", required=True)

        existing_row = db.execute(
            get_iso_map_by_id_query(), {"iso_map_id": int(iso_map_id)}
        ).fetchone()
        if not existing_row:
            raise HTTPException(status_code=404, detail="ISO map entry not found")
        existing = dict(existing_row._mapping)

        if existing.get("active") != 1:
            # Already inactive — idempotent no-op.
            return {
                "data": {"iso_map_id": int(iso_map_id), "action": "unchanged"},
                "message": "ISO map entry is already inactive.",
            }

        db.execute(soft_delete_iso_map_query(), {
            "iso_map_id": int(iso_map_id),
            "updated_by": int(user_id),
            "updated_date_time": now_ist(),
        })
        db.commit()
        return {
            "data": {"iso_map_id": int(iso_map_id), "action": "deactivated"},
            "message": "ISO map entry deleted.",
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting ISO map entry")
        raise HTTPException(status_code=500, detail=str(e))
