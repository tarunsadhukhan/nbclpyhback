"""
Attendance-Dashboard endpoint.

Returns the four datasets required by the Android `AttendanceDashboardActivity`
charts in a single response so the mobile app issues only ONE network call.

GET /attendance-dashboard
    ?date=YYYY-MM-DD          (optional, default = today)
    &branch_id=<int>          (optional)
    &co_id=<int>              (optional)
    &hourly_rate=<float>      (optional, default = 1.0  -> wage = hours * rate)
"""

import traceback
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from src.mobileapp.db import get_db


attendance_dashboard_bp = Blueprint('attendance_dashboard', __name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _scope_clause(branch_id, co_id, table_alias='da', emp_alias='o'):
    """
    Build optional WHERE-clause fragment + params tuple.
    Branch_id is on daily_attendance directly; co_id requires the employee join.
    """
    where = ''
    params = []
    if branch_id:
        where = f' AND {table_alias}.branch_id = %s'
        params.append(branch_id)
    elif co_id:
        where = f' AND {emp_alias}.co_id = %s'
        params.append(co_id)
    return where, params


def _emp_scope_clause(branch_id, co_id, alias='o'):
    """Scope clause for queries that ONLY hit hrms_ed_official_details."""
    where = ''
    params = []
    if branch_id:
        where = f' AND {alias}.branch_id = %s'
        params.append(branch_id)
    elif co_id:
        where = f' AND {alias}.co_id = %s'
        params.append(co_id)
    return where, params


# ──────────────────────────────────────────────────────────────────────────────
# Endpoint
# ──────────────────────────────────────────────────────────────────────────────

@attendance_dashboard_bp.route('/attendance-dashboard', methods=['GET'])
def attendance_dashboard():
    try:
        stat_date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        stat_date = datetime.strptime(stat_date_str, '%Y-%m-%d').date()
        branch_id = request.args.get('branch_id', type=int)
        co_id = request.args.get('co_id', type=int)
        hourly_rate = request.args.get('hourly_rate', default=1.0, type=float)

        db = get_db()
        cursor = db.cursor(dictionary=True)

        # ─────────────────────────────────────────────────────────────
        # 1. Today's attendance pie  (present / absent / leave)
        # ─────────────────────────────────────────────────────────────
        emp_where, emp_params = _emp_scope_clause(branch_id, co_id, alias='o')
        cursor.execute(
            f"""
            SELECT COUNT(*) AS cnt
              FROM hrms_ed_official_details o
             WHERE 1=1 {emp_where}
            """,
            tuple(emp_params),
        )
        total_employees = cursor.fetchone()['cnt'] or 0

        scope_where, scope_params = _scope_clause(branch_id, co_id)
        # Need employee join only when filtering by co_id
        join_emp = (
            ' JOIN hrms_ed_official_details o ON da.eb_id = o.eb_id'
            if co_id and not branch_id else ''
        )

        psql="""SELECT
                SUM(CASE WHEN COALESCE(da.attendance_mark,'P') IN ('P','PR','PRESENT')
                         THEN working_hours/8 ELSE 0 END) AS present,
                SUM(CASE WHEN COALESCE(da.attendance_mark,'')  IN ('L','LV','LEAVE')
                         THEN working_hours/8 ELSE 0 END) AS leaves
              FROM daily_attendance da
              {join_emp}
             WHERE da.attendance_date = %s
               AND da.is_active = 1
               {scope_where}
            """
        cursor.execute(
            f"""
            SELECT
                SUM(CASE WHEN COALESCE(da.attendance_mark,'P') IN ('P','PR','PRESENT')
                         THEN working_hours/8 ELSE 0 END) AS present,
                SUM(CASE WHEN COALESCE(da.attendance_mark,'')  IN ('L','LV','LEAVE')
                         THEN working_hours/8 ELSE 0 END) AS leaves
              FROM daily_attendance da
              {join_emp}
             WHERE da.attendance_date = %s
               AND da.is_active = 1
               {scope_where}
            """,
            tuple([stat_date] + scope_params),
        )
        row = cursor.fetchone() or {}
        present_count = int(row.get('present') or 0)
        leave_count = int(row.get('leaves') or 0)
        absent_count = max(0, total_employees - present_count - leave_count)
        print(f"present sql {psql} {stat_date} {scope_where} {scope_params}")
        print(f"Total: {total_employees}, Present: {present_count}, Leave: {leave_count}, Absent: {absent_count}")
        today_attendance = {
            'present': present_count,
            'absent': absent_count,
            'leave': leave_count,
            'total_employees': total_employees,
        }

        # ─────────────────────────────────────────────────────────────
        # 2. Wages – last 7 days (SUM of working_hours * hourly_rate per day)
        # ─────────────────────────────────────────────────────────────
        wages_from_date = stat_date - timedelta(days=6)
        cursor.execute(
            f"""
            SELECT da.attendance_date                        AS d,
                                     COALESCE(SUM(da.working_hours), 0)        AS total_hours,
                                     COALESCE(SUM(da.working_hours * ert.rate), 0) AS total_wages
                            FROM daily_attendance da
                            LEFT JOIN employee_rate_table ert ON da.eb_id = ert.eb_id
              {join_emp}
             WHERE da.attendance_date BETWEEN %s AND %s
               AND da.is_active = 1
               {scope_where}
             GROUP BY da.attendance_date
            """,
            tuple([wages_from_date, stat_date] + scope_params),
        )
        wages_rows = cursor.fetchall()
        hours_by_day = {r['d']: float(r['total_hours'] or 0) for r in wages_rows}
        wages_by_day = {r['d']: float(r['total_wages'] or 0) for r in wages_rows}

        wages_last_7_days = []
        for i in range(7):
            d = wages_from_date + timedelta(days=i)
            hours = hours_by_day.get(d, 0.0)
            wages = wages_by_day.get(d, 0.0)
            wages_last_7_days.append({
                'date':        d.strftime('%Y-%m-%d'),
                'label':       d.strftime('%d/%m'),      # dd/mm
                'total_hours': round(hours, 2),
                'amount':      round(wages, 2),
            })

        # ─────────────────────────────────────────────────────────────
        # 3. Last-7-days present count (line chart)
        # ─────────────────────────────────────────────────────────────
        from_date_7 = stat_date - timedelta(days=6)
        sql=f"""
            SELECT da.attendance_date                         AS d,
                   sum(working_hours/8)                   AS present
              FROM daily_attendance da
             WHERE da.attendance_date BETWEEN %s AND %s
               AND da.is_active = 1
               AND COALESCE(da.attendance_source,'P') IN ('P','PR','BIO')
               {scope_where}
             GROUP BY da.attendance_date
             ORDER BY da.attendance_date ASC
            """
        print(f"Last 7 days present SQL: {sql} with params {[from_date_7, stat_date] + scope_params}")      
        cursor.execute(
            sql,
            tuple([from_date_7, stat_date] + scope_params),
        )
        present_by_day = {row['d']: int(row['present'] or 0) for row in cursor.fetchall()}

        last_7_days_present = []
        for i in range(7):
            d = from_date_7 + timedelta(days=i)
            last_7_days_present.append({
                'date': d.strftime('%Y-%m-%d'),
                'label': d.strftime('%d/%m'),     # dd/mm
                'present': present_by_day.get(d, 0),
            })

        # ─────────────────────────────────────────────────────────────
        # 4. Absent buckets – days since each employee's last attendance
        #    Buckets (mutually exclusive):
        #       1-7 days, 8-15 days, 16-30 days, > 30 days
        # ─────────────────────────────────────────────────────────────
        emp_where2, emp_params2 = _emp_scope_clause(branch_id, co_id, alias='o')
        cursor.execute(
            f"""
            SELECT o.eb_id,
                   DATEDIFF(%s, MAX(da.attendance_date)) AS days_absent
              FROM hrms_ed_official_details o
              LEFT JOIN daily_attendance da
                     ON da.eb_id = o.eb_id
                    AND da.is_active = 1
                    AND da.attendance_date <= %s
             WHERE 1=1 {emp_where2}
             GROUP BY o.eb_id
            """,
            tuple([stat_date, stat_date] + emp_params2),
        )
        bucket_1_7 = bucket_8_15 = bucket_16_30 = bucket_over_30 = 0
        for r in cursor.fetchall():
            d = r['days_absent']
            if d is None or d > 30:
                bucket_over_30 += 1
            elif d <= 0:        # employee was present today  → not absent
                continue
            elif d <= 7:
                bucket_1_7 += 1
            elif d <= 15:
                bucket_8_15 += 1
            elif d <= 30:
                bucket_16_30 += 1

        absent_buckets = {
            'range_1_to_7':   bucket_1_7,
            'range_8_to_15':  bucket_8_15,
            'range_16_to_30': bucket_16_30,
            'over_30_days':   bucket_over_30,
        }

        # ─────────────────────────────────────────────────────────────
        # 5. Man vs Machine – last 7 days from view vw_man_machine
        #    total_hands  = hands_a  + hands_b  + hands_c
        #    total_target = thands_a + thands_b + thands_c
        # ─────────────────────────────────────────────────────────────
        mm_from_date = stat_date - timedelta(days=6)
        mm_where = ''
        mm_params = []
        if branch_id:
            mm_where = ' AND vmm.branch_id = %s'
            mm_params.append(branch_id)
        # NOTE: vw_man_machine has NO co_id column → cannot filter by co_id

        try:
            cursor.execute(
                f"""
                SELECT vmm.attendance_date AS d,
                       COALESCE(SUM(IFNULL(vmm.hands_a,0)  + IFNULL(vmm.hands_b,0)  + IFNULL(vmm.hands_c,0)),  0) AS total_hands,
                       COALESCE(SUM(IFNULL(vmm.thands_a,0) + IFNULL(vmm.thands_b,0) + IFNULL(vmm.thands_c,0)), 0) AS total_target
                  FROM vw_man_machine vmm
                 WHERE vmm.attendance_date BETWEEN %s AND %s
                   {mm_where}
                 GROUP BY vmm.attendance_date
                """,
                tuple([mm_from_date, stat_date] + mm_params),
            )
            mm_rows = cursor.fetchall()
        except Exception as mm_err:
            print(f"vw_man_machine query failed: {mm_err}")
            mm_rows = []

        hands_by_day  = {r['d']: float(r['total_hands']  or 0) for r in mm_rows}
        target_by_day = {r['d']: float(r['total_target'] or 0) for r in mm_rows}

        man_machine_last_7_days = []
        for i in range(7):
            d = mm_from_date + timedelta(days=i)
            man_machine_last_7_days.append({
                'date':         d.strftime('%Y-%m-%d'),
                'label':        d.strftime('%d/%m'),
                'total_hands':  round(hands_by_day.get(d, 0.0), 2),
                'total_target': round(target_by_day.get(d, 0.0), 2),
            })
        #print(f"Man vs Machine - last 7 days: {man_machine_last_7_days}")
        cursor.close()
        db.close()

        return jsonify({
            'status': 'success',
            'date': stat_date_str,
            'branch_id': branch_id,
            'co_id': co_id,
            'today_attendance':         today_attendance,
            'wages_last_7_days':        wages_last_7_days,
            'last_7_days_present':      last_7_days_present,
            'absent_buckets':           absent_buckets,
            'man_machine_last_7_days':  man_machine_last_7_days,
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500

