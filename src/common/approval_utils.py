"""Shared approval utility functions.

Provides generic approval processing, rejection, and permission calculation
that can be used across all modules (procurement, sales, jute, etc.).

Each module passes in its own get_doc_fn and update_status_fn callables
so the core approval logic remains module-agnostic.
"""

import logging
from datetime import datetime
from typing import Optional
from src.common.utils import now_ist

from sqlalchemy.orm import Session
from fastapi import HTTPException

from src.common.approval_query import (
    get_user_approval_level,
    get_max_approval_level,
    check_approval_mst_exists,
    get_user_edit_access,
)

logger = logging.getLogger(__name__)


def process_approval(
    doc_id: int,
    user_id: int,
    menu_id: int,
    db: Session,
    get_doc_fn,
    update_status_fn,
    id_param_name: str,
    doc_name: str,
    document_amount: float | None = None,
    extra_update_params: dict | None = None,
    get_consumed_amounts_fn=None,
    commit: bool = True,
) -> dict:
    """Generic approval processing for any document type.

    Handles the full approval lifecycle: auto-transition from Open (1) to
    Pending Approval (20), level-based approval checks, optional value-based
    limits, and final approval (status 3) when the last level is reached.

    Args:
        doc_id: The document primary key value.
        user_id: The approving user's ID.
        menu_id: The menu ID for approval lookup.
        db: Database session.
        get_doc_fn: Callable that returns a text() query. The query must
            return columns: status_id, approval_level, branch_id.
        update_status_fn: Callable that returns a text() query for updating
            status_id and approval_level. Must accept bind params:
            {id_param_name}, status_id, approval_level, updated_by,
            updated_date_time.
        id_param_name: The bind parameter name for the document ID
            (e.g., 'indent_id', 'po_id', 'sales_quotation_id').
        doc_name: Human-readable document name for error messages
            (e.g., 'Indent', 'Purchase Order', 'Quotation').
        document_amount: Optional amount for value-based approval checks.
            When None, amount checks are skipped entirely.
        extra_update_params: Optional dict of additional bind parameters
            to include in update_status_fn calls (e.g., {'indent_no': None}).
        get_consumed_amounts_fn: Optional callable that returns a text() query
            for fetching daily/monthly consumed amounts. The query must accept
            bind param :user_id and return columns: day_total, month_total.
            When provided, daily/monthly limits from approval_mst are enforced.
        commit: When True (default) the status transition is committed before
            returning. Pass False when the caller performs additional writes in
            the SAME transaction after this call (e.g. generating document
            numbers on final approval) and will commit once itself — so the
            status change and those writes land atomically.

    Returns:
        Dict with keys: status, new_status_id, new_approval_level, message.
    """
    try:
        merged_extra = extra_update_params or {}

        # 1. Fetch the document
        doc_query = get_doc_fn()
        doc_result = db.execute(doc_query, {id_param_name: doc_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail=f"{doc_name} not found")

        doc = dict(doc_result._mapping)
        current_status_id = doc.get("status_id")
        current_approval_level = doc.get("approval_level") or 0
        branch_id = doc.get("branch_id")

        # 2. Guard: already approved
        if current_status_id == 3:
            raise HTTPException(
                status_code=400,
                detail=f"{doc_name} is already approved."
            )

        # 3. Auto-transition from Open (1) to Pending Approval (20)
        if current_status_id == 1:
            updated_at = now_ist()
            update_q = update_status_fn()
            params = {
                id_param_name: doc_id,
                "status_id": 20,
                "approval_level": 1,
                "updated_by": user_id,
                "updated_date_time": updated_at,
                **merged_extra,
            }
            db.execute(update_q, params)
            # Do NOT commit here — keep auto-transition + approval as one
            # atomic transaction. The single commit at the end handles both.
            # If validation fails, db.rollback() in the except block will
            # undo this auto-transition.
            current_status_id = 20
            current_approval_level = 1

        # 4. Must be in Pending Approval (20) to proceed
        if current_status_id != 20:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot approve {doc_name} with status_id {current_status_id}. "
                    f"Expected 20 (Pending Approval) or 1 (Open)."
                )
            )

        # 5. Check if approval hierarchy exists for this menu/branch
        approval_exists_query = check_approval_mst_exists()
        approval_exists_result = db.execute(
            approval_exists_query,
            {"menu_id": menu_id, "branch_id": branch_id}
        ).fetchone()
        approval_exists = False
        if approval_exists_result:
            approval_exists = (dict(approval_exists_result._mapping).get("count") or 0) > 0

        if approval_exists:
            # 6a. Hierarchy exists — use level-based approval
            # A user may have entries at multiple levels (e.g., level 1 AND level 2).
            # Fetch all and find the row matching the document's current level.
            user_level_query = get_user_approval_level()
            user_level_rows = db.execute(
                user_level_query,
                {"menu_id": menu_id, "branch_id": branch_id, "user_id": user_id}
            ).fetchall()

            if not user_level_rows:
                raise HTTPException(
                    status_code=403,
                    detail="User does not have approval permission for this menu and branch."
                )

            # Find the row matching the document's current approval level
            user_data = None
            for row in user_level_rows:
                row_dict = dict(row._mapping)
                if row_dict.get("approval_level") == current_approval_level:
                    user_data = row_dict
                    break

            if user_data is None:
                # User has approval entries but none at the current level
                user_levels = [dict(r._mapping).get("approval_level") for r in user_level_rows]
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"User approval level(s) {user_levels} do not match "
                        f"current {doc_name} approval level ({current_approval_level})."
                    )
                )

            user_approval_level = user_data.get("approval_level")

            # 8. Get max approval level for this menu/branch (needed for
            #    value-based decisions below)
            max_level_query = get_max_approval_level()
            max_level_result = db.execute(
                max_level_query,
                {"menu_id": menu_id, "branch_id": branch_id}
            ).fetchone()
            max_approval_level = (
                dict(max_level_result._mapping).get("max_level")
                if max_level_result
                else user_approval_level
            )

            # 9. Value-based checks (only when document_amount is provided)
            value_based_final = False
            amount_exceeds_limit = False
            if document_amount is not None:
                max_amount_single = user_data.get("max_amount_single")
                day_max_amount_limit = user_data.get("day_max_amount")
                month_max_amount_limit = user_data.get("month_max_amount")

                # Check single-document amount limit
                has_value_limits = (
                    max_amount_single is not None and max_amount_single > 0
                )
                if has_value_limits:
                    if document_amount > max_amount_single:
                        # Amount exceeds this user's limit. If higher levels
                        # exist, escalate so someone with a higher limit can
                        # approve. Only block when this IS the final level.
                        if user_approval_level >= max_approval_level:
                            raise HTTPException(
                                status_code=403,
                                detail=(
                                    f"Document amount ({document_amount}) exceeds maximum "
                                    f"single approval amount ({max_amount_single}) "
                                    f"and no higher approval level exists."
                                )
                            )
                        amount_exceeds_limit = True
                    else:
                        # Single amount is within limit — check daily/monthly
                        value_based_final = True

                        if get_consumed_amounts_fn is not None:
                            needs_daily = (
                                day_max_amount_limit is not None
                                and day_max_amount_limit > 0
                            )
                            needs_monthly = (
                                month_max_amount_limit is not None
                                and month_max_amount_limit > 0
                            )

                            if needs_daily or needs_monthly:
                                consumed_query = get_consumed_amounts_fn()
                                consumed_result = db.execute(
                                    consumed_query, {"user_id": user_id}
                                ).fetchone()

                                if consumed_result:
                                    consumed = dict(consumed_result._mapping)
                                    day_total = float(consumed.get("day_total", 0) or 0)
                                    month_total = float(consumed.get("month_total", 0) or 0)

                                    if needs_daily and (day_total + document_amount) > day_max_amount_limit:
                                        if user_approval_level >= max_approval_level:
                                            raise HTTPException(
                                                status_code=403,
                                                detail=(
                                                    f"Approving this {doc_name} (amount {document_amount}) "
                                                    f"would exceed daily approval limit "
                                                    f"({day_total} + {document_amount} > {day_max_amount_limit})."
                                                )
                                            )
                                        value_based_final = False
                                        amount_exceeds_limit = True

                                    if needs_monthly and (month_total + document_amount) > month_max_amount_limit:
                                        if user_approval_level >= max_approval_level:
                                            raise HTTPException(
                                                status_code=403,
                                                detail=(
                                                    f"Approving this {doc_name} (amount {document_amount}) "
                                                    f"would exceed monthly approval limit "
                                                    f"({month_total} + {document_amount} > {month_max_amount_limit})."
                                                )
                                            )
                                        value_based_final = False
                                        amount_exceeds_limit = True

            # 10-11. Determine next status
            # - value_based_final: user's value limits cover the amount →
            #   approve directly without requiring higher levels.
            # - amount_exceeds_limit: user's limits are too low → force
            #   escalation to next level regardless of level-based logic.
            if amount_exceeds_limit:
                # Must escalate — user's value authority is insufficient
                new_status_id = 20  # Still Pending Approval
                new_approval_level = current_approval_level + 1
                message = f"{doc_name} moved to approval level {new_approval_level}."
            elif user_approval_level >= max_approval_level or value_based_final:
                new_status_id = 3  # Approved (final)
                new_approval_level = user_approval_level
                message = f"{doc_name} approved (final level)."
            else:
                new_status_id = 20  # Still Pending Approval
                new_approval_level = current_approval_level + 1
                message = f"{doc_name} moved to approval level {new_approval_level}."
        else:
            # 6b. No hierarchy — fall back to edit-access check
            if not _user_has_edit_access(user_id, branch_id, menu_id, db):
                raise HTTPException(
                    status_code=403,
                    detail="User does not have approval permission for this menu and branch."
                )
            # Direct approval — no levels to traverse
            new_status_id = 3  # Approved (final)
            new_approval_level = current_approval_level
            message = f"{doc_name} approved (no approval hierarchy configured)."

        # 12. Update document status
        updated_at = now_ist()
        update_q = update_status_fn()
        params = {
            id_param_name: doc_id,
            "status_id": new_status_id,
            "approval_level": new_approval_level,
            "updated_by": user_id,
            "updated_date_time": updated_at,
            **merged_extra,
        }
        db.execute(update_q, params)

        # 13. Commit (unless the caller will commit its own follow-up writes in
        #     the same transaction so status + those writes land atomically).
        if commit:
            db.commit()

        # 14. Return result
        return {
            "status": "success",
            "new_status_id": new_status_id,
            "new_approval_level": new_approval_level,
            "message": message,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"Error processing approval for {doc_name}")
        raise HTTPException(status_code=500, detail=str(e))


