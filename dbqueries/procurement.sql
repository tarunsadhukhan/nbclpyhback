CREATE TABLE currency_mst (
    currency_id INT PRIMARY KEY AUTO_INCREMENT,
    currency_prefix VARCHAR(25)
);


INSERT INTO currency_mst (currency_prefix) VALUES
  ('USD'),  -- US Dollar
  ('EUR'),  -- Euro
  ('INR'),  -- Indian Rupee
  ('GBP'),  -- British Pound
  ('JPY'),  -- Japanese Yen
  ('CNY'),  -- Chinese Yuan
  ('AUD'),  -- Australian Dollar
  ('CAD'),  -- Canadian Dollar
  ('CHF'),  -- Swiss Franc
  ('SGD'),  -- Singapore Dollar
  ('NZD'),  -- New Zealand Dollar
  ('ZAR'),  -- South African Rand
  ('HKD'),  -- Hong Kong Dollar
  ('THB'),  -- Thai Baht
  ('AED');  -- UAE Dirham


  
CREATE TABLE co_config (
    co_id INT,
    currency_id INT,
    india_gst BOOLEAN,
    india_tds BOOLEAN,
    india_tcs BOOLEAN,
    back_date_allowable BOOLEAN,
    indent_required BOOLEAN,
    po_required BOOLEAN,
    material_inspection BOOLEAN,
    quotation_required BOOLEAN,
    do_required BOOLEAN,
    gst_linked BOOLEAN,
    update_by INT,
    update_date DATETIME,
    PRIMARY KEY (co_id),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (currency_id) REFERENCES currency_mst(currency_id)
);


CREATE TABLE co_config (
    co_id INT,
    currency_id INT,
    india_gst BOOLEAN,
    india_tds BOOLEAN,
    india_tcs BOOLEAN,
    back_date_allowable BOOLEAN,
    indent_required BOOLEAN,
    po_required BOOLEAN,
    material_inspection BOOLEAN,
    quotation_required BOOLEAN,
    do_required BOOLEAN,
    gst_linked BOOLEAN,
    PRIMARY KEY (co_id),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (currency_id) REFERENCES currency_mst(currency_id)
);

  
  CREATE TABLE tax_type_mst (
    tax_type_id INT PRIMARY KEY AUTO_INCREMENT,
    tax_type_name VARCHAR(255) UNIQUE
);

CREATE TABLE tax_mst (
    tax_id BIGINT PRIMARY KEY,
    updated_by BIGINT,
    update_date_time_time DATETIME,
    tax_name VARCHAR(255),
    tax_percentage DECIMAL(10,2),
    is_active BOOLEAN,
    tax_type_id INT,
    FOREIGN KEY (tax_type_id) REFERENCES tax_type_mst(tax_type_id)  
);

CREATE TABLE party_types_mst (
    party_types_mst_id INT PRIMARY KEY,
    party_types_mst_name VARCHAR(25),
    party_types_mst_prefix VARCHAR(25)
);



CREATE TABLE entity_type_mst (
    entity_type_id INT PRIMARY KEY,
    entity_type_name VARCHAR(30)
);

CREATE TABLE party_mst (
    party_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    active INT,
    prefix VARCHAR(25),
    update_date_time DATETIME,
    updated_by INT,
    phone_no VARCHAR(25),
    cin VARCHAR(25),
    co_id INT,
    supp_contact_person VARCHAR(255),
    supp_contact_designation VARCHAR(255),
    supp_email_id VARCHAR(255),
    supp_code VARCHAR(25),
    party_pan_no VARCHAR(255),
    entity_type_id INT,
    supp_name VARCHAR(255),
    msme_certified INT,
    country_id INT,
    party_type_id VARCHAR(255),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (entity_type_id) REFERENCES entity_type_mst(entity_type_id),
    FOREIGN KEY (country_id) REFERENCES country_mst(country_id)
    -- You can add a foreign key for party_type_id if needed
);

