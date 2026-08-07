"""Weaving Process lock lookups + the locked-unit permission gate.

A (co, branch, tran_date, spell) unit is locked once Processed. While locked,
weaving-page mutations require Edit (access_type_id >= 4); Write-only (3) is
rejected 403. Reads use is_unit_locked to choose frozen-log vs live slice."""

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.common.portal.query import get_user_menu_access_level_query
from src.juteProduction.weaving_query import flag_weaving_unit_reprocess_query

WEAVING_MENU_PATH = "juteProduction/weaving"
EDIT_LEVEL = 4
LOCKED_EDIT_ONLY_MSG = (
    "This day/spell is processed and locked. Editing a locked weaving entry "
    "requires Edit permission for the Weaving Production menu."
)


def get_process_lock(db: Session, co_id, branch_id, tran_date, spell_id):
    """Active lock header for the unit (or None)."""
    return db.execute(
        text(
            """
            SELECT weaving_process_lock_id, is_locked, reprocess_needed
            FROM jute_prod_weaving_process_lock
            WHERE co_id = :co_id AND tran_date = :tran_date AND spell_id = :spell_id
              AND (:branch_id IS NULL OR branch_id = :branch_id OR branch_id IS NULL)
              AND active = 1
            ORDER BY weaving_process_lock_id DESC
            LIMIT 1
            """
        ),
        {"co_id": int(co_id), "tran_date": tran_date, "spell_id": int(spell_id),
         "branch_id": None if branch_id is None else int(branch_id)},
    ).fetchone()


def is_unit_locked(db: Session, co_id, branch_id, tran_date, spell_id) -> bool:
    row = get_process_lock(db, co_id, branch_id, tran_date, spell_id)
    return bool(row and row.is_locked)


def user_menu_access_level(db: Session, user_id, co_id, branch_id, menu_path) -> int:
    lvl = db.execute(
        get_user_menu_access_level_query(),
        {"user_id": int(user_id), "co_id": int(co_id),
         "branch_id": None if branch_id is None else int(branch_id),
         "menu_path": menu_path},
    ).scalar()
    return int(lvl) if lvl is not None else 0


def require_edit_if_locked(db: Session, token_data: dict, co_id, branch_id,
                           tran_date, spell_id) -> None:
    """Raise 403 when the unit is locked and the user lacks Edit (>= 4)."""
    if not is_unit_locked(db, co_id, branch_id, tran_date, spell_id):
        return
    level = user_menu_access_level(
        db, token_data.get("user_id"), co_id, branch_id, WEAVING_MENU_PATH
    )
    if level < EDIT_LEVEL:
        raise HTTPException(status_code=403, detail=LOCKED_EDIT_ONLY_MSG)


def flag_reprocess_if_locked(db: Session, co_id, tran_date, spell_id) -> None:
    """Raise reprocess_needed on the unit's lock header when it is locked (no-op else).

    Spec §7: an Edit-user mutation of a processed unit invalidates its frozen snapshot,
    so the unit must be flagged for reprocessing. Safe to call on any mutation path."""
    if co_id is None or spell_id is None:
        return
    db.execute(
        flag_weaving_unit_reprocess_query(),
        {"co_id": int(co_id), "tran_date": tran_date, "spell_id": int(spell_id)},
    )