def process_rejection(
    doc_id: int,
    user_id: int,
    menu_id: int | None,
    db: Session,
    get_doc_fn,
    update_status_fn,
    id_param_name: str,
    doc_name: str,
    reason: str | None = None,
    extra_update_params: dict | None = None,
) -> dict:
    """Generic rejection processing for any document type.

    Rejects a document that is currently in Pending Approval (status 20),
    setting its status to Rejected (4) and clearing the approval level.

    Args:
        doc_id: The document primary key value.
        user_id: The rejecting user's ID.
        menu_id: The menu ID for approval lookup. When provided, the
            function verifies the user has approval permission at the
            current level before allowing rejection.
        db: Database session.
        get_doc_fn: Callable that returns a text() query. The query must
            return columns: status_id, approval_level, branch_id.
        update_status_fn: Callable that returns a text() query for updating
            status_id and approval_level.
        id_param_name: The bind parameter name for the document ID.
        doc_name: Human-readable document name for error messages.
        reason: Optional rejection reason (logged but not stored by this
            function — callers may store it separately).
        extra_update_params: Optional dict of additional bind parameters
            to include in update_status_fn calls.

    Returns:
        Dict with keys: status, new_status_id, new_approval_level, message.
    """
    try:
        merged_extra = extra_update_params or {}

        # 1. Fetch the document
        doc_query = get_doc_fn()
        doc_result = db.execute(doc_query, {id_param_name: doc_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail=f"{doc_name} not found")

        doc = dict(doc_result._mapping)
        current_status_id = doc.get("status_id")
        current_approval_level = doc.get("approval_level")
        branch_id = doc.get("branch_id")

        # Must be in Pending Approval (20)
        if current_status_id != 20:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot reject {doc_name} with status_id {current_status_id}. "
                    f"Expected 20 (Pending Approval)."
                )
            )

        # 2. If menu_id provided, verify user has approval permission at current level
        if menu_id is not None:
            # Check if approval hierarchy exists for this menu/branch
            approval_exists_query = check_approval_mst_exists()
            approval_exists_result = db.execute(
                approval_exists_query,
                {"menu_id": menu_id, "branch_id": branch_id}
            ).fetchone()
            approval_exists = False
            if approval_exists_result:
                approval_exists = (dict(approval_exists_result._mapping).get("count") or 0) > 0

            if approval_exists:
                # Hierarchy exists — use level-based check
                user_level_query = get_user_approval_level()
                user_level_rows = db.execute(
                    user_level_query,
                    {"menu_id": menu_id, "branch_id": branch_id, "user_id": user_id}
                ).fetchall()

                if not user_level_rows:
                    raise HTTPException(
                        status_code=403,
                        detail="User does not have approval permission for this menu and branch."
                    )

                user_levels = [dict(r._mapping).get("approval_level") for r in user_level_rows]
                if current_approval_level not in user_levels:
                    raise HTTPException(
                        status_code=403,
                        detail=(
                            f"User approval level(s) {user_levels} do not match "
                            f"current {doc_name} approval level ({current_approval_level})."
                        )
                    )
            else:
                # No hierarchy — fall back to edit-access check
                if not _user_has_edit_access(user_id, branch_id, menu_id, db):
                    raise HTTPException(
                        status_code=403,
                        detail="User does not have rejection permission for this menu and branch."
                    )

        # 3. Update status to Rejected (4), clear approval_level
        updated_at = now_ist()
        update_q = update_status_fn()
        params = {
            id_param_name: doc_id,
            "status_id": 4,  # Rejected
            "approval_level": None,
            "updated_by": user_id,
            "updated_date_time": updated_at,
            **merged_extra,
        }
        db.execute(update_q, params)

        # 4. Commit
        db.commit()

        if reason:
            logger.info(f"{doc_name} {doc_id} rejected by user {user_id}. Reason: {reason}")

        # 5. Return result
        return {
            "status": "success",
            "new_status_id": 4,
            "new_approval_level": None,
            "message": f"{doc_name} has been rejected.",
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"Error processing rejection for {doc_name}")
        raise HTTPException(status_code=500, detail=str(e))


