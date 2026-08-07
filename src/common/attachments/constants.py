"""Constants & allow-lists for the generic attachment subsystem.

Keep these tight — the router uses them to validate user-supplied
`module` / `file_type` form fields and to map (module, file_type) to a
source-table column that should track the active attachment_id.
"""

ALLOWED_MIME = {"application/pdf"}
MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_MODULES = {"billpass", "proc_billpass"}

# Allowed file_types per module. Used to validate the multipart form input.
ALLOWED_FILE_TYPES = {
    "billpass": {"invoice", "challan"},
    "proc_billpass": {"invoice", "ewaybill"},
}

# Maps (module, file_type) → (source_table, primary_key_column, attachment_column).
# The router uses this allow-list to safely build the UPDATE / NULL-ing SQL
# that writes the new attachment_id back to the source table (e.g.
# jute_mr.invoice_upload / jute_mr.challan_upload).
#
# NEVER interpolate user input into SQL — only column names looked up via
# this dict are eligible for the dynamic UPDATE in query.py.
MODULE_COLUMN_MAP = {
    ("billpass", "invoice"): ("jute_mr", "jute_mr_id", "invoice_upload"),
    ("billpass", "challan"): ("jute_mr", "jute_mr_id", "challan_upload"),
}