CREATE TABLE party_branch_mst (
    party_mst_branch_id INT AUTO_INCREMENT PRIMARY KEY,
    party_id INT,
    active INT,
    update_date_time DATETIME,
    updated_by INT,
    gst_no VARCHAR(255),
    address VARCHAR(255),
    address_additional VARCHAR(255),
    zip_code INTEGER,
    city_id INT,
    contact_no VARCHAR(25),
    contact_person VARCHAR(255),
    FOREIGN KEY (party_id) REFERENCES party_mst(party_id),
    FOREIGN KEY (city_id) REFERENCES city_mst(city_id)
);



CREATE TABLE expense_type_master (
    expense_type_id INT PRIMARY KEY AUTO_INCREMENT,
    expense_type_name VARCHAR(25) UNIQUE
);

CREATE TABLE uom_mst (
    uom_id INT PRIMARY KEY AUTO_INCREMENT,
    active BOOLEAN,
    uom_name VARCHAR(255)
);

CREATE TABLE item_type_master (
    item_type_id INT PRIMARY KEY AUTO_INCREMENT,
    item_type_name VARCHAR(25) UNIQUE
);

CREATE TABLE item_grp_mst (
    item_grp_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    parent_grp_id BIGINT,
    active VARCHAR(255),
    co_id INTEGER,
    updated_by VARCHAR(255),
    update_date_time DATETIME,
    item_grp_name VARCHAR(255),
    item_grp_code VARCHAR(255),
    purchase_code BIGINT,
    item_type_id INT,
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (item_type_id) REFERENCES item_type_master(item_type_id)
);

CREATE TABLE item_mst (
    item_id INT PRIMARY KEY AUTO_INCREMENT,
    active INT,
    update_date_time DATETIME,
    updated_by INT,
    item_grp_id BIGINT,
    item_code VARCHAR(255),
    tangible BOOLEAN,
    item_name VARCHAR(255),
    item_photo MEDIUMTEXT,
    legacy_item_code VARCHAR(255),
    hsn_code VARCHAR(255),
    uom_id INT,
    tax_percentage DOUBLE,
    saleable BOOLEAN,
    consumable BOOLEAN,
    purchaseable BOOLEAN,
    manufacturable BOOLEAN,
    assembly BOOLEAN,
    uom_rounding INT,
    rate_rounding INT,
    FOREIGN KEY (item_grp_id) REFERENCES item_grp_mst(item_grp_id),
    FOREIGN KEY (uom_id) REFERENCES uom_mst(uom_id))
;


CREATE TABLE item_make (
    item_make_id INT PRIMARY KEY AUTO_INCREMENT,
    item_make_name VARCHAR(255),
    item_grp_id BIGINT,
    FOREIGN KEY (item_grp_id) REFERENCES item_grp_mst(item_grp_id)
);


CREATE TABLE item_minmax_mst (
    item_minmax_id INT PRIMARY KEY AUTO_INCREMENT,
    branch_id INT,
    item_id INT,
    minqty DOUBLE,
    maxqty DOUBLE,
    min_order_qty DOUBLE,
    lead_time INT,
    updated_by INT,
    updated_date_time DATETIME,
    active INT,
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id),
    FOREIGN KEY (item_id) REFERENCES item_mst(item_id)
);


CREATE TABLE uom_item_map_mst (
    uom_item_map_id INT PRIMARY KEY AUTO_INCREMENT,
    item_id INT,
    map_from_id INT,
    map_to_id INT,
    is_fixed INT,
    relation_value DOUBLE,
    rounding INT,
    FOREIGN KEY (item_id) REFERENCES item_mst(item_id),
    FOREIGN KEY (map_from_id) REFERENCES uom_mst(uom_id),
    FOREIGN KEY (map_to_id) REFERENCES uom_mst(uom_id)
);



CREATE TABLE dept_mst (
    dept_id INT PRIMARY KEY AUTO_INCREMENT,
    branch_id INT,
    updated_by INT,
    dept_desc VARCHAR(30),
    dept_code VARCHAR(30),
    order_id INT,
    update_date_time DATETIME,
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id)
);

