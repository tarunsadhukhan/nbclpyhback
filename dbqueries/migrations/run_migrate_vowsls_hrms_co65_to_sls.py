"""
Complete the HRMS migration for company 65 (ACPL, Anurashi Commotrade) from vowsls to sls.

Follow-up to run_migrate_vowsls_hrms_smallco_to_sls.py (2026-07-27), which excluded co 65 per the
original request. Verified state before this script: the 7 co-65 employees ALREADY EXIST in
sls.hrms_ed_personal_details (same eb_ids, same names, branch 25) from an earlier partial copy,
but they have NO official/address/bank/contact/esi/pf/resign rows, no attendance, no leave, and
their masters (sub_dept 120/164, designation 1210/1211, category 44, leave types 31/32) are absent.

This script therefore:
  - does NOT touch hrms_ed_personal_details (pre-existing rows are kept as-is);
  - appends identity rows for the 7 ebs to sls._map_hrms_eb_smallco (company_id=65) — NOTE for
    rollback: co-65 personal rows pre-existed and are NOT migration-owned; never delete personal
    rows for map rows with company_id=65;
  - creates the missing masters (ids preserved, all verified free);
  - migrates official + 6 ed child tables, daily_attendance (329), leave_transactions (8),
    leave_tran_details (8), leave_types (2), for the 7 employees.

ROLLBACK:
  DELETE d FROM sls.leave_tran_details d JOIN sls.leave_transactions t ON t.leave_transaction_id=d.ltran_id
         JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=t.eb_id AND m.company_id=65;
  DELETE t FROM sls.leave_transactions t JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=t.eb_id AND m.company_id=65;
  DELETE a FROM sls.daily_attendance a JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=a.eb_id AND m.company_id=65;
  -- child tables only; personal rows pre-existed, do NOT delete them:
  DELETE x FROM sls.hrms_ed_official_details x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id AND m.company_id=65;
  DELETE x FROM sls.hrms_ed_address_details x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id AND m.company_id=65;
  DELETE x FROM sls.hrms_ed_bank_details   x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id AND m.company_id=65;
  DELETE x FROM sls.hrms_ed_contact_details x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id AND m.company_id=65;
  DELETE x FROM sls.hrms_ed_esi x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id AND m.company_id=65;
  DELETE x FROM sls.hrms_ed_pf  x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id AND m.company_id=65;
  DELETE x FROM sls.hrms_ed_resign_details x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id AND m.company_id=65;
  DELETE FROM sls.hrms_leave_types_mst WHERE leave_type_id IN (31, 32);
  DELETE FROM sls.designation_mst WHERE designation_id IN (1210, 1211);
  DELETE FROM sls.category_mst    WHERE cata_id = 44;
  DELETE FROM sls.sub_dept_mst    WHERE sub_dept_id IN (120, 164);
  DELETE FROM sls.dept_mst        WHERE dept_id IN (<printed 'new dept' list>);
  DELETE FROM sls._map_hrms_eb_smallco WHERE company_id = 65;

Usage:
  python run_migrate_vowsls_hrms_co65_to_sls.py            # dry run (rolls back)
  python run_migrate_vowsls_hrms_co65_to_sls.py --commit   # apply
"""
import json
import sys
from collections import Counter
from pathlib import Path

import pymysql

COMMIT = "--commit" in sys.argv

