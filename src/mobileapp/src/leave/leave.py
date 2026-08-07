import traceback
from flask import Blueprint, request, jsonify
from src.mobileapp.db import get_db
from datetime import datetime

leave_bp = Blueprint('leave', __name__)


# ── GET /leave-types ──────────────────────────────────────────────────────────

@leave_bp.route('/leave-types', methods=['GET'])
def get_leave_types():
    """Return all active leave types from leave_types table."""
    try:
        db     = get_db()
        cursor = db.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT leave_type_id  AS id,
                       leave_type_description AS leave_type_name
                FROM leave_types
                WHERE (is_active IS NULL OR is_active = 1)
                ORDER BY leave_type_description
            """)
            rows = cursor.fetchall()
        except Exception as ex:
            print('leave_types query error:', ex)
            rows = []
        cursor.close()
        db.close()
        return jsonify({'status': 'success', 'leave_types': rows})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── GET /status-mst ───────────────────────────────────────────────────────────

@leave_bp.route('/status-mst', methods=['GET'])
def get_status_mst():
    """Return statuses from status_mst table."""
    try:
        db     = get_db()
        cursor = db.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT status_id, status_name
                FROM status_mst
                ORDER BY status_id
            """)
            rows = cursor.fetchall()
        except Exception as ex:
            print('status_mst query error:', ex)
            rows = []
        cursor.close()
        db.close()
        return jsonify({'status': 'success', 'statuses': rows})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── GET /leave-transactions ───────────────────────────────────────────────────

@leave_bp.route('/leave-transactions', methods=['GET'])
def get_leave_transactions():
    try:
        branch_id = request.args.get('branch_id', type=int)
        from_date = request.args.get('from_date')
        to_date   = request.args.get('to_date')
        emp_code  = (request.args.get('emp_code') or '').strip() or None
        status_id = request.args.get('status_id', type=int)

        db     = get_db()
        cursor = db.cursor(dictionary=True)

        sql = """
            SELECT lt.leave_transaction_id              AS id,
                   lt.eb_id,
                   lt.leave_type_id,
                   ltp.leave_type_description           AS leave_type,
                   lt.leave_from_date                   AS from_date,
                   lt.leave_to_date                     AS to_date,
                   lt.no_of_days,
                   lt.leave_purpose                     AS reason,
                   lt.remarks,
                   lt.status                            AS status_id,
                   sm.status_name                       AS status,
                   lt.branch_id,
                   lt.updated_by,
                   lt.updated_date_time                 AS created_at,
                   COALESCE(o.emp_code, '')             AS emp_code,
                   TRIM(CONCAT(
                       COALESCE(p.first_name,''), ' ',
                       COALESCE(p.middle_name,''), ' ',
                       COALESCE(p.last_name,''))) AS emp_name
            FROM leave_transactions lt
            LEFT JOIN hrms_ed_official_details o  ON lt.eb_id = o.eb_id
            LEFT JOIN hrms_ed_personal_details  p ON lt.eb_id = p.eb_id
            LEFT JOIN leave_types              ltp ON lt.leave_type_id = ltp.leave_type_id
            LEFT JOIN status_mst               sm  ON lt.status = sm.status_id
            WHERE 1=1
        """
        params = []

        if branch_id:
            sql += " AND lt.branch_id = %s";         params.append(branch_id)
        if from_date:
            sql += " AND lt.leave_from_date >= %s";  params.append(from_date)
        if to_date:
            sql += " AND lt.leave_to_date <= %s";    params.append(to_date)
        if emp_code:
            sql += " AND o.emp_code = %s";           params.append(emp_code)
        if status_id:
            sql += " AND lt.status = %s";            params.append(status_id)

        sql += " ORDER BY lt.leave_transaction_id DESC"
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()

        transactions = []
        for row in rows:
            # Format dates in Python to avoid %% escaping issues
            for col in ('from_date', 'to_date'):
                v = row.get(col)
                if v and hasattr(v, 'strftime'):
                    row[col] = v.strftime('%Y-%m-%d')
                elif v:
                    row[col] = str(v)[:10]
            if row.get('created_at') and hasattr(row['created_at'], 'strftime'):
                row['created_at'] = row['created_at'].strftime('%Y-%m-%d %H:%M')
            try:
                cursor.execute("""
                    SELECT lvd_tran_id AS id, ltran_id AS tran_id,
                           leave_date
                    FROM leave_tran_details
                    WHERE ltran_id = %s ORDER BY leave_date
                """, (row['id'],))
                details = cursor.fetchall()
                for d in details:
                    v = d.get('leave_date')
                    if v and hasattr(v, 'strftime'):
                        d['leave_date'] = v.strftime('%Y-%m-%d')
                    elif v:
                        d['leave_date'] = str(v)[:10]
                row['details'] = details
            except Exception:
                row['details'] = []
            transactions.append(row)

        cursor.close()
        db.close()
        return jsonify({'status': 'success', 'transactions': transactions})

    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── POST /leave-transactions ──────────────────────────────────────────────────