CREATE TABLE sub_dept_mst (
    sub_dept_id INT PRIMARY KEY AUTO_INCREMENT,
    updated_by INT,
    sub_dept_name VARCHAR(25),
    sub_dept_code VARCHAR(25),
    sub_dept_desc VARCHAR(30),
    dept_id INT,
    update_date_time DATETIME,
    FOREIGN KEY (dept_id) REFERENCES dept_mst(dept_id)
);

CREATE TABLE warehouse_mst (
    warehouse_id INT PRIMARY KEY AUTO_INCREMENT,
    warehouse_name VARCHAR(30),
    update_date_time DATETIME,
    updated_by INT,
    warehouse_type VARCHAR(20),
    branch_id INT,
    parent_warehouse_id INT,
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id)
    -- Add parent_warehouse_id foreign key if needed
);


CREATE TABLE expense_type_mst (
    expense_type_id INT PRIMARY KEY AUTO_INCREMENT,
    expense_type_name VARCHAR(45),
    active INT
);

CREATE TABLE machine_type_mst (
    machine_type_id INT PRIMARY KEY AUTO_INCREMENT,
    machine_type_name VARCHAR(255)
);


CREATE TABLE machine_mst (
    machine_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    dept_id BIGINT,
    machine_name FLOAT,
    machine_type_id INT,
    updated_by INT,
    remarks VARCHAR(255),
    FOREIGN KEY (dept_id) REFERENCES dept_mst(dept_id)
);


CREATE TABLE machine_mst (
    machine_id INT PRIMARY KEY AUTO_INCREMENT,
    dept_id INT,
    machine_name VARCHAR(255),
    machine_type_id INT,
    updated_by INT,
    remarks VARCHAR(255),
    FOREIGN KEY (dept_id) REFERENCES dept_mst(dept_id)
);

CREATE TABLE status_mst (
    status_id INT PRIMARY KEY AUTO_INCREMENT,
    status_name VARCHAR(255),
    update_date_time DATETIME,
    updated_by INT,
    status_grp VARCHAR(255)
);


CREATE TABLE project_mst (
    project_id INT PRIMARY KEY AUTO_INCREMENT,
    prj_desc VARCHAR(255),
    prj_end_dt DATE,
    prj_name VARCHAR(255),
    prj_start_dt DATE,
    status_id INT,
    active INT,
    branch_id INT,
    updated_by INT,
    update_date_time TIMESTAMP,
    party_id INT,
    dept_id INT,
    FOREIGN KEY (status_id) REFERENCES status_mst(status_id),
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id),
    FOREIGN KEY (dept_id) REFERENCES dept_mst(dept_id),
    FOREIGN KEY (party_id) REFERENCES party_mst(party_id)
    -- Add more foreign keys as needed
);


CREATE TABLE machine_mst (
    machine_id INT PRIMARY KEY AUTO_INCREMENT,
    dept_id INT,
    machine_name VARCHAR(255),
    machine_type_id INT,
    updated_by INT,
    remarks VARCHAR(255),
    FOREIGN KEY (dept_id) REFERENCES dept_mst(dept_id)
);

CREATE TABLE status_mst (
    status_id INT PRIMARY KEY AUTO_INCREMENT,
    status_name VARCHAR(255),
    update_date_time DATETIME,
    updated_by INT,
    status_grp VARCHAR(255)
);


CREATE TABLE project_mst (
    project_id INT PRIMARY KEY AUTO_INCREMENT,
    prj_desc VARCHAR(255),
    prj_end_dt DATE,
    prj_name VARCHAR(255),
    prj_start_dt DATE,
    status_id INT,
    active INT,
    branch_id INT,
    updated_by INT,
    update_date_time TIMESTAMP,
    party_id INT,
    dept_id INT,
    FOREIGN KEY (status_id) REFERENCES status_mst(status_id),
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id),
    FOREIGN KEY (dept_id) REFERENCES dept_mst(dept_id),
    FOREIGN KEY (party_id) REFERENCES party_mst(party_id)
    -- Add more foreign keys as needed
);


CREATE TABLE cost_factor_mst (
    cost_factor_id INT PRIMARY KEY AUTO_INCREMENT,
    cost_factor_name VARCHAR(255),
    cost_factor_desc VARCHAR(255)
);


