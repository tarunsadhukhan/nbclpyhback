-- Fix audit triggers on proc_price_enquiry_response / proc_price_enquiry_response_dtl (dev3).
-- The original triggers inserted into trigger_audit_logs columns that do not exist
-- (action, action_time, primary_key_val, old_data, new_data), so EVERY UPDATE/DELETE
-- on these tables failed with 1054 "Unknown column 'action' in 'field list'"
-- (broke PUT /api/priceEnquiry/update_response).
-- Correct columns per canonical audit triggers (e.g. after_approval_mst_update):
--   operation_type, changed_by, primary_key_value, old_value, new_value
--   (change_time is a TIMESTAMP with default, not inserted).
-- Rollback: re-create the previous trigger bodies (they were broken; rollback not recommended).
-- NOTE: apply via pymysql executing each statement separately (bodies contain semicolons).

DROP TRIGGER IF EXISTS trg_proc_price_enquiry_response_update;
DROP TRIGGER IF EXISTS trg_proc_price_enquiry_response_delete;
DROP TRIGGER IF EXISTS trg_proc_price_enquiry_response_dtl_update;
DROP TRIGGER IF EXISTS trg_proc_price_enquiry_response_dtl_delete;

CREATE TRIGGER trg_proc_price_enquiry_response_update
AFTER UPDATE ON proc_price_enquiry_response
FOR EACH ROW
BEGIN
  INSERT INTO trigger_audit_logs (
    table_name, operation_type, changed_by, primary_key_value, old_value, new_value
  ) VALUES (
    'proc_price_enquiry_response', 'UPDATE', NEW.updated_by, NEW.proc_price_enquiry_response_id,
    JSON_OBJECT(
      'enquiry_id', OLD.enquiry_id, 'date', OLD.date, 'updated_by', OLD.updated_by,
      'updated_date_time', OLD.updated_date_time, 'created_by_ip', OLD.created_by_ip,
      'supplier_id', OLD.supplier_id, 'delivery_days', OLD.delivery_days,
      'terms_conditions', OLD.terms_conditions, 'remarks', OLD.remarks,
      'gross_amount', OLD.gross_amount, 'net_amount', OLD.net_amount
    ),
    JSON_OBJECT(
      'enquiry_id', NEW.enquiry_id, 'date', NEW.date, 'updated_by', NEW.updated_by,
      'updated_date_time', NEW.updated_date_time, 'created_by_ip', NEW.created_by_ip,
      'supplier_id', NEW.supplier_id, 'delivery_days', NEW.delivery_days,
      'terms_conditions', NEW.terms_conditions, 'remarks', NEW.remarks,
      'gross_amount', NEW.gross_amount, 'net_amount', NEW.net_amount
    )
  );
END;

CREATE TRIGGER trg_proc_price_enquiry_response_delete
AFTER DELETE ON proc_price_enquiry_response
FOR EACH ROW
BEGIN
  INSERT INTO trigger_audit_logs (
    table_name, operation_type, changed_by, primary_key_value, old_value, new_value
  ) VALUES (
    'proc_price_enquiry_response', 'DELETE', OLD.updated_by, OLD.proc_price_enquiry_response_id,
    JSON_OBJECT(
      'enquiry_id', OLD.enquiry_id, 'date', OLD.date, 'updated_by', OLD.updated_by,
      'updated_date_time', OLD.updated_date_time, 'created_by_ip', OLD.created_by_ip,
      'supplier_id', OLD.supplier_id, 'delivery_days', OLD.delivery_days,
      'terms_conditions', OLD.terms_conditions, 'remarks', OLD.remarks,
      'gross_amount', OLD.gross_amount, 'net_amount', OLD.net_amount
    ),
    NULL
  );
END;

CREATE TRIGGER trg_proc_price_enquiry_response_dtl_update
AFTER UPDATE ON proc_price_enquiry_response_dtl
FOR EACH ROW
BEGIN
  INSERT INTO trigger_audit_logs (
    table_name, operation_type, changed_by, primary_key_value, old_value, new_value
  ) VALUES (
    'proc_price_enquiry_response_dtl', 'UPDATE', NEW.updated_by, NEW.proc_price_enquiry_response_dtl_id,
    JSON_OBJECT(
      'enquiry_dtl_id', OLD.enquiry_dtl_id, 'item_id', OLD.item_id, 'item_make_id', OLD.item_make_id,
      'uom_id', OLD.uom_id, 'qty', OLD.qty, 'rate', OLD.rate, 'discount_mode', OLD.discount_mode,
      'discount_value', OLD.discount_value, 'discount_amount', OLD.discount_amount,
      'gross_amount', OLD.gross_amount, 'net_amount', OLD.net_amount,
      'updated_by', OLD.updated_by, 'updated_date_time', OLD.updated_date_time
    ),
    JSON_OBJECT(
      'enquiry_dtl_id', NEW.enquiry_dtl_id, 'item_id', NEW.item_id, 'item_make_id', NEW.item_make_id,
      'uom_id', NEW.uom_id, 'qty', NEW.qty, 'rate', NEW.rate, 'discount_mode', NEW.discount_mode,
      'discount_value', NEW.discount_value, 'discount_amount', NEW.discount_amount,
      'gross_amount', NEW.gross_amount, 'net_amount', NEW.net_amount,
      'updated_by', NEW.updated_by, 'updated_date_time', NEW.updated_date_time
    )
  );
END;

CREATE TRIGGER trg_proc_price_enquiry_response_dtl_delete
AFTER DELETE ON proc_price_enquiry_response_dtl
FOR EACH ROW
BEGIN
  INSERT INTO trigger_audit_logs (
    table_name, operation_type, changed_by, primary_key_value, old_value, new_value
  ) VALUES (
    'proc_price_enquiry_response_dtl', 'DELETE', OLD.updated_by, OLD.proc_price_enquiry_response_dtl_id,
    JSON_OBJECT(
      'enquiry_dtl_id', OLD.enquiry_dtl_id, 'item_id', OLD.item_id, 'item_make_id', OLD.item_make_id,
      'uom_id', OLD.uom_id, 'qty', OLD.qty, 'rate', OLD.rate, 'discount_mode', OLD.discount_mode,
      'discount_value', OLD.discount_value, 'discount_amount', OLD.discount_amount,
      'gross_amount', OLD.gross_amount, 'net_amount', OLD.net_amount,
      'updated_by', OLD.updated_by, 'updated_date_time', OLD.updated_date_time
    ),
    NULL
  );
END;
