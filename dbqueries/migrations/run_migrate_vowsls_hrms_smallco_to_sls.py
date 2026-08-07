"""
Migrate HRMS data for the remaining "small" companies from vowsls (legacy) to sls (new schema).

Scope: every company EXCEPT comp_id IN (67, 65, 2, 106, 139, 1).
  (1=NJM and 2=EJM were migrated earlier in the vowsls->sls series; 65/67/106/139 excluded by user.)
  ~21 companies, 336 employees, ~3.2k attendance rows, ~60 leave transactions.

Conventions (per VOWSLS_TO_SLS_MIGRATION_GUIDE.md and the established series):
  - branch_id values are aligned between vowsls and sls -> passthrough official.branch_id.
  - IDs preserved 1:1 wherever free in the target (verified 2026-07-27):
      * eb_id: preserved except 6 collisions (54485-54503 range, taken by the co-1/branch-87
        remap) -> those get fresh ids; full map persisted in sls._map_hrms_eb_smallco.
      * legacy department_master.dept_id -> sls.sub_dept_mst.sub_dept_id (all free except 74,
        which already exists in sls with the same desc 'GUNNY GODOWN' -> reused).
      * designation ids 1182-1316, category ids 27-55, leave_type ids 7-59: all free -> preserved.
      * leave_transaction_id / lvd_tran_id: no collisions -> preserved (details reference headers).
      * daily_atten_id: NOT preserved (nothing references it; target auto-increment).
  - dept_mst parents are created per branch from legacy master_department (find-or-create by
    (branch_id, dept_desc)); branch chosen as the modal branch of referencing employees.
  - Inactive employees ARE migrated (target keeps active=0 history; resign_details track exits).
  - Audit created_* columns dropped; updated_by falls back to 0 (guide rule).

Tables migrated:
  masters : dept_mst(new parents), sub_dept_mst, designation_mst, category_mst, hrms_leave_types_mst
  employee: hrms_ed_personal_details, hrms_ed_official_details, hrms_ed_address_details,
            hrms_ed_bank_details, hrms_ed_contact_details, hrms_ed_esi, hrms_ed_pf,
            hrms_ed_resign_details, hrms_experience_details
  txn     : daily_attendance (INSERT IGNORE; 9 exact-duplicate legacy groups collapse),
            leave_transactions, leave_tran_details

NOT migrated (no compatible target in sls / precedent skips):
  attendance_summary, tbl_hrms_holiday_transactions, holiday_master, leave_ledger,
  leave_policies_hdr/dtl, emp_leave_policy_mapping, worker_master, tbl_pay_* (payroll),
  5 leave_transactions rows with junk company_id=1000001 (belong to excluded co-1 employees).

ROLLBACK (run only if a committed run must be reversed):
  DELETE d FROM sls.leave_tran_details d JOIN sls.leave_transactions t ON t.leave_transaction_id=d.ltran_id
         JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=t.eb_id;
  DELETE t FROM sls.leave_transactions t JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=t.eb_id;
  DELETE a FROM sls.daily_attendance a JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=a.eb_id;
  DELETE x FROM sls.hrms_experience_details x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id;
  -- child tables then personal (FK order):
  DELETE x FROM sls.hrms_ed_official_details x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id;
  DELETE x FROM sls.hrms_ed_address_details x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id;
  DELETE x FROM sls.hrms_ed_bank_details   x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id;
  DELETE x FROM sls.hrms_ed_contact_details x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id;
  DELETE x FROM sls.hrms_ed_esi x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id;
  DELETE x FROM sls.hrms_ed_pf  x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id;
  DELETE x FROM sls.hrms_ed_resign_details x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id;
  DELETE p FROM sls.hrms_ed_personal_details p JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=p.eb_id;
  -- masters (id lists are printed by the run and stored in migration_log.details):
  DELETE FROM sls.hrms_leave_types_mst WHERE leave_type_id IN (<printed list>);
  DELETE FROM sls.designation_mst WHERE designation_id IN (<printed list>);
  DELETE FROM sls.category_mst    WHERE cata_id        IN (<printed list>);
  DELETE FROM sls.sub_dept_mst    WHERE sub_dept_id    IN (<printed list>);
  DELETE FROM sls.dept_mst        WHERE dept_id        IN (<printed 'new dept' list>);
  DROP TABLE sls._map_hrms_eb_smallco;

Usage:
  python run_migrate_vowsls_hrms_smallco_to_sls.py            # dry run (rolls back)
  python run_migrate_vowsls_hrms_smallco_to_sls.py --commit   # apply
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

EXCL = "(67, 65, 2, 106, 139, 1)"
SCOPE_EB = f"(SELECT eb_id FROM vowsls.tbl_hrms_ed_personal_details WHERE company_id NOT IN {EXCL})"
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
cur.execute("SHOW TABLES FROM sls LIKE '_map_hrms_eb_smallco'")
if cur.fetchone():
    n = one(f"SELECT COUNT(*) FROM {MAP}")[0]
    if n:
        sys.exit(f"ABORT: {MAP} already has {n} rows — migration appears to have run. "
                 "Use the rollback block in the header first if you need to re-run.")

(scope_n,) = one(f"SELECT COUNT(*) FROM vowsls.tbl_hrms_ed_personal_details WHERE company_id NOT IN {EXCL}")
(coll_n,) = one(f"""SELECT COUNT(*) FROM vowsls.tbl_hrms_ed_personal_details s
                     JOIN sls.hrms_ed_personal_details t ON t.eb_id = s.eb_id
                    WHERE s.company_id NOT IN {EXCL}""")
log(f"scope employees: {scope_n} (eb_id collisions to remap: {coll_n})")

# every scope official branch must exist in sls.branch_mst (FK)
(bad_branch,) = one(f"""SELECT COUNT(*) FROM vowsls.tbl_hrms_ed_official_details o
                         LEFT JOIN sls.branch_mst b ON b.branch_id = o.branch_id
                        WHERE o.eb_id IN {SCOPE_EB} AND b.branch_id IS NULL""")
if bad_branch:
    sys.exit(f"ABORT: {bad_branch} scope official rows reference branches missing in sls.branch_mst")

cur.execute(f"""CREATE TABLE IF NOT EXISTS {MAP} (
    legacy_eb_id bigint NOT NULL PRIMARY KEY,
    new_eb_id    bigint NOT NULL,
    branch_id    bigint NOT NULL,
    company_id   bigint NOT NULL,
    UNIQUE KEY uq_new_eb (new_eb_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
conn.commit()  # DDL; keep out of the data transaction

try:
    # ------------------------------------------------------------ 1. eb map
    # branch per employee = branch of the active official row, else the latest official row
    cur.execute(f"""
        INSERT INTO {MAP} (legacy_eb_id, new_eb_id, branch_id, company_id)
        SELECT p.eb_id, p.eb_id, o.branch_id, p.company_id
          FROM vowsls.tbl_hrms_ed_personal_details p
          JOIN vowsls.tbl_hrms_ed_official_details o
            ON o.tbl_hrms_ed_official_detail_id = (
                 SELECT o2.tbl_hrms_ed_official_detail_id
                   FROM vowsls.tbl_hrms_ed_official_details o2
                  WHERE o2.eb_id = p.eb_id
                  ORDER BY o2.is_active DESC, o2.tbl_hrms_ed_official_detail_id DESC
                  LIMIT 1)
         WHERE p.company_id NOT IN {EXCL}""")
    log(f"eb map rows: {cur.rowcount}")

    # remap the colliding eb_ids to fresh ids above the current sls max
    (next_eb,) = one("SELECT GREATEST((SELECT MAX(eb_id) FROM sls.hrms_ed_personal_details),"
                     f"(SELECT MAX(new_eb_id) FROM {MAP})) + 1")
    cur.execute(f"""SELECT m.legacy_eb_id FROM {MAP} m
                     JOIN sls.hrms_ed_personal_details t ON t.eb_id = m.new_eb_id
                    ORDER BY m.legacy_eb_id""")
    colliding = [r[0] for r in cur.fetchall()]
    for legacy in colliding:
        cur.execute(f"UPDATE {MAP} SET new_eb_id = %s WHERE legacy_eb_id = %s", (next_eb, legacy))
        next_eb += 1
    log(f"remapped colliding eb_ids: {colliding}")

    # ------------------------------------------------- 2. dept_mst + sub_dept_mst
    cur.execute(f"""
        SELECT o.department_id, dm.dept_code, dm.dept_desc, dm.mdept_id, dm.company_id,
               md.dept_desc, md.dept_code, o.branch_id, COUNT(*)
          FROM vowsls.tbl_hrms_ed_official_details o
          JOIN vowsls.department_master dm ON dm.dept_id = o.department_id
          LEFT JOIN vowsls.master_department md
            ON md.mdept_id = dm.mdept_id AND md.company_id = dm.company_id
         WHERE o.eb_id IN {SCOPE_EB}
         GROUP BY 1,2,3,4,5,6,7,8""")
    dept_usage = cur.fetchall()

    # modal branch per legacy dept
    branch_votes = {}
    dept_info = {}
    for dept_id, dcode, ddesc, mdept, co, mdesc, mcode, branch, n in dept_usage:
        branch_votes.setdefault(dept_id, Counter())[branch] += n
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
        SELECT o.designation_id, o.branch_id, COUNT(*)
          FROM vowsls.tbl_hrms_ed_official_details o
         WHERE o.eb_id IN {SCOPE_EB}
         GROUP BY 1, 2""")
    desig_votes = {}
    for did, branch, n in cur.fetchall():
        desig_votes.setdefault(did, Counter())[branch] += n

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
        SELECT o.catagory_id, o.branch_id, COUNT(*)
          FROM vowsls.tbl_hrms_ed_official_details o
         WHERE o.eb_id IN {SCOPE_EB}
         GROUP BY 1, 2""")
    cata_votes = {}
    for cid, branch, n in cur.fetchall():
        cata_votes.setdefault(cid, Counter())[branch] += n

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
         WHERE lt.company_id NOT IN {EXCL}
           AND NOT EXISTS (SELECT 1 FROM sls.hrms_leave_types_mst x
                            WHERE x.leave_type_id = lt.leave_type_id)""")
    log(f"hrms_leave_types_mst inserted: {cur.rowcount}")
    cur.execute(f"SELECT leave_type_id FROM vowsls.leave_types WHERE company_id NOT IN {EXCL}")
    leave_type_ids = sorted(r[0] for r in cur.fetchall())

    # ------------------------------------------- 6. hrms_ed_personal_details
    cur.execute(f"""
        INSERT INTO sls.hrms_ed_personal_details
               (eb_id, first_name, middle_name, last_name, gender, date_of_birth, blood_group,
                mobile_no, email_id, marital_status, country_id, relegion_name, fixed_eb_id,
                father_spouse_name, passport_no, driving_licence_no, pan_no, aadhar_no,
                branch_id, updated_by, active, status_id)
        SELECT m.new_eb_id, COALESCE(NULLIF(TRIM(p.first_name), ''), 'UNKNOWN'), p.middle_name,
               p.last_name, p.gender, p.date_of_birth, p.blood_group,
               NULL, NULLIF(p.email_id, ''), COALESCE(p.marital_status, 0),
               COALESCE(p.country_id, 73), p.relegion_name, p.fixed_eb_id,
               p.father_spouse_name, p.passport_no, p.driving_licence_no, p.pan_no, p.aadhar_no,
               m.branch_id, COALESCE(p.updated_by, 0), p.is_active, COALESCE(p.status, 21)
          FROM vowsls.tbl_hrms_ed_personal_details p
          JOIN {MAP} m ON m.legacy_eb_id = p.eb_id""")
    log(f"hrms_ed_personal_details inserted: {cur.rowcount}")

    # ------------------------------------------- 7. hrms_ed_official_details
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
          JOIN {MAP} m ON m.legacy_eb_id = o.eb_id
          LEFT JOIN {MAP} mr ON mr.legacy_eb_id = o.reporting_eb_id""")
    log(f"hrms_ed_official_details inserted: {cur.rowcount}")

    # --------------------------------------------------- 8. remaining ed child tables
    cur.execute(f"""
        INSERT INTO sls.hrms_ed_address_details
               (eb_id, address_type, country_id, state_id, city_name, address_line_1,
                address_line_2, pin_code, active, is_correspondent_address, updated_by)
        SELECT m.new_eb_id, COALESCE(a.address_type, 1), a.country_id, a.state_id, a.city_name,
               COALESCE(a.address_line_1, ''), a.address_line_2, COALESCE(a.pin_code, 0),
               COALESCE(a.is_active, 1), COALESCE(a.is_correspondent_address, 0),
               COALESCE(a.created_by, 0)
          FROM vowsls.tbl_hrms_ed_address_details a
          JOIN {MAP} m ON m.legacy_eb_id = a.eb_id""")
    log(f"hrms_ed_address_details inserted: {cur.rowcount}")

    cur.execute(f"""
        INSERT INTO sls.hrms_ed_bank_details
               (ifsc_code, bank_acc_no, active, updated_by, bank_name, is_verified,
                bank_branch_name, eb_id)
        SELECT COALESCE(b.ifsc_code, ''), COALESCE(b.bank_acc_no, ''), COALESCE(b.is_active, 1),
               COALESCE(b.updated_by, 0), COALESCE(b.bank_name, ''), COALESCE(b.is_verified, 0),
               COALESCE(b.bank_branch_name, ''), m.new_eb_id
          FROM vowsls.tbl_hrms_ed_bank_details b
          JOIN {MAP} m ON m.legacy_eb_id = b.eb_id""")
    log(f"hrms_ed_bank_details inserted: {cur.rowcount}")

    cur.execute(f"""
        INSERT INTO sls.hrms_ed_contact_details
               (eb_id, mobile_no, emergency_no, active, updated_by)
        SELECT m.new_eb_id, COALESCE(c.mobile_no, ''), c.emergency_no,
               COALESCE(c.is_active, 1), COALESCE(c.updated_by, 0)
          FROM vowsls.tbl_hrms_ed_contact_details c
          JOIN {MAP} m ON m.legacy_eb_id = c.eb_id""")
    log(f"hrms_ed_contact_details inserted: {cur.rowcount}")

    cur.execute(f"""
        INSERT INTO sls.hrms_ed_esi (eb_id, active, esi_no, updated_by, medical_policy_no)
        SELECT m.new_eb_id, COALESCE(e.is_active, 1), COALESCE(e.esi_no, ''),
               COALESCE(e.updated_by, 0), e.medical_policy_no
          FROM vowsls.tbl_hrms_ed_esi e
          JOIN {MAP} m ON m.legacy_eb_id = e.eb_id""")
    log(f"hrms_ed_esi inserted: {cur.rowcount}")

    cur.execute(f"""
        INSERT INTO sls.hrms_ed_pf
               (eb_id, active, updated_by, pf_date_of_join, pf_no, pf_uan_no, pf_transfer_no,
                pf_previous_no, nominee_name, relationship_name)
        SELECT m.new_eb_id, COALESCE(f.is_active, 1), COALESCE(f.updated_by, 0),
               f.pf_date_of_join, COALESCE(f.pf_no, ''), COALESCE(f.pf_uan_no, ''),
               f.pf_transfer_no, COALESCE(f.pf_previous_no, ''), f.nominee_name, f.relationship_name
          FROM vowsls.tbl_hrms_ed_pf f
          JOIN {MAP} m ON m.legacy_eb_id = f.eb_id""")
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
          JOIN {MAP} m ON m.legacy_eb_id = r.eb_id""")
    log(f"hrms_ed_resign_details inserted: {cur.rowcount}")

    # ------------------------------------------------ 9. hrms_experience_details
    (exp_skipped,) = one(f"""SELECT COUNT(*) FROM vowsls.tbl_hrms_experience_details x
                              WHERE x.company_id NOT IN {EXCL}
                                AND x.emp_id NOT IN (SELECT legacy_eb_id FROM {MAP})""")
    cur.execute(f"""
        INSERT INTO sls.hrms_experience_details
               (updated_by, eb_id, company_name, from_date, to_date, designation, project,
                co_id, active, contact)
        SELECT COALESCE(x.updated_by, 0), m.new_eb_id, x.company_name, x.from_date, x.to_date,
               x.designation, x.project, x.company_id, COALESCE(x.is_active, 1), x.contact
          FROM vowsls.tbl_hrms_experience_details x
          JOIN {MAP} m ON m.legacy_eb_id = x.emp_id
         WHERE x.company_id NOT IN {EXCL}""")
    log(f"hrms_experience_details inserted: {cur.rowcount} (skipped, employee outside scope: {exp_skipped})")

    # ----------------------------------------------------- 10. daily_attendance
    # INSERT IGNORE: 9 legacy groups are exact duplicates on the target's unique key and collapse.
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
          JOIN {MAP} m ON m.legacy_eb_id = a.eb_id
         WHERE a.company_id NOT IN {EXCL}""")
    log(f"daily_attendance inserted: {cur.rowcount}")

    # --------------------------------------------------- 11. leave_transactions
    (leave_skipped,) = one(f"""SELECT COUNT(*) FROM vowsls.leave_transactions l
                                WHERE l.company_id NOT IN {EXCL}
                                  AND l.eb_id NOT IN (SELECT legacy_eb_id FROM {MAP})""")
    cur.execute(f"""
        INSERT INTO sls.leave_transactions
               (leave_transaction_id, branch_id, eb_id, leave_from_date, leave_ledger_id,
                leave_purpose, leave_to_date, leave_type_id, remarks, status, updated_by,
                updated_date_time)
        SELECT l.leave_transaction_id, m.branch_id, m.new_eb_id, l.leave_from_date,
               l.leave_ledger_id, l.leave_purpose, l.leave_to_date, l.leave_type_id, l.remarks,
               l.status, COALESCE(l.updated_by, 0), l.updated_date_time
          FROM vowsls.leave_transactions l
          JOIN {MAP} m ON m.legacy_eb_id = l.eb_id
         WHERE l.company_id NOT IN {EXCL}""")
    log(f"leave_transactions inserted: {cur.rowcount} (skipped, employee outside scope: {leave_skipped})")

    # --------------------------------------------------- 12. leave_tran_details
    cur.execute(f"""
        INSERT INTO sls.leave_tran_details
               (lvd_tran_id, leave_date, ltran_id, auto_datetime_insert, created_by,
                company_id, is_active)
        SELECT d.lvd_tran_id, d.leave_date, d.ltran_id, d.auto_datetime_insert, d.created_by,
               d.company_id, d.is_active
          FROM vowsls.leave_tran_details d
         WHERE d.ltran_id IN (
                 SELECT l.leave_transaction_id FROM vowsls.leave_transactions l
                  JOIN {MAP} m ON m.legacy_eb_id = l.eb_id
                 WHERE l.company_id NOT IN {EXCL})""")
    log(f"leave_tran_details inserted: {cur.rowcount}")

    # ------------------------------------------------------------ verification
    log("\n--- verification (all orphan counts must be 0) ---")
    checks = {
        "personal branch orphans": f"""SELECT COUNT(*) FROM sls.hrms_ed_personal_details p
            JOIN {MAP} m ON m.new_eb_id = p.eb_id
            LEFT JOIN sls.branch_mst b ON b.branch_id = p.branch_id WHERE b.branch_id IS NULL""",
        "attendance dept orphans": f"""SELECT COUNT(*) FROM sls.daily_attendance a
            JOIN {MAP} m ON m.new_eb_id = a.eb_id
            LEFT JOIN sls.sub_dept_mst s ON s.sub_dept_id = a.worked_department_id
            WHERE a.worked_department_id IS NOT NULL AND s.sub_dept_id IS NULL""",
        "attendance desig orphans": f"""SELECT COUNT(*) FROM sls.daily_attendance a
            JOIN {MAP} m ON m.new_eb_id = a.eb_id
            LEFT JOIN sls.designation_mst d ON d.designation_id = a.worked_designation_id
            WHERE a.worked_designation_id IS NOT NULL AND d.designation_id IS NULL""",
        "leave type orphans": f"""SELECT COUNT(*) FROM sls.leave_transactions l
            JOIN {MAP} m ON m.new_eb_id = l.eb_id
            LEFT JOIN sls.hrms_leave_types_mst t ON t.leave_type_id = l.leave_type_id
            WHERE l.leave_type_id IS NOT NULL AND t.leave_type_id IS NULL""",
        "leave detail orphans": f"""SELECT COUNT(*) FROM sls.leave_tran_details d
            LEFT JOIN sls.leave_transactions l ON l.leave_transaction_id = d.ltran_id
            WHERE d.ltran_id IS NOT NULL AND l.leave_transaction_id IS NULL""",
    }
    failed = []
    for name, sql in checks.items():
        (n,) = one(sql)
        log(f"{name}: {n}")
        if n:
            failed.append(name)
    if failed:
        raise RuntimeError(f"verification failed: {failed}")

    details = {
        "scope_employees": scope_n,
        "remapped_eb_ids": colliding,
        "new_dept_ids": new_dept_ids,
        "new_sub_dept_ids": new_sub_dept_ids,
        "new_designation_ids": new_desig_ids,
        "new_category_ids": new_cata_ids,
        "leave_type_ids": leave_type_ids,
        "skipped_leave_rows_eb_out_of_scope": leave_skipped,
        "skipped_experience_rows": exp_skipped,
    }
    cur.execute("INSERT INTO sls.migration_log (step, status, started_at, finished_at, details) "
                "VALUES ('vowsls_hrms_smallco', %s, NOW(), NOW(), %s)",
                ("committed" if COMMIT else "dry-run", json.dumps(details)))

    if COMMIT:
        conn.commit()
        log("\nCOMMITTED.")
    else:
        conn.rollback()
        cur.execute(f"DROP TABLE IF EXISTS {MAP}")  # dry run leaves nothing behind
        conn.commit()
        log("\nDRY RUN — rolled back. Re-run with --commit to apply.")
except Exception:
    conn.rollback()
    if not COMMIT:
        cur.execute(f"DROP TABLE IF EXISTS {MAP}")
        conn.commit()
    raise
finally:
    conn.close()