def calculate_approval_permissions(
    user_id: int,
    menu_id: int,
    branch_id: int,
    status_id: int,
    current_approval_level: int | None,
    db: Session,
) -> dict:
    """Calculate approval permissions for a user based on document status and approval configuration.

    Returns a dict of boolean permission flags that the frontend uses to
    show/hide action buttons (Approve, Reject, Open, Cancel Draft, etc.).

    Args:
        user_id: The user ID.
        menu_id: The menu ID.
        branch_id: The branch ID.
        status_id: Current status ID of the document.
        current_approval_level: Current approval level (only relevant when status_id = 20).
        db: Database session.

    Returns:
        Dict with permission flags: canApprove, canReject, canOpen,
        canSendForApproval, canCancelDraft, canReopen, canViewApprovalLog,
        canClone, canSave.
    """
    permissions = {
        "canApprove": False,
        "canReject": False,
        "canOpen": False,
        "canSendForApproval": False,
        "canCancelDraft": False,
        "canReopen": False,
        "canViewApprovalLog": False,
        "canClone": False,
        "canSave": False,
    }

    try:
        # Check if approval_mst has entries for this menu/branch
        approval_exists_query = check_approval_mst_exists()
        approval_exists_result = db.execute(
            approval_exists_query,
            {"menu_id": menu_id, "branch_id": branch_id}
        ).fetchone()
        approval_exists = False
        if approval_exists_result:
            result_dict = dict(approval_exists_result._mapping)
            approval_exists = (result_dict.get("count") or 0) > 0

        # Status-based permissions
        if status_id == 21:  # Drafted
            permissions["canOpen"] = True
            permissions["canCancelDraft"] = True
            permissions["canSave"] = True
        elif status_id == 1:  # Open
            permissions["canSave"] = True
            if approval_exists:
                # Approval hierarchy exists — check if user has approval level 1
                user_level_query = get_user_approval_level()
                user_level_rows = db.execute(
                    user_level_query,
                    {"menu_id": menu_id, "branch_id": branch_id, "user_id": user_id}
                ).fetchall()

                if user_level_rows:
                    user_levels = [dict(r._mapping).get("approval_level") for r in user_level_rows]
                    if 1 in user_levels:
                        permissions["canApprove"] = True
            else:
                # No approval hierarchy — check if user has edit access
                permissions["canApprove"] = _user_has_edit_access(
                    user_id, branch_id, menu_id, db
                )
        elif status_id == 6:  # Cancelled
            permissions["canReopen"] = True
            permissions["canClone"] = True
            permissions["canViewApprovalLog"] = True
        elif status_id == 4:  # Rejected
            permissions["canReopen"] = True
            permissions["canClone"] = True
            permissions["canViewApprovalLog"] = True
        elif status_id == 3:  # Approved
            permissions["canViewApprovalLog"] = True
            permissions["canClone"] = True
        elif status_id == 5:  # Closed
            permissions["canViewApprovalLog"] = True

        # Approval/Reject permissions (only for status_id = 20)
        if status_id == 20:  # Pending Approval
            permissions["canSave"] = True
            permissions["canViewApprovalLog"] = True

            if approval_exists:
                # Approval hierarchy exists — check if user's level matches current level
                if current_approval_level is not None:
                    user_level_query = get_user_approval_level()
                    user_level_rows = db.execute(
                        user_level_query,
                        {"menu_id": menu_id, "branch_id": branch_id, "user_id": user_id}
                    ).fetchall()

                    if user_level_rows:
                        user_levels = [dict(r._mapping).get("approval_level") for r in user_level_rows]
                        level_matches = current_approval_level in user_levels
                        logger.info(
                            f"[PermCheck] user_id={user_id} menu_id={menu_id} branch_id={branch_id} "
                            f"user_levels={user_levels} doc_level={current_approval_level} "
                            f"match={level_matches}"
                        )
                        if level_matches:
                            permissions["canApprove"] = True
                            permissions["canReject"] = True
                    else:
                        logger.warning(
                            f"[PermCheck] No approval_mst entry for user_id={user_id} "
                            f"menu_id={menu_id} branch_id={branch_id}"
                        )
                else:
                    logger.warning(
                        f"[PermCheck] current_approval_level is None for status=20, "
                        f"menu_id={menu_id} branch_id={branch_id}"
                    )
            else:
                # No approval hierarchy — check if user has edit access
                logger.info(
                    f"[PermCheck] No approval hierarchy for menu_id={menu_id} "
                    f"branch_id={branch_id}, checking edit access"
                )
                has_edit = _user_has_edit_access(user_id, branch_id, menu_id, db)
                if has_edit:
                    permissions["canApprove"] = True
                    permissions["canReject"] = True

        return permissions
    except Exception as e:
        logger.exception("Error calculating approval permissions")
        # Return default permissions (all False) on error
        return permissions


def _user_has_edit_access(
    user_id: int,
    branch_id: int,
    menu_id: int,
    db: Session,
) -> bool:
    """Check if user has edit access (access_type_id >= 4) for a menu and branch."""
    edit_access_query = get_user_edit_access()
    edit_access_result = db.execute(
        edit_access_query,
        {"user_id": user_id, "branch_id": branch_id, "menu_id": menu_id}
    ).fetchone()

    if edit_access_result:
        max_access_type = dict(edit_access_result._mapping).get("max_access_type_id")
        if max_access_type is not None and max_access_type >= 4:
            return True
    return False
