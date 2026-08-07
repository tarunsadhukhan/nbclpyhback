import traceback
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from src.mobileapp.db import get_db


dashboard_bp = Blueprint('dashboard', __name__)


# TEMP: /dashboard-stats endpoint disabled temporarily. Re-enable by
# uncommenting the route decorator below.
# @dashboard_bp.route('/dashboard-stats', methods=['GET'])
def dashboard_stats():
    """
    Returns dashboard statistics for a given date.
    Query params:
      - date      (yyyy-MM-dd) - defaults to today
      - branch_id (int)        - filter by branch
      - co_id     (int)        - filter by company
    """
    try:
        stat_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        branch_id = request.args.get('branch_id', type=int)
        co_id = request.args.get('co_id', type=int)

        db = get_db()
        cursor = db.cursor(dictionary=True)

        def _safe_count(query, params=None):
            try:
                cursor.execute(query, params or ())
                row = cursor.fetchone() or {}
                return int(row.get("cnt", 0) or 0)
            except Exception:
                return 0

        def _safe_fetchall(query, params=None):
            try:
                cursor.execute(query, params or ())
                return cursor.fetchall()
            except Exception:
                return []

        if branch_id:
            total_departments = _safe_count(
                """
                SELECT COUNT(*) AS cnt
                FROM sub_dept_mst sdm
                LEFT JOIN dept_mst dm ON dm.dept_id = sdm.dept_id
                WHERE dm.branch_id = %s
                """,
                (branch_id,),
            )
        elif co_id:
            total_departments = _safe_count(
                """
                SELECT COUNT(*) AS cnt
                FROM sub_dept_mst sdm
                LEFT JOIN dept_mst dm ON dm.dept_id = sdm.dept_id
                WHERE dm.co_id = %s
                """,
                (co_id,),
            )
        else:
            total_departments = _safe_count("SELECT COUNT(*) AS cnt FROM sub_dept_mst")

        if branch_id:
            total_designations = _safe_count(
                "SELECT COUNT(*) AS cnt FROM designation_mst WHERE active = 1 AND branch_id = %s",
                (branch_id,),
            )
        elif co_id:
            total_designations = _safe_count(
                "SELECT COUNT(*) AS cnt FROM designation_mst WHERE active = 1 AND co_id = %s",
                (co_id,),
            )
        else:
            total_designations = _safe_count("SELECT COUNT(*) AS cnt FROM designation_mst WHERE active = 1")

        if branch_id:
            total_shifts = _safe_count("SELECT COUNT(*) AS cnt FROM shift_mst WHERE branch_id = %s", (branch_id,))
        elif co_id:
            total_shifts = _safe_count("SELECT COUNT(*) AS cnt FROM shift_mst WHERE co_id = %s", (co_id,))
        else:
            total_shifts = _safe_count("SELECT COUNT(*) AS cnt FROM shift_mst")

        if branch_id:
            total_employees = _safe_count(
                "SELECT COUNT(*) AS cnt FROM hrms_ed_official_details WHERE branch_id = %s",
                (branch_id,),
            )
        elif co_id:
            total_employees = _safe_count(
                "SELECT COUNT(*) AS cnt FROM hrms_ed_official_details WHERE co_id = %s",
                (co_id,),
            )
        else:
            total_employees = _safe_count("SELECT COUNT(*) AS cnt FROM hrms_ed_official_details")

        if branch_id:
            total_present = _safe_count(
                """
                SELECT round(sum(working_hours/8),0) AS cnt
                FROM daily_attendance da
                WHERE da.attendance_date = %s AND da.branch_id = %s
                """,
                (stat_date, branch_id),
            )
        elif co_id:
            total_present = _safe_count(
                """
                SELECT round(sum(working_hours/8),0) AS cnt
                FROM daily_attendance da
                JOIN hrms_ed_official_details o ON da.eb_id = o.eb_id
                WHERE da.attendance_date = %s AND o.co_id = %s
                """,
                (stat_date, co_id),
            )
        else:
            total_present = _safe_count(
                "SELECT round(sum(working_hours/8),0) AS cnt FROM daily_attendance WHERE attendance_date = %s",
                (stat_date,),
            )

        if branch_id:
            present_face = _safe_count(
                """
                SELECT round(sum(working_hours/8),0) AS cnt
                FROM daily_attendance da
                WHERE da.attendance_date = %s
                  AND da.attendance_source IN ('Face', 'F', 'BIO')
                  AND da.branch_id = %s
                """,
                (stat_date, branch_id),
            )
        elif co_id:
            present_face = _safe_count(
                """
                SELECT round(sum(working_hours/8),0) AS cnt
                FROM daily_attendance da
                JOIN hrms_ed_official_details o ON da.eb_id = o.eb_id
                WHERE da.attendance_date = %s
                  AND da.attendance_source IN ('Face', 'F', 'BIO')
                  AND o.co_id = %s
                """,
                (stat_date, co_id),
            )
        else:
            present_face = _safe_count(
                """
                SELECT round(sum(working_hours/8),0) AS cnt
                FROM daily_attendance
                WHERE attendance_date = %s AND attendance_source IN ('Face', 'F', 'BIO')
                """,
                (stat_date,),
            )

        if branch_id:
            present_manual = _safe_count(
                """
                SELECT round(sum(working_hours/8),0) AS cnt
                FROM daily_attendance da
                WHERE da.attendance_date = %s
                  AND da.attendance_source IN ('Manual', 'A')
                  AND da.branch_id = %s
                """,
                (stat_date, branch_id),
            )
        elif co_id:
            present_manual = _safe_count(
                """
                SELECT round(sum(working_hours/8),0) AS cnt
                FROM daily_attendance da
                JOIN hrms_ed_official_details o ON da.eb_id = o.eb_id
                WHERE da.attendance_date = %s
                  AND da.attendance_source IN ('Manual', 'A')
                  AND o.co_id = %s
                """,
                (stat_date, co_id),
            )
        else:
            present_manual = _safe_count(
                """
                SELECT round(sum(working_hours/8),0) AS cnt
                FROM daily_attendance
                WHERE attendance_date = %s AND attendance_source IN ('Manual', 'A')
                """,
                (stat_date,),
            )

        # Query departments that have attendance for the selected date+branch.
        # Driven by daily_attendance so every department with present>0 is included
        # regardless of how dept_mst.branch_id is mapped.
        master_query = """
            SELECT sdm.sub_dept_id  AS department_id,
                   sdm.sub_dept_desc AS department_name,
                   0                AS total_employees,
                   round(sum(da.working_hours/8),0) AS present
            FROM daily_attendance da
            INNER JOIN sub_dept_mst sdm
                    ON sdm.sub_dept_id = da.worked_department_id
            WHERE da.attendance_date = %s
              AND da.is_active = 1
        """
        master_params = [stat_date]

        if branch_id:
            master_query += " AND da.branch_id = %s"
            master_params.append(branch_id)
        elif co_id:
            master_query += " AND da.co_id = %s"
            master_params.append(co_id)

        master_query += """
            GROUP BY sdm.sub_dept_id, sdm.sub_dept_desc
            ORDER BY sdm.sub_dept_desc
        """
        #print(f"Executing master query: {master_query} with params {master_params}")
        all_depts = _safe_fetchall(master_query, tuple(master_params))

        # Build department_present (only departments with present > 0)
        department_present = []
        department_master = []
        
        for dept in all_depts:
            total_emp = dept["total_employees"] or 0
            present_count = dept["present"] or 0
            
            dept_data = {
                "department_id": dept["department_id"],
                "department_name": dept["department_name"],
                "total_employees": total_emp,
                "present": present_count,
                "absent": max(0, total_emp - present_count),
            }
            
            # Add to master list
            department_master.append(dept_data)
            
            # Add to present list only if has present employees
            if present_count > 0:
                department_present.append(dept_data.copy())

        # Preserve the existing response contract key.
        department_wise = department_present

        total_absent = max(0, total_employees - total_present)

        # ── Production cards (Jute / Spg / Winding / Others / Bales) ────────
        # All queries scope to branch_id when provided, otherwise unscoped.
        # Numbers default to 0 when the underlying tables/columns are absent.
        def _scalar(sql_branch, sql_no_branch, params_branch, params_no_branch):
            try:
                if branch_id:
                    cursor.execute(sql_branch, params_branch)
                else:
                    cursor.execute(sql_no_branch, params_no_branch)
                row = cursor.fetchone() or {}
                val = list(row.values())[0] if row else 0
                return int(val or 0)
            except Exception:
                return 0

        # Jute — recv / issue / stock (running stock = cumulative recv)
        jute_recv = _scalar(
            "SELECT COALESCE(SUM(weight),0) v FROM tbl_jute_received "
            "WHERE recv_date = %s AND branch_id = %s",
            "SELECT COALESCE(SUM(weight),0) v FROM tbl_jute_received "
            "WHERE recv_date = %s",
            (stat_date, branch_id), (stat_date,))
        jute_issue = _scalar(
            "SELECT COALESCE(SUM(net_wt),0) v FROM assorting_entry "
            "WHERE entry_date = %s AND branch_id = %s",
            "SELECT COALESCE(SUM(net_wt),0) v FROM assorting_entry "
            "WHERE entry_date = %s",
            (stat_date, branch_id), (stat_date,))
        print(f"Jute recv: {jute_recv}, issue: {jute_issue}")
        jute_stock_recv = _scalar(
            "SELECT COALESCE(SUM(weight),0) v FROM tbl_jute_received "
            "WHERE recv_date <= %s AND branch_id = %s",
            "SELECT COALESCE(SUM(weight),0) v FROM tbl_jute_received "
            "WHERE recv_date <= %s",
            (stat_date, branch_id), (stat_date,))
        print(f"Jute stock from recv side: {jute_stock_recv}")
        jute_stock_issue = _scalar(
            "SELECT COALESCE(SUM(net_wt),0) v FROM assorting_entry "
            "WHERE entry_date <= %s AND branch_id = %s",
            "SELECT COALESCE(SUM(net_wt),0) v FROM assorting_entry "
            "WHERE entry_date <= %s",
            (stat_date, branch_id), (stat_date,))
        jute_stock = max(0, jute_stock_recv - jute_stock_issue)

        # Spinning Production — daily_doff_tbl
        spg_prod = _scalar(
            "SELECT COALESCE(SUM(net_weight),0) v FROM daily_doff_tbl "
            "WHERE doff_date = %s AND branch_id = %s AND active = 1",
            "SELECT COALESCE(SUM(net_weight),0) v FROM daily_doff_tbl "
            "WHERE doff_date = %s AND active = 1",
            (stat_date, branch_id), (stat_date,))
        spg_frames = _scalar(
            "SELECT COUNT(DISTINCT mc_id) v FROM daily_doff_tbl "
            "WHERE doff_date = %s AND branch_id = %s AND active = 1",
            "SELECT COUNT(DISTINCT mc_id) v FROM daily_doff_tbl "
            "WHERE doff_date = %s AND active = 1",
            (stat_date, branch_id), (stat_date,))
        spg_prd_frame = int(spg_prod / spg_frames) if spg_frames > 0 else 0
        # Spinning efficiency: weight/hundred-percent-prod from daily_doff_tbl + spinning_quality_mst
        spg_eff = _scalar(
            """
            SELECT COALESCE(ROUND(SUM(weight)/NULLIF(SUM(hunprod),0)*100,0),0) v FROM (
                SELECT mc_id,
                       ROUND(SUM(speed*hrs*std_count*no_of_spindles*mcno)
                             / NULLIF(SUM(tpi*14400*2.2046*36),0), 0) AS hunprod,
                       SUM(weight) AS weight
                FROM (
                    SELECT ddt.mc_id,
                           SUM(ddt.net_weight) AS weight,
                           sqm.speed, sqm.tpi, sqm.no_of_spindles,
                           8*60 AS hrs, sqm.std_count, 1 AS mcno
                    FROM daily_doff_tbl ddt
                    LEFT JOIN daily_doff_frames_winding ddfw
                           ON ddfw.mc_eb_id = ddt.mc_id
                          AND ddfw.tran_date = ddt.doff_date
                          AND ddfw.spell = ddt.spell
                          AND ddfw.spg_wdg = 'S'
                    LEFT JOIN spinning_quality_mst sqm
                           ON sqm.spg_quality_mst_id = ddfw.quality_id
                    WHERE ddt.doff_date = %s AND ddt.branch_id = %s
                    GROUP BY ddt.mc_id, sqm.speed, sqm.tpi, sqm.no_of_spindles,
                             sqm.std_count, sqm.tpi
                ) g GROUP BY mc_id
            ) h
            """,
            """
            SELECT COALESCE(ROUND(SUM(weight)/NULLIF(SUM(hunprod),0)*100,0),0) v FROM (
                SELECT mc_id,
                       ROUND(SUM(speed*hrs*std_count*no_of_spindles*mcno)
                             / NULLIF(SUM(tpi*14400*2.2046*36),0), 0) AS hunprod,
                       SUM(weight) AS weight
                FROM (
                    SELECT ddt.mc_id,
                           SUM(ddt.net_weight) AS weight,
                           sqm.speed, sqm.tpi, sqm.no_of_spindles,
                           8*60 AS hrs, sqm.std_count, 1 AS mcno
                    FROM daily_doff_tbl ddt
                    LEFT JOIN daily_doff_frames_winding ddfw
                           ON ddfw.mc_eb_id = ddt.mc_id
                          AND ddfw.tran_date = ddt.doff_date
                          AND ddfw.spell = ddt.spell
                          AND ddfw.spg_wdg = 'S'
                    LEFT JOIN spinning_quality_mst sqm
                           ON sqm.spg_quality_mst_id = ddfw.quality_id
                    WHERE ddt.doff_date = %s
                    GROUP BY ddt.mc_id, sqm.speed, sqm.tpi, sqm.no_of_spindles,
                             sqm.std_count, sqm.tpi
                ) g GROUP BY mc_id
            ) h
            """,
            (stat_date, branch_id), (stat_date,))
        # Spinning run-efficiency: machine running time / total shift hours from VVFD
        spg_run_eff = _scalar(
            """
            SELECT COALESCE(ROUND(SUM(mcrun)/NULLIF(SUM(tothrs),0)*100, 2), 0) v FROM (
                SELECT mc_id, tdvt.spell_id,
                       SUM(tdvt.mc_runs_time) AS mcrun,
                       1 AS mcno, 8 AS tothrs
                FROM tbl_daily_vvfd_transaction tdvt
                WHERE tdvt.tran_date = %s
                GROUP BY mc_id, spell_id
            ) h
            """,
            """
            SELECT COALESCE(ROUND(SUM(mcrun)/NULLIF(SUM(tothrs),0)*100, 2), 0) v FROM (
                SELECT mc_id, tdvt.spell_id,
                       SUM(tdvt.mc_runs_time) AS mcrun,
                       1 AS mcno, 8 AS tothrs
                FROM tbl_daily_vvfd_transaction tdvt
                WHERE tdvt.tran_date = %s
                GROUP BY mc_id, spell_id
            ) h
            """,
            (stat_date,), (stat_date,))

        # Winding — daily_doff_frames_winding, spg_wdg='W'
        wdg_prod = _scalar(
            "SELECT COALESCE(SUM(net_weight),0) v FROM daily_doff_frames_winding "
            "WHERE tran_date = %s AND branch_id = %s AND spg_wdg='W' AND active=1",
            "SELECT COALESCE(SUM(net_weight),0) v FROM daily_doff_frames_winding "
            "WHERE tran_date = %s AND spg_wdg='W' AND active=1",
            (stat_date, branch_id), (stat_date,))
        wdg_winders = _scalar(
            "SELECT COUNT(DISTINCT eb_id) v FROM daily_doff_frames_winding "
            "WHERE tran_date = %s AND branch_id = %s AND spg_wdg='W' AND active=1",
            "SELECT COUNT(DISTINCT eb_id) v FROM daily_doff_frames_winding "
            "WHERE tran_date = %s AND spg_wdg='W' AND active=1",
            (stat_date, branch_id), (stat_date,))
        wdg_avg_prod = int(wdg_prod / wdg_winders) if wdg_winders > 0 else 0

        # Others (Finishing) — tbl_daily_finishing
        oth_weaving  = _scalar(
            "SELECT COALESCE(SUM(cuts),0) v FROM tbl_daily_finishing "
            "WHERE tran_date = %s",
            "SELECT COALESCE(SUM(cuts),0) v FROM tbl_daily_finishing "
            "WHERE tran_date = %s",
            (stat_date,), (stat_date,))
        oth_hemming  = _scalar(
            "SELECT COALESCE(SUM(hemming),0) v FROM tbl_daily_finishing "
            "WHERE tran_date = %s",
            "SELECT COALESCE(SUM(hemming),0) v FROM tbl_daily_finishing "
            "WHERE tran_date = %s",
            (stat_date,), (stat_date,))
        oth_heracle  = _scalar(
            "SELECT COALESCE(SUM(heracle),0) v FROM tbl_daily_finishing "
            "WHERE tran_date = %s",
            "SELECT COALESCE(SUM(heracle),0) v FROM tbl_daily_finishing "
            "WHERE tran_date = %s",
            (stat_date,), (stat_date,))
        oth_hsewer  = _scalar(
            "SELECT COALESCE(SUM(hand_sewer),0) v FROM tbl_daily_finishing "
            "WHERE tran_date = %s",
            "SELECT COALESCE(SUM(hand_sewer),0) v FROM tbl_daily_finishing "
            "WHERE tran_date = %s",
            (stat_date,), (stat_date,))

        # Bales — tbl_daily_bales_transaction
        bales_prod = _scalar(
            "SELECT COALESCE(SUM(prod_bales),0) v FROM tbl_daily_bales_transaction "
            "WHERE tran_date = %s",
            "SELECT COALESCE(SUM(prod_bales),0) v FROM tbl_daily_bales_transaction "
            "WHERE tran_date = %s",
            (stat_date,), (stat_date,))

        bales_issue = _scalar(
            "SELECT COALESCE(SUM(issue_bales),0) v FROM tbl_daily_bales_transaction "
            "WHERE tran_date = %s",
            "SELECT COALESCE(SUM(issue_bales),0) v FROM tbl_daily_bales_transaction "
            "WHERE tran_date = %s",
            (stat_date,), (stat_date,))
        bales_stock = _scalar(
            "SELECT COALESCE(SUM(prod_bales - issue_bales),0) v FROM tbl_daily_bales_transaction "
            "WHERE tran_date <= %s",
            "SELECT COALESCE(SUM(prod_bales - issue_bales),0) v FROM tbl_daily_bales_transaction "
            "WHERE tran_date <= %s",
            (stat_date,), (stat_date,))
        print(f"Bales prod: {bales_prod}, issue: {bales_issue}, stock: {bales_stock}")
        cursor.close()
        db.close()
        return jsonify(
            {
                "status": "success",
                "date": stat_date,
                "total_departments": total_departments,
                "total_designations": total_designations,
                "total_shifts": total_shifts,
                "total_employees": total_employees,
                "total_present": total_present,
                "present_face": present_face,
                "present_manual": present_manual,
                "total_absent": total_absent,
                "department_wise": department_wise,
                "department_present": department_present,
                "jute_recv":     jute_recv,
                "jute_issue":    jute_issue,
                "jute_stock":    jute_stock,
                "spg_prod":      spg_prod,
                "spg_eff":       spg_eff,
                "spg_run_eff":   spg_run_eff,
                "spg_prd_frame": spg_prd_frame,
                "wdg_prod":      wdg_prod,
                "wdg_winders":   wdg_winders,
                "wdg_avg_prod":  wdg_avg_prod,
                "oth_weaving":   oth_weaving,
                "oth_hemming":   oth_hemming,
                "oth_heracle":   oth_heracle,
                "oth_hsewer":    oth_hsewer,
                "bales_prod":    bales_prod,
                "bales_issue":   bales_issue,
                "bales_stock":   bales_stock,
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── Card trend: last 7 days for one metric ──────────────────────────────────
@dashboard_bp.route('/dashboard/card-trend', methods=['GET'])
def dashboard_card_trend():
    """
    Return the last 7 days (inclusive of end_date) for one dashboard card metric.

    Query params:
      - metric     hands | jute | spg | winding | others | bales   (required)
      - branch_id  int (optional)
      - end_date   yyyy-MM-dd (defaults to today)
    Response:
      { status, metric, label, days: [{date, value}, ... 7 rows] }
    """
    try:
        metric    = (request.args.get('metric') or '').strip().lower()
        branch_id = request.args.get('branch_id', type=int)
        end_str   = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
        end_date  = datetime.strptime(end_str, '%Y-%m-%d').date()
        start_date = end_date - timedelta(days=6)

        # ── Jute is multi-series (Recv / Issue / Stock per day) ──
        if metric == 'jute':
            return _jute_trend(branch_id, start_date, end_date)

        # ── Spg Prod is multi-series (Prod / Eff / Run Eff / Prd-Frame per day) ──
        if metric == 'spg':
            return _spg_trend(branch_id, start_date, end_date)

        # ── Winding is multi-series (Prod / Avg Prod per day) ──
        if metric == 'winding':
            return _winding_trend(branch_id, start_date, end_date)

        # ── Others is multi-series (Weaving / Hemming / Heracle / H-Sewer) ──
        if metric == 'others':
            return _others_trend(branch_id, start_date, end_date)

        # ── Bales is multi-series (Prod / Issue / Stock per day) ──
        if metric == 'bales':
            return _bales_trend(branch_id, start_date, end_date)

        # metric → (display label, date column, value sql, table, optional filter)
        # value_sql must aggregate to a single number per row using GROUP BY date_col.
        metric_map = {
            'hands':   ("Hands",
                        "attendance_date",
                        "ROUND(SUM(working_hours/8),0)",
                        "daily_attendance", None),
            'spg':     ("Spg Production",
                        "doff_date",
                        "COALESCE(SUM(net_weight),0)",
                        "daily_doff_tbl", "active = 1"),
            'winding': ("Winding Production",
                        "tran_date",
                        "COALESCE(SUM(net_weight),0)",
                        "daily_doff_frames_winding",
                        "spg_wdg = 'W' AND active = 1"),
            'others':  ("Finishing (Cuts)",
                        "tran_date",
                        "COALESCE(SUM(cuts),0)",
                        "tbl_daily_finishing", None),
            'bales':   ("Bales Production",
                        "tran_date",
                        "COALESCE(SUM(prod_bales),0)",
                        "tbl_daily_bales_transaction", None),
        }
        if metric not in metric_map:
            return jsonify({'status': 'error',
                            'message': f'unknown metric "{metric}"'}), 400
        label, date_col, val_sql, table, extra = metric_map[metric]

        clauses = [f"{date_col} BETWEEN %s AND %s"]
        params  = [start_date.isoformat(), end_date.isoformat()]
        if branch_id and table != 'tbl_daily_finishing':
            clauses.append("branch_id = %s")
            params.append(branch_id)
        if extra:
            clauses.append(extra)
        where = " AND ".join(clauses)

        sql = (f"SELECT {date_col} AS d, {val_sql} AS v "
               f"FROM {table} WHERE {where} "
               f"GROUP BY {date_col} ORDER BY {date_col}")
        db  = get_db()
        cur = db.cursor(dictionary=True)
        try:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        except Exception as ex:
            print(f"[card-trend] query failed for {metric}: {ex}")
            rows = []
        finally:
            cur.close()
            db.close()

        by_date = {}
        for r in rows:
            d = r.get('d')
            if d is None:
                continue
            key = d.isoformat() if hasattr(d, 'isoformat') else str(d)
            try:
                by_date[key] = int(r.get('v') or 0)
            except Exception:
                by_date[key] = 0

        days = []
        for i in range(7):
            day = start_date + timedelta(days=i)
            key = day.isoformat()
            days.append({'date': key, 'value': by_date.get(key, 0)})

        return jsonify({'status': 'success', 'metric': metric,
                        'label': label, 'days': days})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


def _jute_trend(branch_id, start_date, end_date):
    """
    Build the 7-day trend for the Jute card with three series, mirroring
    dashboard_stats:
      Recv  → SUM(weight)  from tbl_jute_received per day
      Issue → SUM(net_wt)  from assorting_entry  per day (entry_date)
      Stock → cumulative recv − cumulative issue, clamped at 0
    """
    s_iso, e_iso = start_date.isoformat(), end_date.isoformat()
    db  = get_db()
    cur = db.cursor(dictionary=True)
    recv_by_day, issue_by_day = {}, {}
    opening_recv = 0
    opening_issue = 0
    try:
        # Recv per day (within window)
        sql = ("SELECT recv_date AS d, COALESCE(SUM(weight),0) AS v "
               "FROM tbl_jute_received "
               "WHERE recv_date BETWEEN %s AND %s")
        params = [s_iso, e_iso]
        if branch_id:
            sql += " AND branch_id = %s"
            params.append(branch_id)
        sql += " GROUP BY recv_date"
        cur.execute(sql, tuple(params))
        for r in cur.fetchall():
            d = r['d']
            key = d.isoformat() if hasattr(d, 'isoformat') else str(d)
            recv_by_day[key] = int(r['v'] or 0)

        # Issue per day (assorting_entry as jute-consumption proxy)
        sql = ("SELECT entry_date AS d, COALESCE(SUM(net_wt),0) AS v "
               "FROM assorting_entry "
               "WHERE entry_date BETWEEN %s AND %s")
        params = [s_iso, e_iso]
        if branch_id:
            sql += " AND branch_id = %s"
            params.append(branch_id)
        sql += " GROUP BY entry_date"
        cur.execute(sql, tuple(params))
        for r in cur.fetchall():
            d = r['d']
            key = d.isoformat() if hasattr(d, 'isoformat') else str(d)
            issue_by_day[key] = int(r['v'] or 0)

        # Opening recv (cumulative weight received before the window starts)
        sql = ("SELECT COALESCE(SUM(weight),0) AS v "
               "FROM tbl_jute_received WHERE recv_date < %s")
        params = [s_iso]
        if branch_id:
            sql += " AND branch_id = %s"
            params.append(branch_id)
        cur.execute(sql, tuple(params))
        row = cur.fetchone() or {}
        opening_recv = int(row.get('v') or 0)

        # Opening issue (cumulative net_wt issued before the window starts)
        sql = ("SELECT COALESCE(SUM(net_wt),0) AS v "
               "FROM assorting_entry WHERE entry_date < %s")
        params = [s_iso]
        if branch_id:
            sql += " AND branch_id = %s"
            params.append(branch_id)
        cur.execute(sql, tuple(params))
        row = cur.fetchone() or {}
        opening_issue = int(row.get('v') or 0)
    except Exception as ex:
        print(f"[card-trend jute] query failed: {ex}")
    finally:
        cur.close()
        db.close()

    days = []
    running_recv  = opening_recv
    running_issue = opening_issue
    for i in range(7):
        day = start_date + timedelta(days=i)
        key = day.isoformat()
        r = recv_by_day.get(key, 0)
        i_v = issue_by_day.get(key, 0)
        running_recv  += r
        running_issue += i_v
        stock = max(0, running_recv - running_issue)
        days.append({
            'date': key,
            'values': [r, i_v, stock],
        })

    return jsonify({
        'status': 'success',
        'metric': 'jute',
        'label':  'Jute',
        'series': ['Recv', 'Issue', 'Stock'],
        'days':   days,
    })


def _spg_trend(branch_id, start_date, end_date):
    """
    Build the 7-day trend for Spg Prod with four series per day, mirroring
    dashboard_stats:
      Prod      → SUM(net_weight) from daily_doff_tbl
      Eff %     → SUM(weight)/SUM(hunprod)*100 from daily_doff_tbl + spinning_quality_mst
      Run Eff   → SUM(mc_runs_time)/SUM(8h)*100 from tbl_daily_vvfd_transaction
      Prd/Frame → Prod / COUNT(DISTINCT mc_id)
    """
    s_iso, e_iso = start_date.isoformat(), end_date.isoformat()
    prod_by_day, frames_by_day = {}, {}
    eff_by_day, runeff_by_day = {}, {}

    db  = get_db()
    cur = db.cursor(dictionary=True)
    try:
        # Prod + frames per day
        sql = ("SELECT doff_date AS d, "
               "COALESCE(SUM(net_weight),0) AS prod, "
               "COUNT(DISTINCT mc_id)       AS frames "
               "FROM daily_doff_tbl "
               "WHERE doff_date BETWEEN %s AND %s AND active = 1")
        params = [s_iso, e_iso]
        if branch_id:
            sql += " AND branch_id = %s"
            params.append(branch_id)
        sql += " GROUP BY doff_date"
        cur.execute(sql, tuple(params))
        for r in cur.fetchall():
            d = r['d']
            key = d.isoformat() if hasattr(d, 'isoformat') else str(d)
            prod_by_day[key]   = int(r['prod']   or 0)
            frames_by_day[key] = int(r['frames'] or 0)

        # Spinning Eff % per day
        eff_sql = """
            SELECT d, COALESCE(ROUND(SUM(weight)/NULLIF(SUM(hunprod),0)*100,0),0) AS v
            FROM (
                SELECT doff_date AS d, mc_id,
                       ROUND(SUM(speed*hrs*std_count*no_of_spindles*mcno)
                             / NULLIF(SUM(tpi*14400*2.2046*36),0), 0) AS hunprod,
                       SUM(weight) AS weight
                FROM (
                    SELECT ddt.doff_date, ddt.mc_id,
                           SUM(ddt.net_weight) AS weight,
                           sqm.speed, sqm.tpi, sqm.no_of_spindles,
                           8*60 AS hrs, sqm.std_count, 1 AS mcno
                    FROM daily_doff_tbl ddt
                    LEFT JOIN daily_doff_frames_winding ddfw
                           ON ddfw.mc_eb_id = ddt.mc_id
                          AND ddfw.tran_date = ddt.doff_date
                          AND ddfw.spell = ddt.spell
                          AND ddfw.spg_wdg = 'S'
                    LEFT JOIN spinning_quality_mst sqm
                           ON sqm.spg_quality_mst_id = ddfw.quality_id
                    WHERE ddt.doff_date BETWEEN %s AND %s {branch_clause}
                    GROUP BY ddt.doff_date, ddt.mc_id, sqm.speed, sqm.tpi,
                             sqm.no_of_spindles, sqm.std_count, sqm.tpi
                ) g GROUP BY d, mc_id
            ) h GROUP BY d
        """
        if branch_id:
            cur.execute(eff_sql.format(branch_clause="AND ddt.branch_id = %s"),
                        (s_iso, e_iso, branch_id))
        else:
            cur.execute(eff_sql.format(branch_clause=""), (s_iso, e_iso))
        for r in cur.fetchall():
            d = r['d']
            key = d.isoformat() if hasattr(d, 'isoformat') else str(d)
            eff_by_day[key] = int(r['v'] or 0)

        # Run Eff per day (no branch filter — column may not exist in VVFD table)
        cur.execute(
            """
            SELECT d, COALESCE(ROUND(SUM(mcrun)/NULLIF(SUM(tothrs),0)*100, 2), 0) AS v
            FROM (
                SELECT tran_date AS d, mc_id, spell_id,
                       SUM(mc_runs_time) AS mcrun,
                       1 AS mcno, 8 AS tothrs
                FROM tbl_daily_vvfd_transaction
                WHERE tran_date BETWEEN %s AND %s
                GROUP BY tran_date, mc_id, spell_id
            ) h GROUP BY d
            """,
            (s_iso, e_iso),
        )
        for r in cur.fetchall():
            d = r['d']
            key = d.isoformat() if hasattr(d, 'isoformat') else str(d)
            try:
                runeff_by_day[key] = float(r['v'] or 0)
            except Exception:
                runeff_by_day[key] = 0
    except Exception as ex:
        print(f"[card-trend spg] query failed: {ex}")
    finally:
        cur.close()
        db.close()

    days = []
    for i in range(7):
        day = start_date + timedelta(days=i)
        key = day.isoformat()
        prod   = prod_by_day.get(key, 0)
        frames = frames_by_day.get(key, 0)
        prd_frame = int(prod / frames) if frames > 0 else 0
        days.append({
            'date': key,
            'values': [
                prod,
                eff_by_day.get(key, 0),
                runeff_by_day.get(key, 0),
                prd_frame,
            ],
        })

    return jsonify({
        'status': 'success',
        'metric': 'spg',
        'label':  'Spg Prod',
        'series': ['Prod', 'Eff %', 'Run Eff', 'Prd/Frame'],
        'days':   days,
    })


def _winding_trend(branch_id, start_date, end_date):
    """
    Build the 7-day trend for Winding with two series per day:
      Prod     → SUM(net_weight) from daily_doff_frames_winding (spg_wdg='W')
      Avg Prod → Prod / COUNT(DISTINCT eb_id)   (avg production per winder)
    """
    s_iso, e_iso = start_date.isoformat(), end_date.isoformat()
    prod_by_day, winders_by_day = {}, {}

    db  = get_db()
    cur = db.cursor(dictionary=True)
    try:
        sql = ("SELECT tran_date AS d, "
               "COALESCE(SUM(net_weight),0) AS prod, "
               "COUNT(DISTINCT eb_id)       AS winders "
               "FROM daily_doff_frames_winding "
               "WHERE tran_date BETWEEN %s AND %s "
               "  AND spg_wdg = 'W' AND active = 1")
        params = [s_iso, e_iso]
        if branch_id:
            sql += " AND branch_id = %s"
            params.append(branch_id)
        sql += " GROUP BY tran_date"
        cur.execute(sql, tuple(params))
        for r in cur.fetchall():
            d = r['d']
            key = d.isoformat() if hasattr(d, 'isoformat') else str(d)
            prod_by_day[key]    = int(r['prod']    or 0)
            winders_by_day[key] = int(r['winders'] or 0)
    except Exception as ex:
        print(f"[card-trend winding] query failed: {ex}")
    finally:
        cur.close()
        db.close()

    days = []
    for i in range(7):
        day = start_date + timedelta(days=i)
        key = day.isoformat()
        prod    = prod_by_day.get(key, 0)
        winders = winders_by_day.get(key, 0)
        avg     = int(prod / winders) if winders > 0 else 0
        days.append({'date': key, 'values': [prod, avg]})

    return jsonify({
        'status': 'success',
        'metric': 'winding',
        'label':  'Winding',
        'series': ['Prod', 'Avg Prod'],
        'days':   days,
    })


def _others_trend(branch_id, start_date, end_date):
    """
    Build the 7-day trend for the Others / Finishing card with four series per day:
      Weaving → SUM(cuts) from tbl_daily_finishing
      Hemming → SUM(hemming)
      Heracle → SUM(heracle)
      H/Sewer → SUM(hand_sewer)
    Note: tbl_daily_finishing has no branch_id column, so branch filter is ignored.
    """
    s_iso, e_iso = start_date.isoformat(), end_date.isoformat()
    by_day = {}

    db  = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT tran_date AS d,
                   COALESCE(SUM(cuts),0)       AS weaving,
                   COALESCE(SUM(hemming),0)    AS hemming,
                   COALESCE(SUM(heracle),0)    AS heracle,
                   COALESCE(SUM(hand_sewer),0) AS hsewer
            FROM tbl_daily_finishing
            WHERE tran_date BETWEEN %s AND %s
            GROUP BY tran_date
            """,
            (s_iso, e_iso),
        )
        for r in cur.fetchall():
            d = r['d']
            key = d.isoformat() if hasattr(d, 'isoformat') else str(d)
            by_day[key] = (
                int(r['weaving'] or 0),
                int(r['hemming'] or 0),
                int(r['heracle'] or 0),
                int(r['hsewer']  or 0),
            )
    except Exception as ex:
        print(f"[card-trend others] query failed: {ex}")
    finally:
        cur.close()
        db.close()

    days = []
    for i in range(7):
        day = start_date + timedelta(days=i)
        key = day.isoformat()
        w, h, hc, hs = by_day.get(key, (0, 0, 0, 0))
        days.append({'date': key, 'values': [w, h, hc, hs]})

    return jsonify({
        'status': 'success',
        'metric': 'others',
        'label':  'Others',
        'series': ['Weaving', 'Hemming', 'Heracle', 'H/Sewer'],
        'days':   days,
    })


def _bales_trend(branch_id, start_date, end_date):
    """
    Build the 7-day trend for the Bales card with three series per day,
    mirroring dashboard_stats (no branch filter):
      Prod  → SUM(prod_bales)  from tbl_daily_bales_transaction
      Issue → SUM(issue_bales)
      Stock → opening cumulative (prod - issue) before window + running net each day
    """
    del branch_id  # intentionally unused — kept for caller signature symmetry
    s_iso, e_iso = start_date.isoformat(), end_date.isoformat()
    prod_by_day, issue_by_day = {}, {}
    opening_stock = 0

    db  = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT tran_date AS d, "
            "COALESCE(SUM(prod_bales),0)  AS prod, "
            "COALESCE(SUM(issue_bales),0) AS issue "
            "FROM tbl_daily_bales_transaction "
            "WHERE tran_date BETWEEN %s AND %s "
            "GROUP BY tran_date",
            (s_iso, e_iso),
        )
        for r in cur.fetchall():
            d = r['d']
            key = d.isoformat() if hasattr(d, 'isoformat') else str(d)
            prod_by_day[key]  = int(r['prod']  or 0)
            issue_by_day[key] = int(r['issue'] or 0)

        # Opening stock = cumulative (prod - issue) before the window starts
        cur.execute(
            "SELECT COALESCE(SUM(prod_bales - issue_bales),0) AS v "
            "FROM tbl_daily_bales_transaction "
            "WHERE tran_date < %s",
            (s_iso,),
        )
        row = cur.fetchone() or {}
        opening_stock = int(row.get('v') or 0)
    except Exception as ex:
        print(f"[card-trend bales] query failed: {ex}")
    finally:
        cur.close()
        db.close()

    days = []
    running_stock = opening_stock
    for i in range(7):
        day = start_date + timedelta(days=i)
        key = day.isoformat()
        p = prod_by_day.get(key, 0)
        s = issue_by_day.get(key, 0)
        running_stock += (p - s)
        days.append({'date': key, 'values': [p, s, running_stock]})

    return jsonify({
        'status': 'success',
        'metric': 'bales',
        'label':  'Bales',
        'series': ['Prod', 'Issue', 'Stock'],
        'days':   days,
    })
