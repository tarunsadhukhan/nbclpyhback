"""
Migrate ALL remaining emp_code-missing HRMS employees (companies 1 and 2) from vowsls to sls.

Final step of the vowsls->sls HRMS series (smallco 2026-07-27, co65 + co67/106/139 2026-07-28).
Requested 2026-07-28: "EJCL486 is not migrated, migrate all emp_codes which are missing".

SCOPE — an employee is in scope iff:
  - personal.company_id IN (1, 2), AND
  - they have at least one official row with a non-empty emp_code, AND
  - NONE of their trimmed emp_codes already exist in sls.hrms_ed_official_details.
(~8,240: 8,231 co-2 EJM historicals + 9 co-1.)

Verified pre-flight (2026-07-28):
  - ALL 8,231 co-2 scope employees already have sls personal rows with the SAME eb_id and
    matching first name (earlier EJM migration copied personal for everyone but official/child
    rows only for others) -> identity map, personal NOT re-inserted.
    ~81 active co-2 employees are PARTIALLY migrated (some addr/bank/contact/esi/pf/resign rows
    exist) -> per-table eb-level guards skip ebs that already have rows in that table.
  - The 9 co-1 employees collide: their sls eb slot holds a DIFFERENT person (name mismatch)
    -> remapped to fresh eb_ids, personal inserted.
  - masters: 1 dept, 3 designation (+2 attendance-only), 1 category absent -> created, legacy
    ids preserved. Leave types all present; leave txn ids collision-free.
  - 2 co-2 employees have official.branch_id = 0 -> branch falls back to their sls personal
    branch (29). Attendance: 89 sls rows pre-exist for scope ebs -> INSERT IGNORE dedups.

Collision rule (differs from smallco): a map row is remapped to a fresh eb_id ONLY when the sls
personal row at that eb has a DIFFERENT first name; same-name rows are identity-mapped.
Personal is inserted only for map rows whose new_eb_id is absent from sls personal.

ROLLBACK (committed run only):
  DELETE d FROM sls.leave_tran_details d JOIN sls.leave_transactions t ON t.leave_transaction_id=d.ltran_id
         JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=t.eb_id AND m.company_id IN (1,2);
  DELETE t FROM sls.leave_transactions t JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=t.eb_id AND m.company_id IN (1,2);
  DELETE a FROM sls.daily_attendance a JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=a.eb_id AND m.company_id IN (1,2)
         WHERE a.created_date_time IS NULL OR 1=1;  -- CAUTION: 89 attendance rows pre-existed for co-2 ebs;
                                                    -- restore from backup rather than blanket-delete if exact
                                                    -- reversal matters.
  DELETE x FROM sls.hrms_experience_details x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id AND m.company_id IN (1,2);
  DELETE x FROM sls.hrms_ed_official_details x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id AND m.company_id IN (1,2);
  -- child tables: only ebs that had NO rows before this run were inserted; the per-table skip
  -- lists are in migration_log.details (skipped_child_ebs) — do not delete rows for those ebs:
  DELETE x FROM sls.hrms_ed_address_details x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id AND m.company_id IN (1,2);
  DELETE x FROM sls.hrms_ed_bank_details   x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id AND m.company_id IN (1,2);
  DELETE x FROM sls.hrms_ed_contact_details x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id AND m.company_id IN (1,2);
  DELETE x FROM sls.hrms_ed_esi x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id AND m.company_id IN (1,2);
  DELETE x FROM sls.hrms_ed_pf  x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id AND m.company_id IN (1,2);
  DELETE x FROM sls.hrms_ed_resign_details x JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=x.eb_id AND m.company_id IN (1,2);
  -- personal: ONLY the fresh-id rows (co-1 remaps); identity rows pre-existed:
  DELETE p FROM sls.hrms_ed_personal_details p JOIN sls._map_hrms_eb_smallco m ON m.new_eb_id=p.eb_id
         AND m.company_id IN (1,2) WHERE m.new_eb_id <> m.legacy_eb_id;
  DELETE FROM sls.designation_mst WHERE designation_id IN (<printed list>);
  DELETE FROM sls.category_mst    WHERE cata_id        IN (<printed list>);
  DELETE FROM sls.sub_dept_mst    WHERE sub_dept_id    IN (<printed list>);
  DELETE FROM sls.dept_mst        WHERE dept_id        IN (<printed 'new dept' list>);
  DELETE FROM sls._map_hrms_eb_smallco WHERE company_id IN (1, 2);

Usage:
  python run_migrate_vowsls_hrms_missing_rest_to_sls.py            # dry run (rolls back)
  python run_migrate_vowsls_hrms_missing_rest_to_sls.py --commit   # apply
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

COS = "(1, 2)"
MAP = "sls._map_hrms_eb_smallco"

conn = pymysql.connect(host=ENV["DATABASE_HOST"], user=ENV["DATABASE_USER"],
                       password=ENV["DATABASE_PASSWORD"], port=int(ENV["DATABASE_PORT"]),
                       database="sls", autocommit=False)
cur = conn.cursor()


def one(sql, args=None):
    cur.execute(sql, args)
    return cur.fetchone()


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- pre-flight
(n,) = one(f"SELECT COUNT(*) FROM {MAP} WHERE company_id IN {COS}")
if n:
    sys.exit(f"ABORT: {MAP} already has {n} rows for companies {COS} — this script appears to have run. "
             "Use the rollback block in the header first if you need to re-run.")

# materialize the scope once (temp tables; MySQL can't reopen a temp table twice in one query,
# so every later statement references the real MAP table instead)
cur.execute("CREATE TEMPORARY TABLE tmp_sls_codes (emp_code varchar(100) PRIMARY KEY) "
            "SELECT DISTINCT emp_code FROM sls.hrms_ed_official_details WHERE emp_code IS NOT NULL")
cur.execute(f"""CREATE TEMPORARY TABLE tmp_missing (eb_id bigint PRIMARY KEY, company_id bigint)
    SELECT p.eb_id, p.company_id FROM vowsls.tbl_hrms_ed_personal_details p
     WHERE p.company_id IN {COS}
       AND EXISTS (SELECT 1 FROM vowsls.tbl_hrms_ed_official_details o
                    WHERE o.eb_id = p.eb_id AND TRIM(COALESCE(o.emp_code,'')) <> '')
       -- junk filter: legacy test rows ('ejclx'/'ejclxx') whose every official row has all-zero
       -- dept/desig/category cannot satisfy the NOT NULL FK trio in sls -> excluded
       AND EXISTS (SELECT 1 FROM vowsls.tbl_hrms_ed_official_details o
                    WHERE o.eb_id = p.eb_id
                      AND NOT (o.department_id = 0 AND o.designation_id = 0 AND o.catagory_id = 0))
       AND NOT EXISTS (
             SELECT 1 FROM vowsls.tbl_hrms_ed_official_details o
             JOIN tmp_sls_codes x
               ON x.emp_code COLLATE utf8mb4_general_ci = TRIM(o.emp_code) COLLATE utf8mb4_general_ci
            WHERE o.eb_id = p.eb_id AND TRIM(COALESCE(o.emp_code,'')) <> '')""")
(scope_n,) = one("SELECT COUNT(*) FROM tmp_missing")
(junk_n,) = one(f"""SELECT COUNT(*) FROM vowsls.tbl_hrms_ed_personal_details p
     WHERE p.company_id IN {COS}
       AND EXISTS (SELECT 1 FROM vowsls.tbl_hrms_ed_official_details o
                    WHERE o.eb_id = p.eb_id AND TRIM(COALESCE(o.emp_code,'')) <> '')
       AND NOT EXISTS (SELECT 1 FROM vowsls.tbl_hrms_ed_official_details o
                    WHERE o.eb_id = p.eb_id
                      AND NOT (o.department_id = 0 AND o.designation_id = 0 AND o.catagory_id = 0))""")
log(f"scope employees (emp_code missing in sls): {scope_n} (junk all-zero test employees excluded: {junk_n})")
if not scope_n:
    sys.exit("nothing to migrate")

(bad_branch,) = one("""SELECT COUNT(*) FROM vowsls.tbl_hrms_ed_official_details o
                        JOIN tmp_missing m ON m.eb_id = o.eb_id
                        LEFT JOIN sls.branch_mst b ON b.branch_id = o.branch_id
                       WHERE o.branch_id <> 0 AND b.branch_id IS NULL""")
if bad_branch:
    sys.exit(f"ABORT: {bad_branch} scope official rows reference branches missing in sls.branch_mst")

try:
    # ------------------------------------------------------------ 1. eb map
    # branch = branch of the active (else latest) official row; branch 0 falls back to the
    # pre-existing sls personal branch (2 co-2 employees), else the vowsls personal branch
    cur.execute(f"""
        INSERT INTO {MAP} (legacy_eb_id, new_eb_id, branch_id, company_id)
        SELECT p.eb_id, p.eb_id,
               COALESCE(NULLIF(o.branch_id, 0), t.branch_id),
               p.company_id
          FROM tmp_missing tm
          JOIN vowsls.tbl_hrms_ed_personal_details p ON p.eb_id = tm.eb_id
          JOIN vowsls.tbl_hrms_ed_official_details o
            ON o.tbl_hrms_ed_official_detail_id = (
                 SELECT o2.tbl_hrms_ed_official_detail_id
                   FROM vowsls.tbl_hrms_ed_official_details o2
                  WHERE o2.eb_id = p.eb_id
                  ORDER BY o2.is_active DESC, o2.tbl_hrms_ed_official_detail_id DESC
                  LIMIT 1)
          LEFT JOIN sls.hrms_ed_personal_details t ON t.eb_id = p.eb_id""")
    log(f"eb map rows: {cur.rowcount}")

    # remap ONLY true collisions: sls personal exists at that eb with a DIFFERENT first name.
    # Same-name rows are the pre-existing identity population (co-2) and keep their eb_id.
    cur.execute(f"""
        SELECT m.legacy_eb_id FROM {MAP} m
         JOIN sls.hrms_ed_personal_details t ON t.eb_id = m.new_eb_id
         JOIN vowsls.tbl_hrms_ed_personal_details s ON s.eb_id = m.legacy_eb_id
        WHERE m.company_id IN {COS}
          AND UPPER(TRIM(s.first_name)) <> UPPER(TRIM(t.first_name))
        ORDER BY m.legacy_eb_id""")
    colliding = [r[0] for r in cur.fetchall()]
    (next_eb,) = one("SELECT GREATEST((SELECT MAX(eb_id) FROM sls.hrms_ed_personal_details),"
                     f"(SELECT MAX(new_eb_id) FROM {MAP})) + 1")
    for legacy in colliding:
        cur.execute(f"UPDATE {MAP} SET new_eb_id = %s WHERE legacy_eb_id = %s", (next_eb, legacy))
        next_eb += 1
    log(f"remapped colliding eb_ids (different person at slot): {len(colliding)} -> {colliding}")

    (identity_n,) = one(f"""SELECT COUNT(*) FROM {MAP} m
        JOIN sls.hrms_ed_personal_details t ON t.eb_id = m.new_eb_id
        WHERE m.company_id IN {COS}""")
    log(f"identity-mapped (personal pre-exists, kept): {identity_n}")

    # ------------------------------------------------- 2. dept_mst + sub_dept_mst
    cur.execute(f"""
        SELECT u.dept_id, dm.dept_code, dm.dept_desc, md.dept_desc, md.dept_code,
               u.branch_id, COUNT(*)
          FROM (SELECT o.department_id AS dept_id, o.branch_id
                  FROM vowsls.tbl_hrms_ed_official_details o
                  JOIN {MAP} m ON m.legacy_eb_id = o.eb_id AND m.company_id IN {COS}
                UNION ALL
                SELECT a.worked_department_id, m.branch_id
                  FROM vowsls.daily_attendance a
                  JOIN {MAP} m ON m.legacy_eb_id = a.eb_id AND m.company_id IN {COS}
                 WHERE a.worked_department_id IS NOT NULL) u
          JOIN vowsls.department_master dm ON dm.dept_id = u.dept_id
          LEFT JOIN vowsls.master_department md
            ON md.mdept_id = dm.mdept_id AND md.company_id = dm.company_id
         GROUP BY 1,2,3,4,5,6""")
    dept_usage = cur.fetchall()
    branch_votes, dept_info = {}, {}
    for dept_id, dcode, ddesc, mdesc, mcode, branch, cnt in dept_usage:
        branch_votes.setdefault(dept_id, Counter())[branch] += cnt
        dept_info[dept_id] = (dcode, ddesc, mdesc or ddesc, mcode or dcode)

    new_dept_ids, new_sub_dept_ids = [], []
    for dept_id, (dcode, ddesc, parent_desc, parent_code) in sorted(dept_info.items()):
        if one("SELECT 1 FROM sls.sub_dept_mst WHERE sub_dept_id = %s", (dept_id,)):
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
        SELECT u.designation_id, u.branch_id, COUNT(*)
          FROM (SELECT o.designation_id, o.branch_id
                  FROM vowsls.tbl_hrms_ed_official_details o
                  JOIN {MAP} m ON m.legacy_eb_id = o.eb_id AND m.company_id IN {COS}
                UNION ALL
                SELECT a.worked_designation_id, m.branch_id
                  FROM vowsls.daily_attendance a
                  JOIN {MAP} m ON m.legacy_eb_id = a.eb_id AND m.company_id IN {COS}
                 WHERE a.worked_designation_id IS NOT NULL) u
         GROUP BY 1, 2""")
    desig_votes = {}
    for did, branch, cnt in cur.fetchall():
        desig_votes.setdefault(did, Counter())[branch] += cnt
    new_desig_ids = []
    for did in sorted(desig_votes):
        if not did:
            continue
        if one("SELECT 1 FROM sls.designation_mst WHERE designation_id = %s", (did,)):
            continue
        cur.execute("""
            INSERT INTO sls.designation_mst
                   (designation_id, branch_id, dept_id, desig, norms, time_piece, direct_indirect,
                    on_machine, machine_type, no_of_machines, cost_code, cost_description,
                    piece_rate_type, active, updated_by, updated_date_time)
            SELECT id, %s, NULL, LEFT(desig, 100), norms, LEFT(time_piece, 10),
                   LEFT(direct_indirect, 10), LEFT(on_machine, 5),
                   NULLIF(TRIM(machine_type), ''), no_of_machines, cost_code, cost_description,
                   piece_rate_type, 1, 0, NOW()
              FROM vowsls.designation WHERE id = %s""",
            (desig_votes[did].most_common(1)[0][0], did))
        new_desig_ids.append(did)
    log(f"designation_mst created (ids preserved): {new_desig_ids}")

    # --------------------------------------------------------- 4. category_mst
    cur.execute(f"""
        SELECT o.catagory_id, o.branch_id, COUNT(*) FROM vowsls.tbl_hrms_ed_official_details o
          JOIN {MAP} m ON m.legacy_eb_id = o.eb_id AND m.company_id IN {COS}
         GROUP BY 1, 2""")
    cata_votes = {}
    for cid, branch, cnt in cur.fetchall():
        cata_votes.setdefault(cid, Counter())[branch] += cnt
    new_cata_ids = []
    for cid in sorted(cata_votes):
        if not cid:
            continue
        if one("SELECT 1 FROM sls.category_mst WHERE cata_id = %s", (cid,)):
            continue
        cur.execute("""
            INSERT INTO sls.category_mst (cata_id, cata_code, cata_desc, branch_id, updated_by)
            SELECT cata_id, cata_code, cata_desc, %s, 0
              FROM vowsls.category_master WHERE cata_id = %s""",
            (cata_votes[cid].most_common(1)[0][0], cid))
        new_cata_ids.append(cid)
    log(f"category_mst created (ids preserved): {new_cata_ids}")

    # ------------------------------------------- 5. hrms_ed_personal_details
    # ONLY for map rows whose new_eb_id is absent from sls personal (the co-1 remaps);
    # the identity population's personal rows pre-exist and are left untouched
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
          JOIN {MAP} m ON m.legacy_eb_id = p.eb_id AND m.company_id IN {COS}
         WHERE NOT EXISTS (SELECT 1 FROM sls.hrms_ed_personal_details t WHERE t.eb_id = m.new_eb_id)""")
    log(f"hrms_ed_personal_details inserted (fresh-id rows only): {cur.rowcount}")

    # ------------------------------------------- 6. hrms_ed_official_details
    cur.execute(f"""
        INSERT INTO sls.hrms_ed_official_details
               (eb_id, updated_by, active, sub_dept_id, catagory_id, designation_id, branch_id,
                date_of_join, probation_period, minimum_working_commitment, reporting_eb_id,
                emp_code, legacy_code, contractor_id, office_mobile_no, office_email_id, off_day)
        SELECT m.new_eb_id, COALESCE(o.updated_by, 0), o.is_active, o.department_id,
               o.catagory_id, o.designation_id,
               COALESCE(NULLIF(o.branch_id, 0), m.branch_id),
               o.date_of_join, o.probation_period, COALESCE(o.minimum_working_commitment, 0),
               COALESCE(mr.new_eb_id, NULLIF(o.reporting_eb_id, 0)),
               COALESCE(NULLIF(TRIM(o.emp_code), ''), CONCAT('MIG-', m.new_eb_id)),
               o.legacy_code, NULLIF(o.contractor_id, 0),
               o.office_mobile_no, o.office_email_id, 1
          FROM vowsls.tbl_hrms_ed_official_details o
          JOIN {MAP} m ON m.legacy_eb_id = o.eb_id AND m.company_id IN {COS}
          LEFT JOIN {MAP} mr ON mr.legacy_eb_id = o.reporting_eb_id""")
    log(f"hrms_ed_official_details inserted: {cur.rowcount}")

    # --------------------------------------------------- 7. remaining ed child tables
    # eb-level guard per table: ~81 active co-2 employees were partially migrated earlier and
    # already have rows in some of these tables — keep the sls version, skip those ebs
    child_specs = [
        ("hrms_ed_address_details",
         """(eb_id, address_type, country_id, state_id, city_name, address_line_1,
             address_line_2, pin_code, active, is_correspondent_address, updated_by)
            SELECT m.new_eb_id, COALESCE(a.address_type, 1), a.country_id, a.state_id, a.city_name,
                   COALESCE(a.address_line_1, ''), a.address_line_2, COALESCE(a.pin_code, 0),
                   COALESCE(a.is_active, 1), COALESCE(a.is_correspondent_address, 0),
                   COALESCE(a.created_by, 0)
              FROM vowsls.tbl_hrms_ed_address_details a
              JOIN {MAP} m ON m.legacy_eb_id = a.eb_id AND m.company_id IN {COS}"""),
        ("hrms_ed_bank_details",
         """(ifsc_code, bank_acc_no, active, updated_by, bank_name, is_verified,
             bank_branch_name, eb_id)
            SELECT COALESCE(b.ifsc_code, ''), COALESCE(b.bank_acc_no, ''), COALESCE(b.is_active, 1),
                   COALESCE(b.updated_by, 0), COALESCE(b.bank_name, ''), COALESCE(b.is_verified, 0),
                   COALESCE(b.bank_branch_name, ''), m.new_eb_id
              FROM vowsls.tbl_hrms_ed_bank_details b
              JOIN {MAP} m ON m.legacy_eb_id = b.eb_id AND m.company_id IN {COS}"""),
        ("hrms_ed_contact_details",
         """(eb_id, mobile_no, emergency_no, active, updated_by)
            SELECT m.new_eb_id, COALESCE(c.mobile_no, ''), c.emergency_no,
                   COALESCE(c.is_active, 1), COALESCE(c.updated_by, 0)
              FROM vowsls.tbl_hrms_ed_contact_details c
              JOIN {MAP} m ON m.legacy_eb_id = c.eb_id AND m.company_id IN {COS}"""),
        ("hrms_ed_esi",
         """(eb_id, active, esi_no, updated_by, medical_policy_no)
            SELECT m.new_eb_id, COALESCE(e.is_active, 1), COALESCE(e.esi_no, ''),
                   COALESCE(e.updated_by, 0), e.medical_policy_no
              FROM vowsls.tbl_hrms_ed_esi e
              JOIN {MAP} m ON m.legacy_eb_id = e.eb_id AND m.company_id IN {COS}"""),
        ("hrms_ed_pf",
         """(eb_id, active, updated_by, pf_date_of_join, pf_no, pf_uan_no, pf_transfer_no,
             pf_previous_no, nominee_name, relationship_name)
            SELECT m.new_eb_id, COALESCE(f.is_active, 1), COALESCE(f.updated_by, 0),
                   f.pf_date_of_join, COALESCE(f.pf_no, ''), COALESCE(f.pf_uan_no, ''),
                   f.pf_transfer_no, COALESCE(f.pf_previous_no, ''), f.nominee_name, f.relationship_name
              FROM vowsls.tbl_hrms_ed_pf f
              JOIN {MAP} m ON m.legacy_eb_id = f.eb_id AND m.company_id IN {COS}"""),
        ("hrms_ed_resign_details",
         """(eb_id, updated_by, active, date_of_inactive, fnf_date, net_settlement_amount,
             notice_days, release_date, resign_reasons, resign_remarks, resigned_date,
             type_of_resign, retired_date)
            SELECT m.new_eb_id, COALESCE(r.updated_by, 0), COALESCE(r.is_active, 1),
                   r.date_of_inactive, r.fnf_date, r.net_settlement_amount, r.notice_days,
                   r.release_date, r.resign_reasons, r.resign_remarks, r.resigned_date,
                   r.type_of_resign, r.retired_date
              FROM vowsls.tbl_hrms_ed_resign_details r
              JOIN {MAP} m ON m.legacy_eb_id = r.eb_id AND m.company_id IN {COS}"""),
    ]
    skipped_child_ebs = {}
    for table, body in child_specs:
        (skip_n,) = one(f"""SELECT COUNT(DISTINCT m.new_eb_id) FROM {MAP} m
                             JOIN sls.`{table}` t ON t.eb_id = m.new_eb_id
                            WHERE m.company_id IN {COS}""")
        skipped_child_ebs[table] = skip_n
        sql = (f"INSERT INTO sls.{table} " + body.format(MAP=MAP, COS=COS)
               + f" WHERE NOT EXISTS (SELECT 1 FROM sls.`{table}` t WHERE t.eb_id = m.new_eb_id)")
        cur.execute(sql)
        log(f"{table} inserted: {cur.rowcount} (ebs skipped, rows pre-existed: {skip_n})")

    # ------------------------------------------------ 8. hrms_experience_details
    cur.execute(f"""
        INSERT INTO sls.hrms_experience_details
               (updated_by, eb_id, company_name, from_date, to_date, designation, project,
                co_id, active, contact)
        SELECT COALESCE(x.updated_by, 0), m.new_eb_id, x.company_name, x.from_date, x.to_date,
               x.designation, x.project, x.company_id, COALESCE(x.is_active, 1), x.contact
          FROM vowsls.tbl_hrms_experience_details x
          JOIN {MAP} m ON m.legacy_eb_id = x.emp_id AND m.company_id IN {COS}""")
    log(f"hrms_experience_details inserted: {cur.rowcount}")

    # ----------------------------------------------------- 9. daily_attendance
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
          JOIN {MAP} m ON m.legacy_eb_id = a.eb_id AND m.company_id IN {COS}""")
    log(f"daily_attendance inserted: {cur.rowcount}")

    # --------------------------------------------------- 10. leave transactions + details
    cur.execute(f"""
        INSERT INTO sls.leave_transactions
               (leave_transaction_id, branch_id, eb_id, leave_from_date, leave_ledger_id,
                leave_purpose, leave_to_date, leave_type_id, remarks, status, updated_by,
                updated_date_time)
        SELECT l.leave_transaction_id, m.branch_id, m.new_eb_id, l.leave_from_date,
               l.leave_ledger_id, l.leave_purpose, l.leave_to_date,
               NULLIF(l.leave_type_id, 0), l.remarks,
               l.status, COALESCE(l.updated_by, 0), l.updated_date_time
          FROM vowsls.leave_transactions l
          JOIN {MAP} m ON m.legacy_eb_id = l.eb_id AND m.company_id IN {COS}
         WHERE NOT EXISTS (SELECT 1 FROM sls.leave_transactions t
                            WHERE t.leave_transaction_id = l.leave_transaction_id)""")
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
                  JOIN {MAP} m ON m.legacy_eb_id = l.eb_id AND m.company_id IN {COS})
           AND NOT EXISTS (SELECT 1 FROM sls.leave_tran_details x WHERE x.lvd_tran_id = d.lvd_tran_id)""")
    log(f"leave_tran_details inserted: {cur.rowcount}")

    # ------------------------------------------------------------ verification
    log("\n--- verification (all orphan counts must be 0) ---")
    checks = {
        "personal branch orphans": f"""SELECT COUNT(*) FROM sls.hrms_ed_personal_details p
            JOIN {MAP} m ON m.new_eb_id = p.eb_id AND m.company_id IN {COS}
            LEFT JOIN sls.branch_mst b ON b.branch_id = p.branch_id WHERE b.branch_id IS NULL""",
        "official missing personal": f"""SELECT COUNT(*) FROM sls.hrms_ed_official_details o
            JOIN {MAP} m ON m.new_eb_id = o.eb_id AND m.company_id IN {COS}
            LEFT JOIN sls.hrms_ed_personal_details p ON p.eb_id = o.eb_id
            WHERE p.eb_id IS NULL""",
        "official master orphans": f"""SELECT COUNT(*) FROM sls.hrms_ed_official_details o
            JOIN {MAP} m ON m.new_eb_id = o.eb_id AND m.company_id IN {COS}
            LEFT JOIN sls.sub_dept_mst s ON s.sub_dept_id = o.sub_dept_id
            LEFT JOIN sls.designation_mst d ON d.designation_id = o.designation_id
            LEFT JOIN sls.category_mst c ON c.cata_id = o.catagory_id
            WHERE s.sub_dept_id IS NULL OR d.designation_id IS NULL OR c.cata_id IS NULL""",
        "official branch orphans": f"""SELECT COUNT(*) FROM sls.hrms_ed_official_details o
            JOIN {MAP} m ON m.new_eb_id = o.eb_id AND m.company_id IN {COS}
            LEFT JOIN sls.branch_mst b ON b.branch_id = o.branch_id WHERE b.branch_id IS NULL""",
        "attendance dept/desig orphans": f"""SELECT COUNT(*) FROM sls.daily_attendance a
            JOIN {MAP} m ON m.new_eb_id = a.eb_id AND m.company_id IN {COS}
            LEFT JOIN sls.sub_dept_mst s ON s.sub_dept_id = a.worked_department_id
            LEFT JOIN sls.designation_mst d ON d.designation_id = a.worked_designation_id
            WHERE (a.worked_department_id IS NOT NULL AND s.sub_dept_id IS NULL)
               OR (a.worked_designation_id IS NOT NULL AND d.designation_id IS NULL)""",
        "leave type orphans": f"""SELECT COUNT(*) FROM sls.leave_transactions l
            JOIN {MAP} m ON m.new_eb_id = l.eb_id AND m.company_id IN {COS}
            LEFT JOIN sls.hrms_leave_types_mst t ON t.leave_type_id = l.leave_type_id
            WHERE l.leave_type_id IS NOT NULL AND t.leave_type_id IS NULL""",
        "leave detail orphans": f"""SELECT COUNT(*) FROM sls.leave_tran_details d
            LEFT JOIN sls.leave_transactions l ON l.leave_transaction_id = d.ltran_id
            WHERE d.ltran_id IS NOT NULL AND l.leave_transaction_id IS NULL""",
        "emp_code still missing after run": """SELECT COUNT(DISTINCT TRIM(o.emp_code))
            FROM vowsls.tbl_hrms_ed_official_details o
            JOIN tmp_missing tm ON tm.eb_id = o.eb_id
            WHERE TRIM(COALESCE(o.emp_code,'')) <> ''
              AND NOT EXISTS (SELECT 1 FROM sls.hrms_ed_official_details x
                               WHERE x.emp_code COLLATE utf8mb4_general_ci
                                     = TRIM(o.emp_code) COLLATE utf8mb4_general_ci)""",
    }
    failed = []
    for name, sql in checks.items():
        (c,) = one(sql)
        log(f"{name}: {c}")
        if c:
            failed.append(name)
    if failed:
        raise RuntimeError(f"verification failed: {failed}")

    details = {
        "companies": [1, 2],
        "scope_employees": scope_n,
        "junk_employees_excluded": junk_n,
        "identity_mapped": identity_n,
        "remapped_eb_ids": colliding,
        "new_dept_ids": new_dept_ids,
        "new_sub_dept_ids": new_sub_dept_ids,
        "new_designation_ids": new_desig_ids,
        "new_category_ids": new_cata_ids,
        "skipped_child_ebs": skipped_child_ebs,
    }
    cur.execute("INSERT INTO sls.migration_log (step, status, started_at, finished_at, details) "
                "VALUES ('vowsls_hrms_missing_rest', %s, NOW(), NOW(), %s)",
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