@leave_bp.route('/leave-transactions', methods=['POST'])
def save_leave_transaction():
    """Create a new leave transaction with detail rows."""
    try:
        data          = request.json or {}
        eb_id         = data.get('eb_id')
        leave_type_id = data.get('leave_type_id')
        from_date     = data.get('from_date')
        to_date       = data.get('to_date')
        reason        = data.get('reason', '')
        remarks       = data.get('remarks', '')
        status_id     = data.get('status_id', 3) or 3   # default 3
        branch_id     = data.get('branch_id')
        user_id       = data.get('user_id')
        details       = data.get('details', [])

        if not eb_id or not from_date or not to_date:
            return jsonify({'status': 'error',
                            'message': 'eb_id, from_date and to_date are required'}), 400

        # Calculate no_of_days (use sent value or compute)
        try:
            from datetime import date as date_cls
            d1 = date_cls.fromisoformat(from_date)
            d2 = date_cls.fromisoformat(to_date)
            calculated_days = (d2 - d1).days + 1
            if calculated_days < 1:
                calculated_days = 1
        except Exception:
            calculated_days = 1
        no_of_days = data.get('no_of_days') or calculated_days

        db     = get_db()
        cursor = db.cursor(dictionary=True)
        now    = datetime.now()

        cursor.execute("""
            INSERT INTO leave_transactions
                (branch_id, eb_id, leave_from_date, leave_purpose, leave_to_date,
                 leave_type_id, no_of_days, remarks, status, updated_by, updated_date_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (branch_id, eb_id, from_date, reason, to_date,
              leave_type_id, no_of_days, remarks, status_id, user_id, now))

        tran_id = cursor.lastrowid

        for d in details:
            try:
                cursor.execute("""
                    INSERT INTO leave_tran_details (ltran_id, leave_date, updated_bt, updated_date_time)
                    VALUES (%s, %s, %s, %s)
                """, (tran_id, d.get('leave_date'), user_id, now))
            except Exception as ex:
                print('leave_tran_details insert error:', ex)
                traceback.print_exc()
                break

        db.commit()
        cursor.close()
        db.close()
        return jsonify({'status': 'success', 'message': 'Leave saved successfully', 'id': tran_id})

    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── DELETE /leave-transactions/<id> ──────────────────────────────────────────

@leave_bp.route('/leave-transactions/<int:tran_id>', methods=['DELETE'])
def delete_leave_transaction(tran_id):
    """Delete a leave transaction and its details."""
    try:
        db     = get_db()
        cursor = db.cursor()
        try:
            cursor.execute("DELETE FROM leave_tran_details WHERE ltran_id = %s", (tran_id,))
        except Exception as ex:
            print('leave_tran_details delete skipped:', ex)
        cursor.execute("DELETE FROM leave_transactions WHERE leave_transaction_id = %s", (tran_id,))
        db.commit()
        cursor.close()
        db.close()
        return jsonify({'status': 'success', 'message': 'Leave deleted successfully'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