CREATE TABLE proc_indent (
    indent_id INT PRIMARY KEY AUTO_INCREMENT,
    indent_date DATE,
    indent_no INT,
    active BOOLEAN,
    indent_type_id VARCHAR(25),
    remarks VARCHAR(500),
    branch_id INT,
    expense_type_id INT,
    project_id INT,
    dept_id INT,
    updated_by INT,
    updated_date_time INT,
    status_id INT,
    indent_title VARCHAR(255),
    appoval_level INT,
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id),
    FOREIGN KEY (expense_type_id) REFERENCES expense_type_mst(expense_type_id),
    FOREIGN KEY (status_id) REFERENCES status_mst(status_id)
    -- Add more foreign keys if needed (for project_id, dept_id, supplier_id, etc.)
);

CREATE TABLE proc_indent_dtl (
    indent_dtl_id INT PRIMARY KEY AUTO_INCREMENT,
    indent_id INT,
    required_by_days INT,
    active BOOLEAN,
    item_id INT,
    qty DOUBLE,
    uom_id INT,
    remarks VARCHAR(599),
    updated_by INT,
    updated_date_time DATETIME,
    item_make_id INT,
    dept_id INT,
    state INT,
    FOREIGN KEY (indent_id) REFERENCES proc_indent(indent_id),
    FOREIGN KEY (item_id) REFERENCES item_mst(item_id),
    FOREIGN KEY (uom_id) REFERENCES uom_mst(uom_id),
    FOREIGN KEY (item_make_id) REFERENCES item_make(item_make_id)
);

CREATE TABLE proc_price_enquiry_response (
    proc_price_enquiry_response_id INT PRIMARY KEY AUTO_INCREMENT,
    enquiry_id INT,
    date DATE,
    updated_by INT,
    update_date_time DATETIME,
    updated_by_ip VARCHAR(30),
    supplier_id INT,
    delivery_days INT,
    terms_conditions VARCHAR(255),
    remarks VARCHAR(255),
    gross_amount DOUBLE,
    net_amount DOUBLE,
    FOREIGN KEY (enquiry_id) REFERENCES proc_enquiry(enquiry_id)
);

CREATE TABLE proc_price_enquiry_response_dtl (
    proc_price_enquiry_response_dtl_id INT PRIMARY KEY AUTO_INCREMENT,
    enquiry_dtl_id INT,
    item_id INT,
    item_make_id INT,
    uom_id INT,
    qty DOUBLE,
    rate DOUBLE,
    discount_mode INT,
    discount_value DOUBLE,
    discount_amount DOUBLE,
    gross_amount DOUBLE,
    net_amount DOUBLE,
    FOREIGN KEY (enquiry_dtl_id) REFERENCES proc_enquiry_dtl(enquiry_dtl_id),
    FOREIGN KEY (item_id) REFERENCES item_mst(item_id),
    FOREIGN KEY (item_make_id) REFERENCES item_make(item_make_id),
    FOREIGN KEY (uom_id) REFERENCES uom_mst(uom_id)
);

CREATE TABLE proc_po (
    po_id INT PRIMARY KEY AUTO_INCREMENT,
    updated_by INT,
    updated_date_time DATETIME,
    credit_days INT,
    delivery_instructions VARCHAR(255),
    expected_delivery_days INT,
    footer_notes VARCHAR(255),
    po_date DATE,
    po_approve_date DATE,
    po_no VARCHAR(30) UNIQUE,
    remarks VARCHAR(255),
    delivery_mode VARCHAR(30),
    terms_conditions VARCHAR(255),
    branch_id INT,
    price_enquiry_id VARCHAR(255),
    project_id INT,
    supplier_id INT,
    status_id INT,
    supplier_branch_id INT,
    billing_branch_id INT,
    shipping_branch_id INT,
    total_amount DOUBLE,
    net_amount DOUBLE,
    advance_type INT,
    advance_value DOUBLE,
    advance_amount DOUBLE,
    contact_no VARCHAR(25),
    contact_person VARCHAR(30),
    approval_level INT,
    expense_type_id INT,
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id),
    FOREIGN KEY (status_id) REFERENCES status_mst(status_id)
    -- Add other FKs as needed for project_id, supplier_id, etc.
);


