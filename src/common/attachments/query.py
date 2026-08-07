"""Raw SQL helpers for the file_attachment table and source-table back-refs.

All callable functions return SQLAlchemy `text()` objects with named bind
parameters. The dynamic-column helpers (`update_jute_mr_attachment_col`,
`clear_jute_mr_attachment_col`) accept a *pre-validated* column name —
the router resolves this via the `MODULE_COLUMN_MAP` allow-list in
constants.py, so no user input ever reaches an interpolated SQL string.
"""

from sqlalchemy import text


def insert_attachment():
    """Insert a new file_attachment row."""
    return text(
        """
        INSERT INTO file_attachment (
            co_id,
            module,
            entity_id,
            file_type,
            s3_bucket,
            s3_key,
            original_filename,
            mime_type,
            size_bytes,
            uploaded_by,
            active
        ) VALUES (
            :co_id,
            :module,
            :entity_id,
            :file_type,
            :s3_bucket,
            :s3_key,
            :original_filename,
            :mime_type,
            :size_bytes,
            :uploaded_by,
            1
        )
        """
    )


def soft_delete_existing_active():
    """Mark prior active attachment(s) for the same (module, entity_id, file_type) as inactive."""
    return text(
        """
        UPDATE file_attachment
           SET active = 0
         WHERE module = :module
           AND entity_id = :entity_id
           AND file_type = :file_type
           AND active = 1
        """
    )


def soft_delete_by_id():
    """Mark a specific attachment row as inactive."""
    return text(
        """
        UPDATE file_attachment
           SET active = 0
         WHERE attachment_id = :attachment_id
        """
    )


def get_attachment_by_id():
    """Fetch a single attachment row by id (regardless of active state)."""
    return text(
        """
        SELECT attachment_id,
               co_id,
               module,
               entity_id,
               file_type,
               s3_bucket,
               s3_key,
               original_filename,
               mime_type,
               size_bytes,
               uploaded_by,
               uploaded_at,
               active
          FROM file_attachment
         WHERE attachment_id = :attachment_id
        """
    )


def list_active_by_entity():
    """List all active attachments for a (module, entity_id) — most recent first."""
    return text(
        """
        SELECT attachment_id,
               co_id,
               module,
               entity_id,
               file_type,
               s3_bucket,
               s3_key,
               original_filename,
               mime_type,
               size_bytes,
               uploaded_by,
               uploaded_at,
               active
          FROM file_attachment
         WHERE module = :module
           AND entity_id = :entity_id
           AND active = 1
         ORDER BY uploaded_at DESC
        """
    )


# ─── Source-table back-references (allow-list driven) ─────────────────

# `column_name` MUST be sourced from constants.MODULE_COLUMN_MAP — the
# router resolves it from validated (module, file_type) form values and
# passes it in. Never accept this from raw client input.

def update_jute_mr_attachment_col(column_name: str):
    """Build SQL to write a new attachment_id onto jute_mr.<column_name>."""
    return text(
        f"UPDATE jute_mr SET {column_name} = :attachment_id WHERE jute_mr_id = :entity_id"
    )


def clear_jute_mr_attachment_col(column_name: str):
    """Build SQL to NULL out jute_mr.<column_name>."""
    return text(
        f"UPDATE jute_mr SET {column_name} = NULL WHERE jute_mr_id = :entity_id"
    )
