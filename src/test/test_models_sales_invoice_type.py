from src.models.sales import InvoiceTypeMst, InvoiceTypeCoMap


def test_invoice_type_mst_columns_present():
    columns = InvoiceTypeMst.__table__.c
    assert "invoice_type_id" in columns
    assert "invoice_type_name" in columns


def test_invoice_type_co_map_columns_and_fk():
    columns = InvoiceTypeCoMap.__table__.c
    assert "invoice_type_co_map_id" in columns
    assert "co_id" in columns
    assert "invoice_type_id" in columns

    fk_targets = {fk.target_fullname for fk in columns["invoice_type_id"].foreign_keys}
    assert "invoice_type_mst.invoice_type_id" in fk_targets