CREATE TABLE additional_charges_master (
    additional_charges_id INT PRIMARY KEY AUTO_INCREMENT,
    additional_charges_name VARCHAR(255),
    default_value DOUBLE
);


CREATE TABLE proc_po_additional (
    po_additional_id INT PRIMARY KEY AUTO_INCREMENT,
    po_id INT,
    additional_charges_id INT,
    qty INT,
    rate DOUBLE,
    net_amount DOUBLE,
    remarks VARCHAR(255),
    FOREIGN KEY (po_id) REFERENCES proc_po(po_id),
    FOREIGN KEY (additional_charges_id) REFERENCES additional_charges_master(additional_charges_id)
);


CREATE TABLE proc_po_dtl (
    po_dtl_id INT PRIMARY KEY AUTO_INCREMENT,
    po_id INT,
    item_id INT,
    hsn_code VARCHAR(255),
    item_make_id INT,
    qty DOUBLE,
    rate DOUBLE,
    uom_id INT,
    remarks VARCHAR(255),
    discount_mode INT,
    discount_value DOUBLE,
    discount_amount DOUBLE,
    active INT,
    indent_dtl_id INT,
    updated_by INT,
    update_date_time DATETIME,
    state INT,
    FOREIGN KEY (po_id) REFERENCES proc_po(po_id),
    FOREIGN KEY (item_id) REFERENCES item_mst(item_id),
    FOREIGN KEY (item_make_id) REFERENCES item_make(item_make_id),
    FOREIGN KEY (uom_id) REFERENCES uom_mst(uom_id),
    FOREIGN KEY (indent_dtl_id) REFERENCES proc_indent_dtl(indent_dtl_id)
);


CREATE TABLE proc_po_dtl_cancel (
    po_dtl_cancel_id INT PRIMARY KEY AUTO_INCREMENT,
    po_dtl_id INT,
    cancel_qty DOUBLE,
    cancel_date DATE,
    cancel_by INT,
    FOREIGN KEY (po_dtl_id) REFERENCES proc_po_dtl(po_dtl_id)
);

CREATE TABLE po_gst (
    po_gst_id INT PRIMARY KEY AUTO_INCREMENT,
    po_dtl_id INT,
    po_additional_id INT,
    tax_pct DOUBLE,
    stax_percentage DOUBLE,
    s_tax_amount DOUBLE,
    i_tax_amount DOUBLE,
    i_tax_percentage DOUBLE,
    c_tax_amount DOUBLE,
    c_tax_percentage DOUBLE,
    tax_amount DOUBLE,
    FOREIGN KEY (po_dtl_id) REFERENCES proc_po_dtl(po_dtl_id),
    FOREIGN KEY (po_additional_id) REFERENCES proc_po_additional(po_additional_id)
);


CREATE TABLE proc_inward (
    inward_id INT PRIMARY KEY AUTO_INCREMENT,
    inward_sequence_no INT,
    supplier_id INT,
    vehicle_number VARCHAR(25),
    driver_name VARCHAR(30),
    driver_contact_number VARCHAR(25),
    inward_date DATE,
    despatch_remarks VARCHAR(500),
    receipts_remarks VARCHAR(500),
    update_date_time DATETIME,
    updated_by INT,
    invoice_date DATE,
    invoice_recvd_date DATE,
    invoice_due_date DATE,
    invoice_amount DOUBLE,
    challan_no VARCHAR(255),
    challan_date DATE,
    consignment_date DATE,
    consignment_no VARCHAR(255),
    ewaybillno VARCHAR(255),
    ewaybill_date DATE,
    bill_branch_id INT,
    ship_branch_id INT,
    inspection_check VARCHAR(30),
    inspection_date DATE,
    inspection_approved_by INT,
    sr_no VARCHAR(30),
    sr_date DATE,
    sr_approved_by INT,
    sr_value DOUBLE,
    sr_remarks VARCHAR(500),
    sr_status INT,
    billpass_no VARCHAR(30),
    billpass_date DATE,
    billpass_approve_date DATE,
    billpass_approved_by INT,
    billpass_status INT,
    round_off_value DOUBLE,
    branch_id INT,
    project_id INT,
    internal_no VARCHAR(255),
    customer_id INT,
    gross_amount DOUBLE,
    net_amount DOUBLE,
    FOREIGN KEY (bill_branch_id) REFERENCES branch_mst(branch_id),
    FOREIGN KEY (ship_branch_id) REFERENCES branch_mst(branch_id),
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id)
    -- You can add other FKs for supplier_id, project_id, customer_id if needed
);

