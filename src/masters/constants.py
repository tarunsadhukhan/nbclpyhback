"""Constants for the masters module."""

# Lifecycle status values for item_bom_hdr_mst.bom_status.
# Independent from status_id / status_mst (which drives BOM Costing approval).
# Interchangeable: any user with edit permission may switch between these freely.
BOM_STATUS_VALUES = ("New", "Certified", "Under Development", "Closed")