ENV = {}
for line in (Path(__file__).resolve().parents[2] / "env" / "database.env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        ENV[k] = v

CO = 65
SCOPE_EB = f"(SELECT eb_id FROM vowsls.tbl_hrms_ed_personal_details WHERE company_id = {CO})"
MAP = "sls._map_hrms_eb_smallco"

conn = pymysql.connect(host=ENV["DATABASE_HOST"], user=ENV["DATABASE_USER"],
                       password=ENV["DATABASE_PASSWORD"], port=int(ENV["DATABASE_PORT"]),
                       autocommit=False)
cur = conn.cursor()


def one(sql, args=None):
    cur.execute(sql, args)
    return cur.fetchone()


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- pre-flight
(n,) = one(f"SELECT COUNT(*) FROM {MAP} WHERE company_id = {CO}")
if n:
    sys.exit(f"ABORT: {MAP} already has {n} rows for company {CO} — this script appears to have run.")

# every legacy co-65 eb must already exist in sls with the SAME name (identity map premise)
(total, matched) = one(f"""
    SELECT COUNT(*), SUM(t.eb_id IS NOT NULL AND UPPER(TRIM(t.first_name)) = UPPER(TRIM(s.first_name)))
      FROM vowsls.tbl_hrms_ed_personal_details s
      LEFT JOIN sls.hrms_ed_personal_details t ON t.eb_id = s.eb_id
     WHERE s.company_id = {CO}""")
if total != matched:
    sys.exit(f"ABORT: only {matched}/{total} co-{CO} employees exist in sls with matching names — "
             "identity-map premise broken; investigate before migrating.")
log(f"co-{CO} employees: {total}, all pre-existing in sls with matching names")

# no child rows may already exist for these ebs (else this script would duplicate them)
for t in ["hrms_ed_official_details", "hrms_ed_address_details", "hrms_ed_bank_details",
          "hrms_ed_contact_details", "hrms_ed_esi", "hrms_ed_pf", "hrms_ed_resign_details"]:
    (c,) = one(f"SELECT COUNT(*) FROM sls.`{t}` WHERE eb_id IN {SCOPE_EB}")
    if c:
        sys.exit(f"ABORT: sls.{t} already has {c} rows for co-{CO} employees")

try:
    # ------------------------------------------------------------ 1. eb map (identity)
    cur.execute(f"""
        INSERT INTO {MAP} (legacy_eb_id, new_eb_id, branch_id, company_id)
        SELECT p.eb_id, p.eb_id, o.branch_id, {CO}
          FROM vowsls.tbl_hrms_ed_personal_details p
          JOIN vowsls.tbl_hrms_ed_official_details o
            ON o.tbl_hrms_ed_official_detail_id = (
                 SELECT o2.tbl_hrms_ed_official_detail_id
                   FROM vowsls.tbl_hrms_ed_official_details o2
                  WHERE o2.eb_id = p.eb_id
                  ORDER BY o2.is_active DESC, o2.tbl_hrms_ed_official_detail_id DESC
                  LIMIT 1)
         WHERE p.company_id = {CO}""")
    log(f"eb map rows: {cur.rowcount}")

    # ------------------------------------------------- 2. dept_mst + sub_dept_mst
    cur.execute(f"""
        SELECT o.department_id, dm.dept_code, dm.dept_desc, md.dept_desc, md.dept_code,
               o.branch_id, COUNT(*)
          FROM vowsls.tbl_hrms_ed_official_details o
          JOIN vowsls.department_master dm ON dm.dept_id = o.department_id
          LEFT JOIN vowsls.master_department md
            ON md.mdept_id = dm.mdept_id AND md.company_id = dm.company_id
         WHERE o.eb_id IN {SCOPE_EB}
         GROUP BY 1,2,3,4,5,6""")
    dept_usage = cur.fetchall()
    branch_votes, dept_info = {}, {}
    for dept_id, dcode, ddesc, mdesc, mcode, branch, cnt in dept_usage:
        branch_votes.setdefault(dept_id, Counter())[branch] += cnt
        dept_info[dept_id] = (dcode, ddesc, mdesc or ddesc, mcode or dcode)

    new_dept_ids, new_sub_dept_ids = [], []
    for dept_id, (dcode, ddesc, parent_desc, parent_code) in sorted(dept_info.items()):
        if one("SELECT 1 FROM sls.sub_dept_mst WHERE sub_dept_id = %s", (dept_id,)):
            log(f"sub_dept {dept_id} already exists in sls — reused")
            continue
        branch = branch_votes[dept_id].most_common(1)[0][0]
        row = one("SELECT dept_id FROM sls.dept_mst WHERE branch_id = %s AND dept_desc = %s LIMIT 1",
                  (branch, parent_desc[:30]))
        if row:
            parent_id = row[0]
        else:
            cur.execute("INSERT INTO sls.dept_mst (branch_id, created_by, dept_desc, dept_code) "
                        "VALUES (%s, 0, %s, %s)", (branch, parent_desc[:30], (parent_code or "")[:30]))
            parent_id = cur.lastrowid
            new_dept_ids.append(parent_id)
        cur.execute("INSERT INTO sls.sub_dept_mst (sub_dept_id, updated_by, sub_dept_code, sub_dept_desc, dept_id) "
                    "VALUES (%s, 0, %s, %s, %s)", (dept_id, (dcode or "")[:25], (ddesc or "")[:30], parent_id))
        new_sub_dept_ids.append(dept_id)
    log(f"dept_mst created: {new_dept_ids}")
    log(f"sub_dept_mst created (legacy ids preserved): {new_sub_dept_ids}")

    # ------------------------------------------------------- 3. designation_mst
    cur.execute(f"""
        SELECT o.designation_id, o.branch_id, COUNT(*) FROM vowsls.tbl_hrms_ed_official_details o
         WHERE o.eb_id IN {SCOPE_EB} GROUP BY 1, 2""")
    desig_votes = {}
    for did, branch, cnt in cur.fetchall():
        desig_votes.setdefault(did, Counter())[branch] += cnt
    new_desig_ids = []
    for did in sorted(desig_votes):
        if one("SELECT 1 FROM sls.designation_mst WHERE designation_id = %s", (did,)):
            continue
        cur.execute("""
            INSERT INTO sls.designation_mst
                   (designation_id, branch_id, dept_id, desig, norms, time_piece, direct_indirect,
                    on_machine, machine_type, no_of_machines, cost_code, cost_description,
                    piece_rate_type, active, updated_by, updated_date_time)
            SELECT id, %s, NULL, desig, norms, time_piece, direct_indirect,
                   on_machine, machine_type, no_of_machines, cost_code, cost_description,
                   piece_rate_type, 1, 0, NOW()
              FROM vowsls.designation WHERE id = %s""",
            (desig_votes[did].most_common(1)[0][0], did))
        new_desig_ids.append(did)
    log(f"designation_mst created (ids preserved): {new_desig_ids}")

    # --------------------------------------------------------- 4. category_mst
    cur.execute(f"""
        SELECT o.catagory_id, o.branch_id, COUNT(*) FROM vowsls.tbl_hrms_ed_official_details o
         WHERE o.eb_id IN {SCOPE_EB} GROUP BY 1, 2""")
    cata_votes = {}
    for cid, branch, cnt in cur.fetchall():
        cata_votes.setdefault(cid, Counter())[branch] += cnt
    new_cata_ids = []
    for cid in sorted(cata_votes):
        if one("SELECT 1 FROM sls.category_mst WHERE cata_id = %s", (cid,)):
            continue
        cur.execute("""
            INSERT INTO sls.category_mst (cata_id, cata_code, cata_desc, branch_id, updated_by)
            SELECT cata_id, cata_code, cata_desc, %s, 0
              FROM vowsls.category_master WHERE cata_id = %s""",
            (cata_votes[cid].most_common(1)[0][0], cid))
        new_cata_ids.append(cid)
    log(f"category_mst created (ids preserved): {new_cata_ids}")

    # ------------------------------------------------- 5. hrms_leave_types_mst
    cur.execute(f"""
        INSERT INTO sls.hrms_leave_types_mst
               (leave_type_id, company_id, is_active, leave_type_code, leave_type_description,
                payable, updated_by, updated_date_time, Leave_hours)
        SELECT lt.leave_type_id, lt.company_id, lt.is_active, lt.leave_type_code,
               lt.leave_type_description, lt.payable, COALESCE(lt.updated_by, 0),
               lt.updated_date_time, lt.Leave_hours
          FROM vowsls.leave_types lt
         WHERE lt.company_id = {CO}
           AND NOT EXISTS (SELECT 1 FROM sls.hrms_leave_types_mst x
                            WHERE x.leave_type_id = lt.leave_type_id)""")
    log(f"hrms_leave_types_mst inserted: {cur.rowcount}")

    # ------------------------------------------- 6. hrms_ed_official_details
    cur.execute(f"""
        INSERT INTO sls.hrms_ed_official_details
               (eb_id, updated_by, active, sub_dept_id, catagory_id, designation_id, branch_id,
                date_of_join, probation_period, minimum_working_commitment, reporting_eb_id,
                emp_code, legacy_code, contractor_id, office_mobile_no, office_email_id, off_day)
        SELECT m.new_eb_id, COALESCE(o.updated_by, 0), o.is_active, o.department_id,
               o.catagory_id, o.designation_id, o.branch_id,
               o.date_of_join, o.probation_period, COALESCE(o.minimum_working_commitment, 0),
               COALESCE(mr.new_eb_id, o.reporting_eb_id),
               COALESCE(NULLIF(TRIM(o.emp_code), ''), CONCAT('MIG-', m.new_eb_id)),
               o.legacy_code, NULLIF(o.contractor_id, 0),
               o.office_mobile_no, o.office_email_id, 1
          FROM vowsls.tbl_hrms_ed_official_details o
          JOIN {MAP} m ON m.legacy_eb_id = o.eb_id AND m.company_id = {CO}
          LEFT JOIN {MAP} mr ON mr.legacy_eb_id = o.reporting_eb_id""")
    log(f"hrms_ed_official_details inserted: {cur.rowcount}")

    # --------------------------------------------------- 7. remaining ed child tables
    cur.execute(f"""
        INSERT INTO sls.hrms_ed_address_details
               (eb_id, address_type, country_id, state_id, city_name, address_line_1,
                address_line_2, pin_code, active, is_correspondent_address, updated_by)
        SELECT m.new_eb_id, COALESCE(a.address_type, 1), a.country_id, a.state_id, a.city_name,
               COALESCE(a.address_line_1, ''), a.address_line_2, COALESCE(a.pin_code, 0),
               COALESCE(a.is_active, 1), COALESCE(a.is_correspondent_address, 0),
               COALESCE(a.created_by, 0)
          FROM vowsls.tbl_hrms_ed_address_details a
          JOIN {MAP} m ON m.legacy_eb_id = a.eb_id AND m.company_id = {CO}""")
    log(f"hrms_ed_address_details inserted: {cur.rowcount}")

    cur.execute(f"""
        INSERT INTO sls.hrms_ed_bank_details
               (ifsc_code, bank_acc_no, active, updated_by, bank_name, is_verified,
                bank_branch_name, eb_id)
        SELECT COALESCE(b.ifsc_code, ''), COALESCE(b.bank_acc_no, ''), COALESCE(b.is_active, 1),
               COALESCE(b.updated_by, 0), COALESCE(b.bank_name, ''), COALESCE(b.is_verified, 0),
               COALESCE(b.bank_branch_name, ''), m.new_eb_id
          FROM vowsls.tbl_hrms_ed_bank_details b
          JOIN {MAP} m ON m.legacy_eb_id = b.eb_id AND m.company_id = {CO}""")
    log(f"hrms_ed_bank_details inserted: {cur.rowcount}")

    cur.execute(f"""
        INSERT INTO sls.hrms_ed_contact_details (eb_id, mobile_no, emergency_no, active, updated_by)
        SELECT m.new_eb_id, COALESCE(c.mobile_no, ''), c.emergency_no,
               COALESCE(c.is_active, 1), COALESCE(c.updated_by, 0)
          FROM vowsls.tbl_hrms_ed_contact_details c
          JOIN {MAP} m ON m.legacy_eb_id = c.eb_id AND m.company_id = {CO}""")
    log(f"hrms_ed_contact_details inserted: {cur.rowcount}")

    cur.execute(f"""
        INSERT INTO sls.hrms_ed_esi (eb_id, active, esi_no, updated_by, medical_policy_no)
        SELECT m.new_eb_id, COALESCE(e.is_active, 1), COALESCE(e.esi_no, ''),
               COALESCE(e.updated_by, 0), e.medical_policy_no
          FROM vowsls.tbl_hrms_ed_esi e
          JOIN {MAP} m ON m.legacy_eb_id = e.eb_id AND m.company_id = {CO}""")
    log(f"hrms_ed_esi inserted: {cur.rowcount}")

    cur.execute(f"""
        INSERT INTO sls.hrms_ed_pf
               (eb_id, active, updated_by, pf_date_of_join, pf_no, pf_uan_no, pf_transfer_no,
                pf_previous_no, nominee_name, relationship_name)
        SELECT m.new_eb_id, COALESCE(f.is_active, 1), COALESCE(f.updated_by, 0),
               f.pf_date_of_join, COALESCE(f.pf_no, ''), COALESCE(f.pf_uan_no, ''),
               f.pf_transfer_no, COALESCE(f.pf_previous_no, ''), f.nominee_name, f.relationship_name
          FROM vowsls.tbl_hrms_ed_pf f
          JOIN {MAP} m ON m.legacy_eb_id = f.eb_id AND m.company_id = {CO}""")
    log(f"hrms_ed_pf inserted: {cur.rowcount}")

    cur.execute(f"""
        INSERT INTO sls.hrms_ed_resign_details
               (eb_id, updated_by, active, date_of_inactive, fnf_date, net_settlement_amount,
                notice_days, release_date, resign_reasons, resign_remarks, resigned_date,
                type_of_resign, retired_date)
        SELECT m.new_eb_id, COALESCE(r.updated_by, 0), COALESCE(r.is_active, 1),
               r.date_of_inactive, r.fnf_date, r.net_settlement_amount, r.notice_days,
               r.release_date, r.resign_reasons, r.resign_remarks, r.resigned_date,
               r.type_of_resign, r.retired_date
          FROM vowsls.tbl_hrms_ed_resign_details r
          JOIN {MAP} m ON m.legacy_eb_id = r.eb_id AND m.company_id = {CO}""")
    log(f"hrms_ed_resign_details inserted: {cur.rowcount}")

    # ----------------------------------------------------- 8. daily_attendance
    cur.execute(f"""
        INSERT IGNORE INTO sls.daily_attendance
               (attendance_date, attendance_mark, attendance_source, attendance_type, branch_id,
                created_by, created_date_time, device_id, eb_code, eb_id, eb_no, entry_time,
                exit_time, idle_hours, is_active, remarks, spell, spell_hours, status_id,
                update_date_time, updated_by, worked_department_id, worked_designation_id,
                working_hours)
        SELECT a.attendance_date, a.attendance_mark, a.attendance_source, a.attendance_type,
               m.branch_id, a.created_by, a.created_date_time, a.device_id, a.eb_code,
               m.new_eb_id, a.eb_no, a.entry_time, a.exit_time, a.idle_hours, a.is_active,
               a.remarks, a.spell, a.spell_hours, a.status_id, a.update_date_time, a.updated_by,
               a.worked_department_id, a.worked_designation_id, a.working_hours
          FROM vowsls.daily_attendance a
          JOIN {MAP} m ON m.legacy_eb_id = a.eb_id AND m.company_id = {CO}
         WHERE a.company_id = {CO}""")
    log(f"daily_attendance inserted: {cur.rowcount}")

    # --------------------------------------------------- 9. leave transactions + details
    cur.execute(f"""
        INSERT INTO sls.leave_transactions
               (leave_transaction_id, branch_id, eb_id, leave_from_date, leave_ledger_id,
                leave_purpose, leave_to_date, leave_type_id, remarks, status, updated_by,
                updated_date_time)
        SELECT l.leave_transaction_id, m.branch_id, m.new_eb_id, l.leave_from_date,
               l.leave_ledger_id, l.leave_purpose, l.leave_to_date, l.leave_type_id, l.remarks,
               l.status, COALESCE(l.updated_by, 0), l.updated_date_time
          FROM vowsls.leave_transactions l
          JOIN {MAP} m ON m.legacy_eb_id = l.eb_id AND m.company_id = {CO}
         WHERE l.company_id = {CO}""")
    log(f"leave_transactions inserted: {cur.rowcount}")

    cur.execute(f"""
        INSERT INTO sls.leave_tran_details
               (lvd_tran_id, leave_date, ltran_id, auto_datetime_insert, created_by,
                company_id, is_active)
        SELECT d.lvd_tran_id, d.leave_date, d.ltran_id, d.auto_datetime_insert, d.created_by,
               d.company_id, d.is_active
          FROM vowsls.leave_tran_details d
         WHERE d.ltran_id IN (
                 SELECT l.leave_transaction_id FROM vowsls.leave_transactions l
                  JOIN {MAP} m ON m.legacy_eb_id = l.eb_id AND m.company_id = {CO}
                 WHERE l.company_id = {CO})
           AND NOT EXISTS (SELECT 1 FROM sls.leave_tran_details x WHERE x.lvd_tran_id = d.lvd_tran_id)""")
    log(f"leave_tran_details inserted: {cur.rowcount}")

    # ------------------------------------------------------------ verification
    log("\n--- verification (all orphan counts must be 0) ---")
    checks = {
        "official master orphans": f"""SELECT COUNT(*) FROM sls.hrms_ed_official_details o
            JOIN {MAP} m ON m.new_eb_id = o.eb_id AND m.company_id = {CO}
            LEFT JOIN sls.sub_dept_mst s ON s.sub_dept_id = o.sub_dept_id
            LEFT JOIN sls.designation_mst d ON d.designation_id = o.designation_id
            LEFT JOIN sls.category_mst c ON c.cata_id = o.catagory_id
            WHERE s.sub_dept_id IS NULL OR d.designation_id IS NULL OR c.cata_id IS NULL""",
        "attendance dept/desig orphans": f"""SELECT COUNT(*) FROM sls.daily_attendance a
            JOIN {MAP} m ON m.new_eb_id = a.eb_id AND m.company_id = {CO}
            LEFT JOIN sls.sub_dept_mst s ON s.sub_dept_id = a.worked_department_id
            LEFT JOIN sls.designation_mst d ON d.designation_id = a.worked_designation_id
            WHERE (a.worked_department_id IS NOT NULL AND s.sub_dept_id IS NULL)
               OR (a.worked_designation_id IS NOT NULL AND d.designation_id IS NULL)""",
        "leave type orphans": f"""SELECT COUNT(*) FROM sls.leave_transactions l
            JOIN {MAP} m ON m.new_eb_id = l.eb_id AND m.company_id = {CO}
            LEFT JOIN sls.hrms_leave_types_mst t ON t.leave_type_id = l.leave_type_id
            WHERE l.leave_type_id IS NOT NULL AND t.leave_type_id IS NULL""",
    }
    failed = []
    for name, sql in checks.items():
        (c,) = one(sql)
        log(f"{name}: {c}")
        if c:
            failed.append(name)
    if failed:
        raise RuntimeError(f"verification failed: {failed}")

    details = {"company": CO, "employees": total, "new_dept_ids": new_dept_ids,
               "new_sub_dept_ids": new_sub_dept_ids, "new_designation_ids": new_desig_ids,
               "new_category_ids": new_cata_ids,
               "note": "personal rows pre-existed in sls; only children/txn migrated"}
    cur.execute("INSERT INTO sls.migration_log (step, status, started_at, finished_at, details) "
                "VALUES ('vowsls_hrms_co65', %s, NOW(), NOW(), %s)",
                ("committed" if COMMIT else "dry-run", json.dumps(details)))

    if COMMIT:
        conn.commit()
        log("\nCOMMITTED.")
    else:
        conn.rollback()
        log("\nDRY RUN — rolled back. Re-run with --commit to apply.")
except Exception:
    conn.rollback()
    raise
finally:
    conn.close()