CREATE TABLE tds_mst (
    tds_id INT PRIMARY KEY AUTO_INCREMENT,
    tds_name VARCHAR(25),
    tds_percentage DOUBLE,
    tds_single_transaction DOUBLE,
    tds_ytd_transaction DOUBLE,
    tds_entity_type_id VARCHAR(25)
);

CREATE TABLE proc_tds (
    proc_tds_id INT PRIMARY KEY AUTO_INCREMENT,
    inward_id INT,
    itc_applicable INT,
    tds_id INT,
    tds_pctg DOUBLE,
    tds_amount DOUBLE,
    tcs_amount DOUBLE,
    FOREIGN KEY (tds_id) REFERENCES tds_mst(tds_id)
);

CREATE TABLE proc_inward_dtl (
    inward_dtl_id INT PRIMARY KEY AUTO_INCREMENT,
    inward_id INT NOT NULL,
    po_dtl_id BIGINT,
    item_id INT,
    item_make_id INT,
    hsn_code VARCHAR(50),
    description VARCHAR(255),
    remarks VARCHAR(255),
    challan_qty DOUBLE,
    inward_qty DOUBLE,
    approved_qty DOUBLE,
    rejected_qty DOUBLE,
    reasons VARCHAR(255),
    uom_id INT,
    rate DOUBLE,
    amount DOUBLE,
    discount_mode DOUBLE,
    discount_value DOUBLE,
    discount_amount DOUBLE,
    warehouse_id INT,
    active BOOLEAN,
    status_id INT,
    update_date_time DATETIME,
    updated_by INT,
    FOREIGN KEY (inward_id) REFERENCES proc_inward(inward_id),
    FOREIGN KEY (item_id) REFERENCES item_mst(item_id),
    FOREIGN KEY (item_make_id) REFERENCES item_make(item_make_id),
    FOREIGN KEY (uom_id) REFERENCES uom_mst(uom_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouse_mst(warehouse_id),
    FOREIGN KEY (status_id) REFERENCES status_mst(status_id)
);

CREATE TABLE proc_gst (
    gst_invoice_type INT PRIMARY KEY AUTO_INCREMENT,
    proc_inward_dtl INT,
    tax_pct DOUBLE,
    stax_percentage DOUBLE,
    s_tax_amount DOUBLE,
    i_tax_amount DOUBLE,
    i_tax_percentage DOUBLE,
    c_tax_amount DOUBLE,
    c_tax_percentage DOUBLE,
    tax_amount DOUBLE,
    FOREIGN KEY (proc_inward_dtl) REFERENCES proc_inward_dtl(inward_dtl_id)
);


CREATE TABLE drcr_note (
    debit_credit_note_id INT PRIMARY KEY AUTO_INCREMENT,
    date DATE,
    adjustment_type INT,
    inward_id INT,
    remarks VARCHAR(255),
    status_id INT,
    auto_create INT,
    updated_by INT,
    update_date_timetime DATETIME,
    approved_by INT,
    approved_date DATE,
    gross_amount DOUBLE,
    net_amount DOUBLE,
    round_off_value DOUBLE,
    FOREIGN KEY (inward_id) REFERENCES proc_inward(inward_id),
    FOREIGN KEY (status_id) REFERENCES status_mst(status_id)
);

CREATE TABLE drcr_note_dtl (
    drcr_note_dtl_id INT PRIMARY KEY AUTO_INCREMENT,
    inward_dtl_id INT,
    debitnote_type INT,
    quantity DOUBLE,
    rate DOUBLE,
    discount_mode INT,
    discount_value DOUBLE,
    discount_amount DOUBLE,
    FOREIGN KEY (inward_dtl_id) REFERENCES proc_inward_dtl(inward_dtl_id)
);

CREATE TABLE drcr_note_dtl_gst (
    drcr_note_dtl_gst_id INT PRIMARY KEY AUTO_INCREMENT,
    drcr_note_dtl_id INT,
    cgst_amount DOUBLE,
    igst_amount DOUBLE,
    sgst_amount DOUBLE,
    active BOOLEAN,
    FOREIGN KEY (drcr_note_dtl_id) REFERENCES drcr_note_dtl(drcr_note_dtl_id)
);

CREATE TABLE issue_hdr (
    issue_id INT PRIMARY KEY AUTO_INCREMENT,
    branch_id INT,
    dept_id INT,
    issue_pass_no INT,
    issue_pass_print_no VARCHAR(255),
    active BOOLEAN,
    issue_date DATE,
    item_id INT,
    approved_date DATE,
    approved_by INT,
    status_id INT,
    issued_to VARCHAR(255),
    req_by VARCHAR(255),
    project_id INT,
    customer_id INT,
    internal_note VARCHAR(255),
    updated_by INT,
    update_date_time DATETIME,
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id),
    FOREIGN KEY (dept_id) REFERENCES dept_mst(dept_id),
    FOREIGN KEY (item_id) REFERENCES item_mst(item_id),
    FOREIGN KEY (status_id) REFERENCES status_mst(status_id)
    -- Add more FKs as required (e.g., project_id, customer_id)
);


CREATE TABLE issue_li (
    issue_li_id INT PRIMARY KEY AUTO_INCREMENT,
    issue_id INT NOT NULL,
    item_id INT,
    uom_id INT,
    req_quantity DOUBLE,
    issue_qty DOUBLE,
    expense_type_id INT,
    cost_factor_id INT,
    machine_id INT,
    inward_dtl_id INT,
    remarks VARCHAR(255),
    update_date_time DATETIME,
    updated_by INT,
    FOREIGN KEY (issue_id) REFERENCES issue_hdr(issue_id),
    FOREIGN KEY (item_id) REFERENCES item_mst(item_id),
    FOREIGN KEY (uom_id) REFERENCES uom_mst(uom_id),
    FOREIGN KEY (expense_type_id) REFERENCES expense_type_mst(expense_type_id),
    FOREIGN KEY (cost_factor_id) REFERENCES cost_factor_mst(cost_factor_id),
    FOREIGN KEY (inward_dtl_id) REFERENCES proc_inward_dtl(inward_dtl_id)
    -- Add more FKs as needed
);

CREATE TABLE proc_transfer (
    transfer_id INT PRIMARY KEY AUTO_INCREMENT,
    transfer_type INT,
    transfer_no INT,
    transfer_sequence_no VARCHAR(25),
    transfer_date DATE,
    branch_id INT,
    scrap BOOLEAN,
    updated_by INT,
    update_date_timetime DATETIME,
    approved_by INT,
    approved_date DATE,
    remarks VARCHAR(255),
    status_id INT,
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id),
    FOREIGN KEY (status_id) REFERENCES status_mst(status_id)
);


CREATE TABLE proc_transfer_dtl (
    transfer_dtl_id INT PRIMARY KEY AUTO_INCREMENT,
    transfer_id INT,
    item_id INT,
    uom_id INT,
    qty DOUBLE,
    to_branch_id INT,
    from_warehouse_id INT,
    to_warehouse_id INT,
    reason VARCHAR(255),
    active BOOLEAN,
    updated_by INT,
    update_date_timetime DATETIME,
    FOREIGN KEY (transfer_id) REFERENCES proc_transfer(transfer_id),
    FOREIGN KEY (item_id) REFERENCES item_mst(item_id),
    FOREIGN KEY (uom_id) REFERENCES uom_mst(uom_id)
    -- Add FKs for to_branch_id, from_warehouse_id, to_warehouse_id as needed
);




