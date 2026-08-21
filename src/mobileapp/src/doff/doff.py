"""Spinning Doff entry endpoints.

Tables (sjm database):
  - daily_doff_tbl       (header rows, columns: daily_doff_tbl_id, doff_date, spell,
                          mc_id, quality_id, trolly_id, gross_weight,
                          tare_weight, net_weight, active, branch_id, updated_by,
                          updated_date_time, weight_type)
  - spinning_quality_mst (spg_quality_mst_id, spg_quality, ...)
  - trolly_mst           (trolly_id, trolly_name, trolly_weight, busket_weight, ...)
  - machine_mst          (machine_id, machine_name, mech_code, ...)
  - spell_mst            (spell_id, spell_name, ...)
  - hrms_ed_official_details / hrms_ed_personal_details (employee lookup)
"""
import traceback
from datetime import datetime, date as date_cls

from flask import Blueprint, request, jsonify
from src.mobileapp.db import get_db

doff_bp = Blueprint('doff', __name__)


# â”€â”€ helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _to_str(v):
    if v is None:
        return None
    if hasattr(v, 'strftime'):
        try:
            return v.strftime('%Y-%m-%d')
        except Exception:
            return str(v)
    return str(v)


# â”€â”€ GET /spells â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@doff_bp.route('/spells', methods=['GET'])
def get_spells():
    try:
        db = get_db()
        cur = db.cursor(dictionary=True)
        branch_id = request.args.get('branch_id', type=int)
        print('Received branch_id for spells:', branch_id)
        params = []
        if branch_id:
            sql = """
            SELECT sm.spell_id, sm.spell_name
            FROM spell_mst sm
            JOIN shift_mst sh ON sh.shift_id = sm.shift_id
            WHERE (sm.status IS NULL OR sm.status = 1)
              AND sh.branch_id = %s"""
            params.append(branch_id)
        else:
            sql = """
            SELECT spell_id, spell_name
            FROM spell_mst
            WHERE (status IS NULL OR status = 1)"""
        sql += " ORDER BY spell_name"
        print('Executing SQL:', sql, 'with params:', params)
            
        try:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        except Exception as ex:
            print('spells query error:', ex)
            rows = []
        cur.close(); db.close()
        return jsonify({'status': 'success', 'spells': rows})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# â”€â”€ GET /doff/machines â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@doff_bp.route('/doff/machines', methods=['GET'])
def get_doff_machines():
    try:
        branch_id = request.args.get('branch_id', type=int)
        db = get_db()
        cur = db.cursor(dictionary=True)
        sql = """
            SELECT machine_id   AS mc_id,
                   machine_name AS mc_name,
                   mech_code    AS mc_code,
                   dept_id
            FROM machine_mst
            WHERE (active IS NULL OR active = 1)
        """
        params = []
        if branch_id:
            # machine_mst doesn't have branch_id directly; ignore filter
            pass
        sql += " ORDER BY machine_name"
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        cur.close(); db.close()
        return jsonify({'status': 'success', 'machines': rows})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# â”€â”€ GET /doff/qualities â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@doff_bp.route('/doff/qualities', methods=['GET'])
def get_doff_qualities():
    try:
        branch_id = request.args.get('branch_id', type=int)
        db = get_db()
        cur = db.cursor(dictionary=True)
        sql = """
               SELECT spg_quality_mst_id AS quality_id,
                   concat(stm.spg_type_name,'-',spg_quality,' ',sqm.no_of_spindles,' Spindles'  )        AS quality_name 
            FROM spinning_quality_mst sqm
			left join spinning_type_mst stm on stm.spg_type_mst_id =sqm.spg_type_id 
            WHERE 1=1
        """
        params = []
        if branch_id:
            sql += " AND (branch_id IS NULL OR branch_id = %s)"
            params.append(branch_id)
        sql += " ORDER BY spg_quality"
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        cur.close(); db.close()
        return jsonify({'status': 'success', 'qualities': rows})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# â”€â”€ GET /doff/trollies â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@doff_bp.route('/doff/trollies', methods=['GET'])
def get_doff_trollies():
    try:
        branch_id = request.args.get('branch_id', type=int)
        db = get_db()
        cur = db.cursor(dictionary=True)
        sql = """
            SELECT trolly_id,
                   trolly_name,
                   trolly_weight,
                   busket_weight AS bucket_weight
            FROM trolly_mst
            WHERE 1=1
        """
        params = []
        if branch_id:
            sql += " AND (branch_id IS NULL OR branch_id = %s)"
            params.append(branch_id)
        sql += " ORDER BY trolly_name"
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        # cast decimals to float for clean JSON
        for r in rows:
            for k in ('trolly_weight', 'bucket_weight'):
                if r.get(k) is not None:
                    try: r[k] = float(r[k])
                    except Exception: pass
        cur.close(); db.close()
        return jsonify({'status': 'success', 'trollies': rows})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# â”€â”€ GET /doff-transactions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@doff_bp.route('/doff-transactions', methods=['GET'])
def list_doff_transactions():
    try:
        date_q    = request.args.get('date')
        spell_id  = request.args.get('spell_id', type=int)
        branch_id = request.args.get('branch_id', type=int)
        mc_id     = request.args.get('mc_id', type=int)

        db = get_db()
        cur = db.cursor(dictionary=True)
        sql = """
            SELECT d.daily_doff_tbl_id   AS id,
                   d.doff_date,
                   d.spell                AS spell_id,
                   sp.spell_name,
                   d.mc_id,
                   m.machine_name         AS mc_name,
                   m.mech_code            AS mc_code,
                   d.quality_id,
                   q.spg_quality          AS quality_name,
                   d.trolly_id,
                   t.trolly_name,
                   t.trolly_weight,
                   t.busket_weight        AS bucket_weight,
                   d.gross_weight,
                   d.tare_weight,
                   d.net_weight,
                   d.weight_type,
                   d.branch_id,
                   d.updated_by,
                   d.updated_date_time
            FROM daily_doff_tbl d
            LEFT JOIN spell_mst            sp ON sp.spell_id           = d.spell
            LEFT JOIN machine_mst          m  ON m.machine_id          = d.mc_id
            LEFT JOIN spinning_quality_mst q  ON q.spg_quality_mst_id  = d.quality_id
            LEFT JOIN trolly_mst           t  ON t.trolly_id           = d.trolly_id
            WHERE (d.active IS NULL OR d.active = 1)
        """
        params = []
        if date_q:
            sql += " AND d.doff_date = %s"; params.append(date_q)
        if spell_id:
            sql += " AND d.spell = %s";     params.append(spell_id)
        if branch_id:
            sql += " AND d.branch_id = %s"; params.append(branch_id)
        if mc_id:
            sql += " AND d.mc_id = %s";     params.append(mc_id)
        sql += " ORDER BY d.doff_date DESC, d.daily_doff_tbl_id DESC"

        print('GET /doff-transactions SQL:', sql)
        print('GET /doff-transactions params:', params)
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        print('GET /doff-transactions row count:', len(rows))

        out = []
        for r in rows:
            r['doff_date'] = _to_str(r.get('doff_date'))
            ud = r.get('updated_date_time')
            if ud and hasattr(ud, 'strftime'):
                r['updated_date_time'] = ud.strftime('%Y-%m-%d %H:%M')
            for k in ('gross_weight', 'tare_weight', 'net_weight',
                      'trolly_weight', 'bucket_weight'):
                v = r.get(k)
                if v is not None:
                    try: r[k] = float(v)
                    except Exception: pass
            out.append(r)

        cur.close(); db.close()
        return jsonify({'status': 'success', 'transactions': out})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# â”€â”€ GET /doff/last-by-machine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@doff_bp.route('/doff/last-by-machine', methods=['GET'])
def get_doff_last_by_machine():
    """Return last quality_id and trolly_id used for a given machine in the
    daily_doff_tbl."""
    try:
        mc_id = request.args.get('mc_id', type=int)
        if not mc_id:
            return jsonify({'status': 'error', 'message': 'mc_id required'}), 400

        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT d.quality_id, q.spg_quality AS quality_name,
                   d.trolly_id,  t.trolly_name,
                   t.trolly_weight, t.busket_weight AS bucket_weight
            FROM daily_doff_tbl d
            LEFT JOIN spinning_quality_mst q ON q.spg_quality_mst_id = d.quality_id
            LEFT JOIN trolly_mst           t ON t.trolly_id          = d.trolly_id
            WHERE d.mc_id = %s
            ORDER BY d.doff_date DESC, d.daily_doff_tbl_id DESC
            LIMIT 1
        """, (mc_id,))
        row = cur.fetchone() or {}
        for k in ('trolly_weight', 'bucket_weight'):
            v = row.get(k)
            if v is not None:
                try: row[k] = float(v)
                except Exception: pass
        cur.close(); db.close()
        return jsonify({'status': 'success', **row})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# â”€â”€ POST /doff-transactions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@doff_bp.route('/doff-transactions', methods=['POST'])
def save_doff_transaction():
    """Insert (no id) or update (id provided) a doff entry."""
    try:
        data = request.json or {}
        rec_id       = data.get('id')
        doff_date    = data.get('doff_date')
        spell_id     = data.get('spell_id')
        mc_id        = data.get('mc_id')
        quality_id   = data.get('quality_id')
        trolly_id    = data.get('trolly_id')
        gross_weight = data.get('gross_weight') or 0
        tare_weight  = data.get('tare_weight')  or 0
        net_weight   = data.get('net_weight')
        if net_weight is None:
            try:
                net_weight = float(gross_weight) - float(tare_weight)
            except Exception:
                net_weight = 0
        weight_type  = (data.get('weight_type') or '').strip() or None
        branch_id    = data.get('branch_id')
        user_id      = data.get('user_id') or 0

        missing = [f for f, v in [('doff_date', doff_date), ('spell_id', spell_id),
                                   ('mc_id', mc_id), ('trolly_id', trolly_id),
                                   ('branch_id', branch_id)] if not v]
        print('POST /doff-transactions data:', data)
        print('POST /doff-transactions missing fields:', missing)
        if missing:
            return jsonify({'status': 'error',
                            'message': f'Missing required fields: {", ".join(missing)}'}), 400

        db = get_db()
        cur = db.cursor()
        now = datetime.now()

        if rec_id:
            sql = """
                UPDATE daily_doff_tbl SET
                    doff_date = %s, spell = %s, mc_id = %s, quality_id = %s,
                    trolly_id = %s,
                    gross_weight = %s, tare_weight = %s, net_weight = %s,
                    weight_type = %s, branch_id = %s,
                    updated_by = %s, updated_date_time = %s
                WHERE daily_doff_tbl_id = %s
            """
            params = (doff_date, spell_id, mc_id, quality_id, trolly_id,
                      gross_weight, tare_weight, net_weight, weight_type, branch_id,
                      user_id, now, rec_id)
            print('POST /doff-transactions UPDATE SQL:', sql)
            print('POST /doff-transactions UPDATE params:', params)
            cur.execute(sql, params)
            saved_id = rec_id
        else:
            sql = """
                INSERT INTO daily_doff_tbl
                    (doff_date, spell, mc_id, quality_id, trolly_id,
                     gross_weight, tare_weight, net_weight, active, branch_id,
                     updated_by, updated_date_time, weight_type)
                VALUES
                    (%s, %s, %s, %s, %s,
                     %s, %s, %s, 1, %s,
                     %s, %s, %s)
            """
            params = (doff_date, spell_id, mc_id, quality_id, trolly_id,
                      gross_weight, tare_weight, net_weight, branch_id,
                      user_id, now, weight_type)
            print('POST /doff-transactions INSERT SQL:', sql)
            print('POST /doff-transactions INSERT params:', params)
            cur.execute(sql, params)
            saved_id = cur.lastrowid

        db.commit()
        cur.close(); db.close()
        return jsonify({'status': 'success',
                        'message': 'Doff entry saved successfully',
                        'id': saved_id})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# â”€â”€ DELETE /doff-transactions/<id> â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@doff_bp.route('/doff-transactions/<int:rec_id>', methods=['DELETE'])
def delete_doff_transaction(rec_id):
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("DELETE FROM daily_doff_tbl WHERE daily_doff_tbl_id = %s",
                    (rec_id,))
        db.commit()
        cur.close(); db.close()
        return jsonify({'status': 'success', 'message': 'Doff entry deleted'})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500





# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# WINDING ENTRY 2 - QUALITY-WISE SHIFT-WISE REPORT
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@doff_bp.route('/doff/winding-entry-2-quality-shift-report', methods=['GET'])
def winding_entry2_quality_shift_report():
    """Quality-wise Shift-wise production report for Winding Entry (2).
    
    Returns quality-wise breakdown with shift A/B/C totals for a given date+branch.
    
    Query params:
      ?date=YYYY-MM-DD  (required)
      ?branch_id=<id>   (required)
    
    Response:
      {
        status: 'success',
        report: [{
          quality_name: str,
          shift_a: float,
          shift_b: float,
          shift_c: float,
          total: float
        }],
        grand_total: {
          shift_a: float,
          shift_b: float,
          shift_c: float,
          total: float
        }
      }
    """
    d = request.args.get('date')
    branch_id = request.args.get('branch_id', type=int)
    
    if not d:
        return jsonify({'status': 'error', 'message': 'date is required'}), 400
    if not branch_id:
        return jsonify({'status': 'error', 'message': 'branch_id is required'}), 400
    
    try:
        db = get_db()
        cur = db.cursor(dictionary=True)
        
        # Query: Get quality-wise shift-wise totals
        # Note: Using wng_quality from winding_quality_master table
        cur.execute("""
            SELECT 
                COALESCE(q.wng_quality, 'Unknown') AS quality_name,
                COALESCE(SUM(CASE WHEN s.spell_name LIKE '%%A%%' THEN w.net_weight ELSE 0 END), 0) AS shift_a,
                COALESCE(SUM(CASE WHEN s.spell_name LIKE '%%B%%' THEN w.net_weight ELSE 0 END), 0) AS shift_b,
                COALESCE(SUM(CASE WHEN s.spell_name LIKE '%%C%%' THEN w.net_weight ELSE 0 END), 0) AS shift_c,
                COALESCE(SUM(w.net_weight), 0) AS total
            FROM daily_doff_frames_winding w
			left join daily_doff_frames_winding ddfw on ddfw.mc_eb_id =w.eb_id and ddfw.tran_date =w.tran_date 
			and ddfw.spell =w.spell and ddfw.eb_id is null
            LEFT JOIN spell_mst s ON w.spell_id = s.spell_id
            LEFT JOIN winding_quality_master q ON ddfw.quality_id = q.wng_quality_mst_id
            WHERE w.tran_date = %s
              AND w.branch_id = %s
              AND w.spg_wdg = 'W'
              AND w.net_weight IS NOT NULL
              AND (w.active IS NULL OR w.active = 1)
            GROUP BY q.wng_quality
            ORDER BY q.wng_quality
        """, (d, branch_id))
        
        report_rows = cur.fetchall()
        
        # Calculate grand totals
        grand_total_a = sum(float(row['shift_a'] or 0) for row in report_rows)
        grand_total_b = sum(float(row['shift_b'] or 0) for row in report_rows)
        grand_total_c = sum(float(row['shift_c'] or 0) for row in report_rows)
        grand_total = sum(float(row['total'] or 0) for row in report_rows)
        
        # Convert to float for JSON serialization
        for row in report_rows:
            row['shift_a'] = float(row['shift_a'] or 0)
            row['shift_b'] = float(row['shift_b'] or 0)
            row['shift_c'] = float(row['shift_c'] or 0)
            row['total'] = float(row['total'] or 0)
        
        cur.close()
        db.close()
        
        return jsonify({
            'status': 'success',
            'message': 'Quality-wise shift-wise report generated',
            'report': report_rows,
            'grand_total': {
                'shift_a': grand_total_a,
                'shift_b': grand_total_b,
                'shift_c': grand_total_c,
                'total': grand_total
            }
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- schema migration helper --------------------------------------------------
_FRAME_SCHEMA_OK = False

def _ensure_frame_schema():
    """Add quality_id INT NULL column to daily_doff_frames_winding if missing.

    Safe to call repeatedly; only runs the ALTER on first invocation per
    process. Errors are swallowed so the endpoints keep working when the
    column already exists or when the user lacks ALTER privileges (in which
    case the DBA must apply the migration manually).
    """
    global _FRAME_SCHEMA_OK
    if _FRAME_SCHEMA_OK:
        return
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME   = 'daily_doff_frames_winding'
               AND COLUMN_NAME  = 'quality_id'
        """)
        (exists,) = cur.fetchone()
        if not exists:
            cur.execute("""
                ALTER TABLE daily_doff_frames_winding
                  ADD COLUMN quality_id INT NULL AFTER mc_eb_id
            """)
            db.commit()
        cur.close(); db.close()
        _FRAME_SCHEMA_OK = True
    except Exception as ex:
        print('frame schema ensure failed:', ex)


# -- GET /doff/frame-entries --------------------------------------------------
@doff_bp.route('/doff/frame-entries', methods=['GET'])
def get_frame_entries():
    """Return active frame mc_ids for a (date, spell, branch).

    spg_wdg = 'S' (spinning) for this screen.
    """
    try:
        d         = request.args.get('date')
        spell_id  = request.args.get('spell_id',  type=int)
        branch_id = request.args.get('branch_id', type=int)
        if not (d and spell_id and branch_id):
            return jsonify({'status': 'error',
                            'message': 'date, spell_id and branch_id are required'}), 400

        _ensure_frame_schema()
        db = get_db()
        cur = db.cursor(dictionary=True)
        sql = """
            SELECT daily_doff_frm_wdg_id AS id,
                   mc_eb_id              AS mc_id,
                   quality_id            AS quality_id
            FROM daily_doff_frames_winding
            WHERE tran_date = %s
              AND spell     = %s
              AND branch_id = %s
              AND (spg_wdg IS NULL OR spg_wdg = 'S')
              AND (active IS NULL OR active = 1)
        """
        cur.execute(sql, (d, spell_id, branch_id))
        rows = cur.fetchall()
        cur.close(); db.close()
        return jsonify({
            'status': 'success',
            'mc_ids': [r['mc_id'] for r in rows],
            'entries': [
                {'mc_id': r['mc_id'], 'quality_id': r.get('quality_id')}
                for r in rows
            ],
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- POST /doff/frame-entries -------------------------------------------------
@doff_bp.route('/doff/frame-entries', methods=['POST'])
def save_frame_entries():
    """Bulk save: replace existing frame rows for (date, spell, branch).

    Body (preferred): {date, spell_id, branch_id, user_id,
                       entries: [{mc_id, quality_id}, ...]}
    Legacy:           {date, spell_id, branch_id, user_id, mc_ids: [int, ...]}
    Strategy: hard-delete existing rows for the key, then insert one row per
    entry with active=1, spg_wdg='S' and the chosen quality_id.
    """
    try:
        data = request.get_json(silent=True) or {}
        d         = data.get('date')
        spell_id  = data.get('spell_id')
        branch_id = data.get('branch_id')
        user_id   = data.get('user_id') or 0
        entries   = data.get('entries')
        mc_ids    = data.get('mc_ids') or []
        if not (d and spell_id and branch_id):
            return jsonify({'status': 'error',
                            'message': 'date, spell_id and branch_id are required'}), 400

        # Normalise to a list of (mc_id, quality_id) tuples
        pairs = []
        if isinstance(entries, list):
            for e in entries:
                if not isinstance(e, dict):
                    continue
                mc = e.get('mc_id')
                if mc is None:
                    continue
                try:
                    pairs.append((int(mc), int(e['quality_id'])
                                  if e.get('quality_id') is not None else None))
                except (TypeError, ValueError):
                    pass
        elif isinstance(mc_ids, list):
            for mc in mc_ids:
                try:
                    pairs.append((int(mc), None))
                except (TypeError, ValueError):
                    pass
        else:
            return jsonify({'status': 'error',
                            'message': 'entries must be an array'}), 400

        _ensure_frame_schema()
        db = get_db()
        cur = db.cursor()
        # Clear existing spinning frame rows for this date+spell+branch
        cur.execute("""
            DELETE FROM daily_doff_frames_winding
            WHERE tran_date = %s
              AND spell     = %s
              AND branch_id = %s
              AND (spg_wdg IS NULL OR spg_wdg = 'S')
        """, (d, spell_id, branch_id))

        inserted = 0
        if pairs:
            ins = """
                INSERT INTO daily_doff_frames_winding
                    (tran_date, spell, mc_eb_id, quality_id, spg_wdg, branch_id, active)
                VALUES (%s, %s, %s, %s, 'S', %s, 1)
            """
            for mc, qid in pairs:
                try:
                    cur.execute(ins, (d, spell_id, mc, qid, branch_id))
                    inserted += 1
                except Exception as ex:
                    print('frame insert err for mc', mc, ex)

        db.commit()
        cur.close(); db.close()
        return jsonify({
            'status':  'success',
            'message': f'Saved {inserted} frame(s)',
            'count':   inserted,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@doff_bp.route('/doff/spg1-mech-codes', methods=['GET'])
def get_spg1_mech_codes():
    """Return distinct mech_posting_code values for machines listed in
    daily_doff_frames_winding for the given date/spell/branch.
    Query params: date (YYYY-MM-DD), spell_id (int), branch_id (int).
    Returns: [{mech_posting_code, mc_id, mc_name, mc_code}, ...]
    """
    try:
        d         = request.args.get('date')
        spell_id  = request.args.get('spell_id',  type=int)
        branch_id = request.args.get('branch_id', type=int)
        if not (d and spell_id and branch_id):
            return jsonify({'status': 'error',
                            'message': 'date, spell_id and branch_id are required'}), 400
        db  = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT DISTINCT
                   m.machine_id        AS mc_id,
                   m.machine_name      AS mc_name,
                   m.mech_code         AS mc_code,
                   m.mech_posting_code AS mech_posting_code
            FROM daily_doff_frames_winding dfw
            INNER JOIN machine_mst m
                    ON m.machine_id = dfw.mc_eb_id
            WHERE dfw.tran_date = %s
              AND dfw.spell     = %s
              AND dfw.branch_id = %s
              AND (dfw.spg_wdg IS NULL OR dfw.spg_wdg = 'S')
              AND (dfw.active IS NULL OR dfw.active = 1)
            ORDER BY m.mech_posting_code
        """, (d, spell_id, branch_id))
        rows = cur.fetchall()
        cur.close(); db.close()
        return jsonify({
            'status': 'success',
            'codes': [
                {
                    'mc_id':             int(r['mc_id']),
                    'mc_name':           r.get('mc_name') or '',
                    'mc_code':           r.get('mc_code') or '',
                    'mech_posting_code': int(r['mech_posting_code']) if r.get('mech_posting_code') is not None else None,
                }
                for r in rows
            ]
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500
# -- GET /doff/spg1-summary ---------------------------------------------------
@doff_bp.route('/doff/spg1-summary', methods=['GET'])
def get_spg1_summary():
    """Return per-machine summary for spinning doff entries.
    Groups daily_doff_tbl rows (weight_type 'SPG1' manual / 'Auto' scale) by machine for the given
    date/spell/branch. Returns mech_posting_code, individual net weights,
    count and total.
    Query params: date (YYYY-MM-DD), spell_id (int), branch_id (int).
    """
    try:
        d         = request.args.get('date')
        spell_id  = request.args.get('spell_id',  type=int)
        branch_id = request.args.get('branch_id', type=int)
        if not (d and spell_id and branch_id):
            return jsonify({'status': 'error',
                            'message': 'date, spell_id and branch_id are required'}), 400
        db  = get_db()
        cur = db.cursor(dictionary=True)
        sql = """
            SELECT  dt.mc_id,
                    m.mech_code         AS mc_code,
                    m.machine_name      AS mc_name,
                    m.mech_posting_code AS mech_posting_code,
                    dt.net_weight,
                    dt.daily_doff_tbl_id
            FROM daily_doff_tbl dt
            INNER JOIN machine_mst m ON m.machine_id = dt.mc_id
            WHERE dt.doff_date  = %s
              AND dt.spell      = %s
              AND dt.branch_id  = %s
              AND dt.weight_type IN ('SPG1', 'Auto')
              AND (dt.active IS NULL OR dt.active = 1)
            ORDER BY m.mech_posting_code, dt.daily_doff_tbl_id
        """
        params = (d, spell_id, branch_id)
        print('GET /doff/spg1-summary SQL:', sql)
        print('GET /doff/spg1-summary params:', params)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close(); db.close()
        # Group by mc_id
        from collections import OrderedDict
        grouped = OrderedDict()
        for r in rows:
            mc_id = r['mc_id']
            if mc_id not in grouped:
                grouped[mc_id] = {
                    'mc_id':             int(mc_id),
                    'mc_code':           r.get('mc_code') or '',
                    'mc_name':           r.get('mc_name') or '',
                    'mech_posting_code': int(r['mech_posting_code']) if r.get('mech_posting_code') is not None else None,
                    'weights':           [],
                    'no_of_doff':        0,
                    'total_wt':          0.0,
                }
            wt = float(r['net_weight'] or 0)
            grouped[mc_id]['weights'].append(wt)
            grouped[mc_id]['no_of_doff'] += 1
            grouped[mc_id]['total_wt']   += wt
        summary = list(grouped.values())
        for s in summary:
            s['total_wt'] = round(s['total_wt'], 3)
        return jsonify({'status': 'success', 'summary': summary})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# -- FRAME ENTRY ENDPOINTS --

# -- GET /doff/frame-machines -------------------------------------------------
@doff_bp.route('/doff/frame-machines', methods=['GET'])
def get_frame_machines():
    """List spinning-frame machines (machine_type_id = 36) for a branch."""
    try:
        branch_id = request.args.get('branch_id', type=int)
        if not branch_id:
            return jsonify({'status': 'error', 'message': 'branch_id required'}), 400

        db = get_db()
        cur = db.cursor(dictionary=True)
        sql = """
            SELECT mm.machine_id   AS mc_id,
                   mm.machine_name AS mc_name,
                   mm.mech_code    AS mc_code
            FROM machine_mst mm
            LEFT JOIN dept_mst dm ON dm.dept_id = mm.dept_id
            WHERE dm.branch_id = %s
              AND mm.machine_type_id = 36
              AND (mm.active IS NULL OR mm.active = 1)
            ORDER BY mm.machine_id DESC
        """
        cur.execute(sql, (branch_id,))
        rows = cur.fetchall()
        cur.close(); db.close()
        return jsonify({'status': 'success', 'machines': rows})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- GET /doff/last-quality-by-mc --------------------------------------------

@doff_bp.route('/doff/last-quality-by-mc', methods=['GET'])
def get_doff_last_quality_by_mc():
    """For branch_id, return most-recently used quality_id per mc from daily_doff_frames_winding.
    spg_wdg = 'S' for spinning (default), 'W' for winding (?type=W).
    Response: {success: true, data: {"<mc_id>": quality_id, ...}}
    """
    branch_id = request.args.get('branch_id', type=int)
    spg_wdg   = (request.args.get('type') or 'S').upper()
    if not branch_id:
        return jsonify({'success': False, 'message': 'branch_id required', 'data': {}}), 400
    try:
        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT f.mc_eb_id   AS mc_id,
                   f.quality_id AS quality_id
            FROM daily_doff_frames_winding f
            INNER JOIN (
                SELECT mc_eb_id, MAX(daily_doff_frm_wdg_id) AS max_id
                FROM daily_doff_frames_winding
                WHERE branch_id  = %s
                  AND quality_id IS NOT NULL
                  AND spg_wdg    = %s
                GROUP BY mc_eb_id
            ) lf ON lf.mc_eb_id = f.mc_eb_id
               AND lf.max_id    = f.daily_doff_frm_wdg_id
        """, (branch_id, spg_wdg))
        rows = cur.fetchall()
        cur.close(); db.close()
        data = {str(r['mc_id']): r['quality_id']
                for r in rows if r.get('quality_id') is not None}
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e), 'data': {}}), 500


# -- GET /doff/winding-qualities ---------------------------------------------

@doff_bp.route('/doff/winding-qualities', methods=['GET'])
def get_doff_winding_qualities():
    """Return rows from winding_quality_master.
    branch_id is accepted for forward-compatibility (table has no branch_id column yet).
    """
    try:
        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT wng_quality_mst_id AS quality_id,
                   wng_quality        AS quality_name
            FROM winding_quality_master
            ORDER BY wng_quality
        """)
        rows = cur.fetchall()
        cur.close(); db.close()
        return jsonify({'status': 'success', 'qualities': rows})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e), 'qualities': []}), 500

# =============================================================================
# CONTINUOUS WINDING ENTRY  (tbl_cont_widning_entry: date + quality + prod_kgs)
# =============================================================================

def _ensure_cont_winding_table(cur):
    """Create tbl_cont_widning_entry if it doesn't exist (idempotent)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tbl_cont_widning_entry (
            cont_winding_ent_id INT(11) NOT NULL AUTO_INCREMENT,
            tran_date           DATE        DEFAULT NULL,
            quality_id          INT(11)     DEFAULT NULL,
            prod_kgs            INT(11)     DEFAULT NULL,
            updated_by          INT(11)     DEFAULT NULL,
            updated_date_time   TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (cont_winding_ent_id)
        )
    """)


# -- GET /doff/cont-winding-entries -------------------------------------------
@doff_bp.route('/doff/cont-winding-entries', methods=['GET'])
def list_cont_winding_entries():
    """List continuous-winding rows for a date, joined with quality name.
    Query: date=YYYY-MM-DD (required).
    """
    date_q = request.args.get('date')
    if not date_q:
        return jsonify({'status': 'error', 'message': 'date required', 'entries': []}), 400
    try:
        db  = get_db()
        cur = db.cursor(dictionary=True)
        _ensure_cont_winding_table(cur)
        cur.execute("""
            SELECT c.cont_winding_ent_id AS id,
                   c.tran_date,
                   c.quality_id,
                   q.wng_quality        AS quality_name,
                   c.prod_kgs
            FROM tbl_cont_widning_entry c
            LEFT JOIN winding_quality_master q ON q.wng_quality_mst_id = c.quality_id
            WHERE c.tran_date = %s
            ORDER BY c.cont_winding_ent_id DESC
        """, (date_q,))
        rows = cur.fetchall()
        out = []
        for r in rows:
            out.append({
                'id':           r['id'],
                'tran_date':    _to_str(r['tran_date']),
                'quality_id':   r['quality_id'],
                'quality_name': r['quality_name'],
                'prod_kgs':     r['prod_kgs'],
            })
        cur.close(); db.close()
        return jsonify({'status': 'success', 'entries': out})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e), 'entries': []}), 500


# -- POST /doff/cont-winding-entry --------------------------------------------
@doff_bp.route('/doff/cont-winding-entry', methods=['POST'])
def save_cont_winding_entry():
    """Insert a continuous-winding row.
    Body: {date, quality_id, prod_kgs, user_id}
    """
    data       = request.get_json(silent=True) or {}
    date_q     = data.get('date')
    quality_id = data.get('quality_id')
    prod_kgs   = data.get('prod_kgs')
    user_id    = data.get('user_id') or 0
    if not (date_q and quality_id):
        return jsonify({'status': 'error',
                        'message': 'date and quality_id required'}), 400
    try:
        db  = get_db()
        cur = db.cursor()
        _ensure_cont_winding_table(cur)
        cur.execute("""
            INSERT INTO tbl_cont_widning_entry
                (tran_date, quality_id, prod_kgs, updated_by)
            VALUES (%s, %s, %s, %s)
        """, (date_q, quality_id, prod_kgs, user_id))
        new_id = cur.lastrowid
        db.commit()
        cur.close(); db.close()
        return jsonify({'status': 'success', 'message': 'Saved', 'id': new_id})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- DELETE /doff/cont-winding-entry/<id> -------------------------------------
@doff_bp.route('/doff/cont-winding-entry/<int:rec_id>', methods=['DELETE'])
def delete_cont_winding_entry(rec_id):
    """Hard-delete a continuous-winding row (table has no active flag)."""
    try:
        db  = get_db()
        cur = db.cursor()
        _ensure_cont_winding_table(cur)
        cur.execute("DELETE FROM tbl_cont_widning_entry WHERE cont_winding_ent_id = %s", (rec_id,))
        db.commit()
        cur.close(); db.close()
        return jsonify({'status': 'success', 'message': 'Deleted'})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- GET /doff/winding-entries ------------------------------------------------
@doff_bp.route('/doff/winding-entries', methods=['GET'])
def list_winding_entries():
    """List W-type rows for a date+spell+branch.
    If no rows found for the given date, fall back to the most-recent date
    that has rows (return those rows + flag 'is_fallback': true).
    """
    date_q    = request.args.get('date')
    spell_id  = request.args.get('spell_id',  type=int)
    branch_id = request.args.get('branch_id', type=int)
    if not (date_q and spell_id and branch_id):
        return jsonify({'status': 'error',
                        'message': 'date, spell_id and branch_id required'}), 400
    try:
        db  = get_db()
        cur = db.cursor(dictionary=True)

        def _fetch(d):
            cur.execute("""
                SELECT w.daily_doff_frm_wdg_id AS id,
                       w.tran_date,
                       w.mc_eb_id              AS eb_id,
                       w.quality_id,
                       q.wng_quality           AS quality_name,
                       CONCAT(COALESCE(p.first_name,''),' ',
                              COALESCE(p.middle_name,''),' ',
                              COALESCE(p.last_name,''))  AS emp_name,
                       o.emp_code
                FROM daily_doff_frames_winding w
                LEFT JOIN winding_quality_master      q ON q.wng_quality_mst_id = w.quality_id
                LEFT JOIN hrms_ed_personal_details    p ON p.eb_id = w.mc_eb_id
                LEFT JOIN hrms_ed_official_details    o ON o.eb_id = w.mc_eb_id
                WHERE w.tran_date = %s
                  AND w.spell_id  = %s
                  AND w.branch_id = %s
                  AND w.spg_wdg   = 'W'
                  AND (w.active IS NULL OR w.active = 1)
                  and w.eb_id is null
                ORDER BY w.daily_doff_frm_wdg_id
            """, (d, spell_id, branch_id))
            return cur.fetchall()

        rows = _fetch(date_q)
        is_fallback = False
        fallback_date = None

        if not rows:
            cur.execute("""
                SELECT MAX(tran_date) AS last_date
                FROM daily_doff_frames_winding
                WHERE tran_date < %s
                  AND spell_id  = %s
                  AND branch_id = %s
                  AND spg_wdg   = 'W'
                  AND (active IS NULL OR active = 1)
            """, (date_q, spell_id, branch_id))
            r = cur.fetchone()
            if r and r['last_date']:
                fallback_date = _to_str(r['last_date'])
                rows = _fetch(fallback_date)
                is_fallback = True

        out = []
        for r in rows:
            out.append({
                'id':           r['id'],
                'tran_date':    _to_str(r['tran_date']),
                'eb_id':        r['eb_id'],
                'emp_code':     r['emp_code'],
                'emp_name':     (r['emp_name'] or '').strip(),
                'quality_id':   r['quality_id'],
                'quality_name': r['quality_name'],
            })
        cur.close(); db.close()
        return jsonify({
            'status':       'success',
            'entries':      out,
            'is_fallback':  is_fallback,
            'fallback_date': fallback_date,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# -- POST /doff/winding-entry -------------------------------------------------
@doff_bp.route('/doff/winding-entry', methods=['POST'])
def save_winding_entry():
    """Insert a single winding entry row.
    Body: {date, spell_id, branch_id, eb_id, quality_id, user_id}
    """
    data      = request.get_json(silent=True) or {}
    date_q    = data.get('date')
    spell_id  = data.get('spell_id')
    branch_id = data.get('branch_id')
    eb_id     = data.get('eb_id')
    quality_id = data.get('quality_id')
    user_id   = data.get('user_id') or 0
    if not (date_q and spell_id and branch_id and eb_id):
        return jsonify({'status': 'error',
                        'message': 'date, spell_id, branch_id and eb_id required'}), 400
    try:
        db  = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO daily_doff_frames_winding
                (tran_date, spell, spell_id, mc_eb_id, quality_id, spg_wdg, branch_id, active)
            VALUES (%s, %s, %s, %s, %s, 'W', %s, 1)
        """, (date_q, spell_id, spell_id, eb_id, quality_id, branch_id))
        db.commit()
        new_id = cur.lastrowid
        cur.close(); db.close()
        return jsonify({'status': 'success', 'message': 'Saved', 'id': new_id})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- GET /doff/validate-trolly ------------------------------------------------
@doff_bp.route('/doff/validate-trolly', methods=['GET'])
def validate_doff_trolly():
    """Validate a typed trolly number against trolly_mst.

    Accepts ?trolly_no=<value>&branch_id=<id>. Matches against
    trolly_posting_code (numeric) OR trolly_name. Returns trolly_id plus
    trolly + bucket weights for auto-tare.
    """
    try:
        trolly_no = (request.args.get('trolly_no') or '').strip()
        branch_id = request.args.get('branch_id', type=int)
        if not trolly_no:
            return jsonify({'status': 'error', 'message': 'trolly_no required'}), 400

        db = get_db()
        cur = db.cursor(dictionary=True)
        sql = """
            SELECT trolly_id,
                   trolly_name,
                   trolly_posting_code AS trolly_no,
                   trolly_weight,
                   busket_weight AS bucket_weight
            FROM trolly_mst
            WHERE (trolly_posting_code = %s OR trolly_name = %s)
        """
        # Coerce posting code: only pass int if input is digits, else -1 (no match)
        try:
            posting_code_val = int(trolly_no)
        except ValueError:
            posting_code_val = -1
        params = [posting_code_val, trolly_no]
        if branch_id:
            sql += ' AND (branch_id IS NULL OR branch_id = %s)'
            params.append(branch_id)
        sql += ' LIMIT 1'
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        cur.close(); db.close()

        if not row:
            return jsonify({'status': 'error', 'message': 'Trolly not found'}), 404
        return jsonify({
            'status':        'success',
            'trolly_id':     row['trolly_id'],
            'trolly_no':     row['trolly_no'],
            'trolly_name':   row['trolly_name'],
            'trolly_weight': float(row['trolly_weight'] or 0),
            'bucket_weight': float(row['bucket_weight'] or 0),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# -- GET /doff/winding-eb-lookup ----------------------------------------------
@doff_bp.route('/doff/winding-eb-lookup', methods=['GET'])
def winding_eb_lookup():
    """Validate an EB number and return the employee's name.
    ?eb_no=<number>&branch_id=<id>
    """
    eb_no     = request.args.get('eb_no', type=int)
    branch_id = request.args.get('branch_id', type=int)
    if not eb_no:
        return jsonify({'status': 'error', 'message': 'eb_no required'}), 400
    try:
        db  = get_db()
        cur = db.cursor(dictionary=True)
        sql = """
            SELECT p.eb_id,
                   o.emp_code,
                   CONCAT(COALESCE(p.first_name,''), ' ',
                          COALESCE(p.middle_name,''), ' ',
                          COALESCE(p.last_name,''))  AS emp_name
            FROM hrms_ed_personal_details  p
            JOIN hrms_ed_official_details  o ON o.eb_id = p.eb_id
            WHERE o.emp_code = %s
              AND (o.active IS NULL OR o.active = 1)
        """
        print('winding_eb_lookup SQL:', sql, 'params:', eb_no, branch_id)
        params = [eb_no]
        if branch_id:
            sql += " AND o.branch_id = %s"
            params.append(branch_id)
        sql += " LIMIT 1"
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        cur.close(); db.close()
        if not row:
            return jsonify({'status': 'error', 'message': 'Employee not found'}), 404
        return jsonify({
            'status':   'success',
            'eb_id':    row['eb_id'],
            'emp_code': row['emp_code'],
            'emp_name': (row['emp_name'] or '').strip(),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- GET /doff/validate-machine -----------------------------------------------
@doff_bp.route('/doff/validate-machine', methods=['GET'])
def validate_doff_machine():
    """Validate a typed machine number/code against machine_mst.

    Accepts ?mc_no=<number-or-code>&branch_id=<id>. Looks up by mech_code
    (preferred) or machine_name. Also returns the trolly whose
    trolly_posting_code = machine.mech_posting_code (same branch when
    given) so the client can pre-fill the trolly input.
    """
    try:
        mc_no = (request.args.get('mc_no') or '').strip()
        branch_id = request.args.get('branch_id', type=int)
        if not mc_no:
            return jsonify({'status': 'error', 'message': 'mc_no required'}), 400

        db = get_db()
        cur = db.cursor(dictionary=True)
        if branch_id:
            sql = """
                SELECT m.machine_id        AS mc_id,
                       m.mech_code         AS mc_no,
                       m.machine_name      AS mc_name,
                       m.mech_code         AS mc_code,
                       m.mech_posting_code AS mech_posting_code,
                       t.trolly_id            AS trolly_id,
                       t.trolly_name          AS trolly_name,
                       t.trolly_posting_code  AS trolly_posting_code,
                       t.trolly_weight        AS trolly_weight,
                       t.busket_weight        AS bucket_weight
                FROM machine_mst m
                INNER JOIN dept_mst dm ON dm.dept_id = m.dept_id
                LEFT JOIN trolly_mst t
                       ON t.trolly_posting_code = m.mech_posting_code
                      AND (t.branch_id IS NULL OR t.branch_id = %s)
                WHERE (m.active IS NULL OR m.active = 1)
                  AND dm.branch_id = %s
                  AND (m.trolly_posting_code = %s OR m.machine_name = %s)
                LIMIT 1
            """
            params = (branch_id, branch_id, mc_no, mc_no)
        else:
            sql = """
                SELECT m.machine_id        AS mc_id,
                       m.mech_code         AS mc_no,
                       m.machine_name      AS mc_name,
                       m.mech_code         AS mc_code,
                       m.mech_posting_code AS mech_posting_code,
                       t.trolly_id            AS trolly_id,
                       t.trolly_name          AS trolly_name,
                       t.trolly_posting_code  AS trolly_posting_code,
                       t.trolly_weight        AS trolly_weight,
                       t.busket_weight        AS bucket_weight
                FROM machine_mst m
                LEFT JOIN trolly_mst t
                       ON t.trolly_posting_code = m.mech_posting_code
                WHERE (m.active IS NULL OR m.active = 1)
                  AND (m.mech_code = %s OR m.machine_name = %s)
                LIMIT 1
            """
            params = (mc_no, mc_no)
        cur.execute(sql, params)
        row = cur.fetchone()
        cur.close(); db.close()

        if not row:
            return jsonify({'status': 'error', 'message': 'Machine not found'}), 404

        for k in ('trolly_weight', 'bucket_weight'):
            v = row.get(k)
            if v is not None:
                try: row[k] = float(v)
                except Exception: pass

        return jsonify({
            'status':              'success',
            'mc_id':               row.get('mc_id'),
            'mc_no':               row.get('mc_no'),
            'mc_name':             row.get('mc_name'),
            'mc_code':             row.get('mc_code'),
            'mech_posting_code':   row.get('mech_posting_code'),
            'trolly_id':           row.get('trolly_id'),
            'trolly_name':         row.get('trolly_name'),
            'trolly_posting_code': row.get('trolly_posting_code'),
            'trolly_weight':       row.get('trolly_weight'),
            'bucket_weight':       row.get('bucket_weight'),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- GET /doff/summary --------------------------------------------------------
@doff_bp.route('/doff/summary', methods=['GET'])
def get_doff_summary():
    """Return per-machine count + total net weight from daily_doff_tbl.

    Filters: ?date=YYYY-MM-DD (required), spell_id (optional),
    branch_id (optional), mc_id (optional, restricts to one machine).
    """
    try:
        d         = request.args.get('date')
        spell_id  = request.args.get('spell_id',  type=int)
        branch_id = request.args.get('branch_id', type=int)
        mc_id     = request.args.get('mc_id',     type=int)
        if not d:
            return jsonify({'status': 'error', 'message': 'date required'}), 400

        db = get_db()
        cur = db.cursor(dictionary=True)
        sql = """
            SELECT d.mc_id,
                   m.mech_code    AS mc_no,
                   m.machine_name AS mc_name,
                   COUNT(*)                       AS no_of_doff,
                   COALESCE(SUM(d.net_weight), 0) AS total_wt
            FROM daily_doff_tbl d
            LEFT JOIN machine_mst m ON m.machine_id = d.mc_id
            WHERE (d.active IS NULL OR d.active = 1)
              AND d.doff_date = %s
        """
        params = [d]
        if spell_id:
            sql += ' AND d.spell = %s'
            params.append(spell_id)
        if branch_id:
            sql += ' AND d.branch_id = %s'
            params.append(branch_id)
        if mc_id:
            sql += ' AND d.mc_id = %s'
            params.append(mc_id)
        sql += ' GROUP BY d.mc_id, m.mech_code, m.machine_name ORDER BY m.mech_code'

        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        cur.close(); db.close()

        out = []
        for r in rows:
            out.append({
                'mc_id':      r['mc_id'],
                'mc_no':      r['mc_no'],
                'mc_name':    r['mc_name'],
                'no_of_doff': int(r['no_of_doff'] or 0),
                'total_wt':   float(r['total_wt'] or 0),
            })
        return jsonify({'status': 'success', 'summary': out})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- GET /doff/frame-machine-defaults -----------------------------------------
@doff_bp.route('/doff/frame-machine-defaults', methods=['GET'])
def get_frame_machine_defaults():
    """Return last-used quality_id per frame machine for a branch.

    Looks at the most recent row in daily_doff_frames_winding for each
    mc_eb_id (regardless of date / spell) where quality_id is not null.
    Falls back to the latest daily_doff_tbl row when no frame entry exists.
    Response: {status, defaults: [{mc_id, quality_id}]}
    """
    try:
        branch_id = request.args.get('branch_id', type=int)
        if not branch_id:
            return jsonify({'status': 'error', 'message': 'branch_id required'}), 400

        _ensure_frame_schema()
        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT f.mc_eb_id   AS mc_id,
                   f.quality_id AS quality_id
            FROM daily_doff_frames_winding f
            INNER JOIN (
                SELECT mc_eb_id, MAX(daily_doff_frm_wdg_id) AS max_id
                FROM daily_doff_frames_winding
                WHERE branch_id = %s
                  AND quality_id IS NOT NULL
                  AND (spg_wdg IS NULL OR spg_wdg = 'S')
                GROUP BY mc_eb_id
            ) lf ON lf.mc_eb_id = f.mc_eb_id
               AND lf.max_id   = f.daily_doff_frm_wdg_id
        """, (branch_id,))
        defaults = {row['mc_id']: row['quality_id'] for row in cur.fetchall()
                    if row.get('quality_id') is not None}

        cur.execute("""
            SELECT d.mc_id      AS mc_id,
                   d.quality_id AS quality_id
            FROM daily_doff_tbl d
            INNER JOIN (
                SELECT mc_id, MAX(daily_doff_tbl_id) AS max_id
                FROM daily_doff_tbl
                WHERE branch_id = %s
                  AND quality_id IS NOT NULL
                  AND (active IS NULL OR active = 1)
                GROUP BY mc_id
            ) ld ON ld.mc_id  = d.mc_id
               AND ld.max_id = d.daily_doff_tbl_id
        """, (branch_id,))
        for row in cur.fetchall():
            qid = row.get('quality_id')
            mc  = row.get('mc_id')
            if mc is not None and qid is not None and mc not in defaults:
                defaults[mc] = qid

        cur.close(); db.close()
        return jsonify({
            'status': 'success',
            'defaults': [{'mc_id': mc, 'quality_id': qid}
                         for mc, qid in defaults.items()],
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- GET /doff/winding-frame-machines -----------------------------------------
@doff_bp.route('/doff/winding-frame-machines', methods=['GET'])
def get_winding_frame_machines():
    """List winding-frame machines (machine_type_id = 37) for a branch."""
    try:
        branch_id = request.args.get('branch_id', type=int)
        if not branch_id:
            return jsonify({'status': 'error', 'message': 'branch_id required'}), 400
        db = get_db()
        cur = db.cursor(dictionary=True)
        sql = """
            SELECT mm.machine_id   AS mc_id,
                   mm.machine_name AS mc_name,
                   mm.mech_code    AS mc_code
            FROM machine_mst mm
            LEFT JOIN dept_mst dm ON dm.dept_id = mm.dept_id
            WHERE dm.branch_id = %s
              AND mm.machine_type_id = 37
              AND (mm.active IS NULL OR mm.active = 1)
            ORDER BY mm.machine_id DESC
        """
        cur.execute(sql, (branch_id,))
        rows = cur.fetchall()
        cur.close(); db.close()
        return jsonify({'status': 'success', 'machines': rows})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- GET /doff/winding-frame-entries ------------------------------------------
@doff_bp.route('/doff/winding-frame-entries', methods=['GET'])
def get_winding_frame_entries():
    """Return active winding frame mc_ids for a (date, spell, branch).
    spg_wdg = 'W' (winding) for this screen.
    """
    try:
        d         = request.args.get('date')
        spell_id  = request.args.get('spell_id',  type=int)
        branch_id = request.args.get('branch_id', type=int)
        if not (d and spell_id and branch_id):
            return jsonify({'status': 'error',
                            'message': 'date, spell_id and branch_id are required'}), 400
        _ensure_frame_schema()
        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT daily_doff_frm_wdg_id AS id,
                   mc_eb_id              AS mc_id,
                   quality_id            AS quality_id
            FROM daily_doff_frames_winding
            WHERE tran_date = %s
              AND spell     = %s
              AND branch_id = %s
              AND spg_wdg   = 'W'
              AND (active IS NULL OR active = 1)
        """, (d, spell_id, branch_id))
        rows = cur.fetchall()
        cur.close(); db.close()
        return jsonify({
            'status': 'success',
            'mc_ids': [r['mc_id'] for r in rows],
            'entries': [
                {'mc_id': r['mc_id'], 'quality_id': r.get('quality_id')}
                for r in rows
            ],
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- POST /doff/winding-frame-entries -----------------------------------------
@doff_bp.route('/doff/winding-frame-entries', methods=['POST'])
def save_winding_frame_entries():
    """Bulk save: replace existing winding frame rows for (date, spell, branch).
    Body (preferred): {date, spell_id, branch_id, user_id,
                       entries: [{mc_id, quality_id}, ...]}
    Legacy:           {date, spell_id, branch_id, user_id, mc_ids: [int, ...]}
    """
    try:
        data = request.get_json(silent=True) or {}
        d         = data.get('date')
        spell_id  = data.get('spell_id')
        branch_id = data.get('branch_id')
        user_id   = data.get('user_id') or 0
        entries   = data.get('entries')
        mc_ids    = data.get('mc_ids') or []
        if not (d and spell_id and branch_id):
            return jsonify({'status': 'error',
                            'message': 'date, spell_id and branch_id are required'}), 400
        pairs = []
        if isinstance(entries, list):
            for e in entries:
                if not isinstance(e, dict):
                    continue
                mc = e.get('mc_id')
                if mc is None:
                    continue
                try:
                    pairs.append((int(mc), int(e['quality_id'])
                                  if e.get('quality_id') is not None else None))
                except (TypeError, ValueError):
                    pass
        elif isinstance(mc_ids, list):
            for mc in mc_ids:
                try:
                    pairs.append((int(mc), None))
                except (TypeError, ValueError):
                    pass
        else:
            return jsonify({'status': 'error',
                            'message': 'entries must be an array'}), 400
        _ensure_frame_schema()
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            DELETE FROM daily_doff_frames_winding
            WHERE tran_date = %s
              AND spell     = %s
              AND branch_id = %s
              AND spg_wdg   = 'W'
        """, (d, spell_id, branch_id))
        inserted = 0
        if pairs:
            ins = """
                INSERT INTO daily_doff_frames_winding
                    (tran_date, spell, mc_eb_id, quality_id, spg_wdg, branch_id, active)
                VALUES (%s, %s, %s, %s, 'W', %s, 1)
            """
            for mc, qid in pairs:
                try:
                    cur.execute(ins, (d, spell_id, mc, qid, branch_id))
                    inserted += 1
                except Exception as ex:
                    print('winding frame insert err for mc', mc, ex)
        db.commit()
        cur.close(); db.close()
        return jsonify({
            'status':  'success',
            'message': f'Saved {inserted} winding frame(s)',
            'count':   inserted,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- GET /doff/winding-frame-machine-defaults ---------------------------------
@doff_bp.route('/doff/winding-frame-machine-defaults', methods=['GET'])
def get_winding_frame_machine_defaults():
    """Return last-used quality_id per winding frame machine for a branch."""
    try:
        branch_id = request.args.get('branch_id', type=int)
        if not branch_id:
            return jsonify({'status': 'error', 'message': 'branch_id required'}), 400
        _ensure_frame_schema()
        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT f.mc_eb_id   AS mc_id,
                   f.quality_id AS quality_id
            FROM daily_doff_frames_winding f
            INNER JOIN (
                SELECT mc_eb_id, MAX(daily_doff_frm_wdg_id) AS max_id
                FROM daily_doff_frames_winding
                WHERE branch_id = %s
                  AND quality_id IS NOT NULL
                  AND spg_wdg = 'W'
                GROUP BY mc_eb_id
            ) lf ON lf.mc_eb_id = f.mc_eb_id
               AND lf.max_id   = f.daily_doff_frm_wdg_id
        """, (branch_id,))
        defaults = {row['mc_id']: row['quality_id'] for row in cur.fetchall()
                    if row.get('quality_id') is not None}
        cur.close(); db.close()
        return jsonify({
            'status': 'success',
            'defaults': [{'mc_id': mc, 'quality_id': qid}
                         for mc, qid in defaults.items()],
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- PUT /doff/winding-entry/<id> ---------------------------------------------
@doff_bp.route('/doff/winding-entry/<int:rec_id>', methods=['PUT'])
def update_winding_entry(rec_id):
    """Update quality_id (and optionally eb_id) for an existing winding row."""
    data       = request.get_json(silent=True) or {}
    quality_id = data.get('quality_id')
    eb_id      = data.get('eb_id')
    if not rec_id:
        return jsonify({'status': 'error', 'message': 'id required'}), 400
    try:
        db  = get_db()
        cur = db.cursor()
        sets, params = [], []
        if quality_id is not None:
            sets.append("quality_id = %s"); params.append(quality_id)
        if eb_id is not None:
            sets.append("mc_eb_id = %s"); params.append(eb_id)
        if not sets:
            return jsonify({'status': 'error', 'message': 'Nothing to update'}), 400
        params.append(rec_id)
        cur.execute(f"UPDATE daily_doff_frames_winding SET {', '.join(sets)} WHERE daily_doff_frm_wdg_id = %s",
                    tuple(params))
        db.commit()
        cur.close(); db.close()
        return jsonify({'status': 'success', 'message': 'Updated'})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- DELETE /doff/winding-entry/<id> ------------------------------------------
@doff_bp.route('/doff/winding-entry/<int:rec_id>', methods=['DELETE'])
def delete_winding_entry(rec_id):
    """Soft-delete (active=0) a single winding entry."""
    try:
        db  = get_db()
        cur = db.cursor()
        cur.execute("""
            UPDATE daily_doff_frames_winding SET active = 0
            WHERE daily_doff_frm_wdg_id = %s AND spg_wdg = 'W'
        """, (rec_id,))
        db.commit()
        cur.close(); db.close()
        return jsonify({'status': 'success', 'message': 'Deleted'})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- GET /doff/winding-entry-2-employees -------------------------------------
@doff_bp.route('/doff/winding-entry-2-employees', methods=['GET'])
def get_winding_entry2_employees():
    """Return distinct employees assigned to winding frames for date+spell+branch.
    Mirrors spg1-mech-codes: reads daily_doff_frames_winding (spg_wdg='W')
    and joins hrms_ed_official_details + hrms_ed_personal_details.
    Query params: date (YYYY-MM-DD), spell_id (int), branch_id (int).
    Returns: [{eb_id, emp_code, emp_name (SUBSTR first_name 1,7)}, ...]
    """
    try:
        d         = request.args.get('date')
        spell_id  = request.args.get('spell_id',  type=int)
        branch_id = request.args.get('branch_id', type=int)
        if not (d and spell_id and branch_id):
            return jsonify({'status': 'error',
                            'message': 'date, spell_id and branch_id are required'}), 400
        db  = get_db()
        cur = db.cursor(dictionary=True)
        sql = """
            SELECT DISTINCT
                   w.mc_eb_id                                AS eb_id,
                   o.emp_code,
                   SUBSTR(COALESCE(p.first_name,''), 1, 7)  AS emp_name
              FROM daily_doff_frames_winding w
              LEFT JOIN hrms_ed_official_details o ON o.eb_id = w.mc_eb_id
              LEFT JOIN hrms_ed_personal_details p ON p.eb_id = w.mc_eb_id
             WHERE w.tran_date = %s
               AND (w.spell = %s OR w.spell_id = %s)
               AND w.branch_id = %s
               AND w.spg_wdg  = 'W'
               AND (w.active IS NULL OR w.active = 1)
             ORDER BY o.emp_code
        """
        params = (d, spell_id, spell_id, branch_id)
        print('GET /doff/winding-entry-2-employees SQL:', sql)
        print('GET /doff/winding-entry-2-employees params:', params)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close(); db.close()
        return jsonify({
            'status':    'success',
            'employees': [
                {
                    'eb_id':    int(r['eb_id']) if r['eb_id'] is not None else None,
                    'emp_code': r['emp_code'] or '',
                    'emp_name': (r['emp_name'] or '').strip(),
                }
                for r in rows if r['eb_id'] is not None
            ]
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -----------------------------------------------------------------------------
# WINDING ENTRY (2) - S/C type + trolly + weight
# -----------------------------------------------------------------------------
_WE2_SCHEMA_OK = False

def _ensure_we2_schema():
    """Add eb_id, sc_type, trolly_id, gross_weight, tare_weight, net_weight,
    user_id columns to daily_doff_frames_winding if missing."""
    global _WE2_SCHEMA_OK
    if _WE2_SCHEMA_OK:
        return
    try:
        db  = get_db()
        cur = db.cursor()
        cur.execute("""
            SELECT COLUMN_NAME FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME   = 'daily_doff_frames_winding'
        """)
        existing = {r[0] for r in cur.fetchall()}
        adds = []
        if 'eb_id'        not in existing: adds.append("ADD COLUMN eb_id INT NULL")
        if 'sc_type'      not in existing: adds.append("ADD COLUMN sc_type CHAR(1) NULL")
        if 'trolly_id'    not in existing: adds.append("ADD COLUMN trolly_id INT NULL")
        if 'gross_weight' not in existing: adds.append("ADD COLUMN gross_weight DECIMAL(12,3) NULL")
        if 'tare_weight'  not in existing: adds.append("ADD COLUMN tare_weight DECIMAL(12,3) NULL")
        if 'net_weight'   not in existing: adds.append("ADD COLUMN net_weight DECIMAL(12,3) NULL")
        if 'user_id'      not in existing: adds.append("ADD COLUMN user_id INT NULL")
        if 'created_at'   not in existing: adds.append("ADD COLUMN created_at DATETIME NULL")
        if adds:
            cur.execute("ALTER TABLE daily_doff_frames_winding " + ", ".join(adds))
            db.commit()
        cur.close(); db.close()
        _WE2_SCHEMA_OK = True
    except Exception as ex:
        print('we2 schema ensure failed:', ex)


# -- GET /doff/winding-entry-2-emp-lookup -------------------------------------
@doff_bp.route('/doff/winding-entry-2-emp-lookup', methods=['GET'])
def winding_entry2_emp_lookup():
    """Lookup an employee by emp_code; return SUBSTR(first_name,1,6).
    ?emp_code=<code>&branch_id=<id>
    """
    emp_code  = request.args.get('emp_code')
    branch_id = request.args.get('branch_id', type=int)
    if not emp_code:
        return jsonify({'status': 'error', 'message': 'emp_code required'}), 400
    try:
        db  = get_db()
        cur = db.cursor(dictionary=True)
        sql = """
            SELECT  o.eb_id,
                    o.emp_code,
                    SUBSTR(COALESCE(p.first_name,''), 1, 6) AS emp_name
              FROM hrms_ed_official_details o
              LEFT JOIN hrms_ed_personal_details p ON p.eb_id = o.eb_id
             WHERE o.emp_code = %s
               AND (o.active IS NULL OR o.active = 1)
        """
        params = [emp_code]
        if branch_id:
            sql += " AND o.branch_id = %s"
            params.append(branch_id)
        sql += " LIMIT 1"
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        cur.close(); db.close()
        if not row:
            return jsonify({'status': 'error', 'message': 'Employee not found'}), 404
        return jsonify({
            'status':   'success',
            'eb_id':    row['eb_id'],
            'emp_code': row['emp_code'],
            'emp_name': (row['emp_name'] or '').strip(),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- GET /doff/winding-entry-2 ------------------------------------------------
@doff_bp.route('/doff/winding-entry-2', methods=['GET'])
def list_winding_entry2():
    """Summary list for Winding Entry (2).
    ?date=YYYY-MM-DD&spell_id=<id>&branch_id=<id>
    Returns rows where spg_wdg='W' for the given date+spell+branch.
    """
    _ensure_we2_schema()
    d         = request.args.get('date')
    spell_id  = request.args.get('spell_id',  type=int)
    branch_id = request.args.get('branch_id', type=int)
    if not (d and spell_id and branch_id):
        return jsonify({'status': 'error',
                        'message': 'date, spell_id and branch_id required'}), 400
    try:
        db  = get_db()
        cur = db.cursor(dictionary=True)
        sql = """
            SELECT  w.daily_doff_frm_wdg_id      AS id,
                    w.eb_id,
                    o.emp_code,
                    SUBSTR(COALESCE(p.first_name,''), 1, 6) AS emp_name,
                    w.sc_type,
                    w.trolly_id,
                    t.trolly_name,
                    w.gross_weight,
                    w.tare_weight,
                    w.net_weight
              FROM daily_doff_frames_winding w
              LEFT JOIN hrms_ed_official_details o ON o.eb_id = w.eb_id
              LEFT JOIN hrms_ed_personal_details p ON p.eb_id = w.eb_id
              LEFT JOIN trolly_mst              t ON t.trolly_id = w.trolly_id
             WHERE w.tran_date = %s
               AND (w.spell_id = %s OR w.spell = %s)
               AND w.branch_id = %s
               AND w.spg_wdg   = 'W'
               AND w.net_weight IS NOT NULL
               AND (w.active IS NULL OR w.active = 1)
             ORDER BY w.daily_doff_frm_wdg_id DESC
        """
        params = (d, spell_id, spell_id, branch_id)
        print('GET /doff/winding-entry-2 SQL:', sql)
        print('GET /doff/winding-entry-2 params:', params)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close(); db.close()
        out = []
        for r in rows:
            out.append({
                'id':           r['id'],
                'eb_id':        r['eb_id'],
                'emp_code':     r['emp_code'],
                'emp_name':     (r['emp_name'] or '').strip(),
                'sc_type':      r['sc_type'],
                'trolly_id':    r['trolly_id'],
                'trolly_name':  r['trolly_name'],
                'gross_weight': float(r['gross_weight']) if r['gross_weight'] is not None else None,
                'tare_weight':  float(r['tare_weight'])  if r['tare_weight']  is not None else None,
                'net_weight':   float(r['net_weight'])   if r['net_weight']   is not None else None,
            })
        return jsonify({'status': 'success', 'summary': out})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- POST /doff/winding-entry-2 -----------------------------------------------
@doff_bp.route('/doff/winding-entry-2', methods=['POST'])
def save_winding_entry2():
    """Save a Winding Entry (2) row.
    Body: {date, spell_id, branch_id, eb_id, sc_type, trolly_id?,
           gross_weight, tare_weight, net_weight, user_id}
    """
    _ensure_we2_schema()
    data       = request.get_json(silent=True) or {}
    d          = data.get('date')
    spell_id   = data.get('spell_id')
    branch_id  = data.get('branch_id')
    eb_id      = data.get('eb_id')
    sc_type    = (data.get('sc_type') or '').upper()
    trolly_id  = data.get('trolly_id')
    gross_wt   = float(data.get('gross_weight') or 0)
    tare_wt    = float(data.get('tare_weight')  or 0)
    net_wt     = data.get('net_weight')
    if net_wt is None:
        net_wt = gross_wt - tare_wt
    net_wt     = float(net_wt)
    user_id    = data.get('user_id') or 0

    if not (d and spell_id and branch_id and eb_id):
        return jsonify({'status': 'error',
                        'message': 'date, spell_id, branch_id and eb_id required'}), 400
    if sc_type not in ('S', 'C'):
        return jsonify({'status': 'error', 'message': 'sc_type must be S or C'}), 400
    if sc_type == 'S' and not trolly_id:
        return jsonify({'status': 'error', 'message': 'trolly_id required when sc_type=S'}), 400
    if net_wt <= 0:
        return jsonify({'status': 'error', 'message': 'Net weight must be positive'}), 400
    try:
        db  = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO daily_doff_frames_winding
                (tran_date, spell, spell_id, mc_eb_id, eb_id, sc_type,
                 trolly_id, gross_weight, tare_weight, net_weight,
                 spg_wdg, branch_id, active, user_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'W', %s, 1, %s, NOW())
        """, (d, spell_id, spell_id, eb_id, eb_id, sc_type,
              trolly_id, gross_wt, tare_wt, net_wt,
              branch_id, user_id))
        db.commit()
        new_id = cur.lastrowid
        cur.close(); db.close()
        return jsonify({'status': 'success', 'message': 'Saved', 'id': new_id})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- DELETE /doff/winding-entry-2/<id> ----------------------------------------
@doff_bp.route('/doff/winding-entry-2/<int:rec_id>', methods=['DELETE'])
def delete_winding_entry2(rec_id):
    try:
        db  = get_db()
        cur = db.cursor()
        cur.execute("""
            UPDATE daily_doff_frames_winding SET active = 0
            WHERE daily_doff_frm_wdg_id = %s AND spg_wdg = 'W'
        """, (rec_id,))
        db.commit()
        cur.close(); db.close()
        return jsonify({'status': 'success', 'message': 'Deleted'})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- GET /doff/winding-entry-2-summary ----------------------------------------
@doff_bp.route('/doff/winding-entry-2-summary', methods=['GET'])
def winding_entry2_summary():
    """Grouped summary for Winding Entry (2) - grouped by employee.
    ?date=YYYY-MM-DD&spell_id=<id>&branch_id=<id>
    Returns: [{eb_id, emp_code, emp_name, weights:[], no_of_doff, total_wt}]
    """
    _ensure_we2_schema()
    d         = request.args.get('date')
    spell_id  = request.args.get('spell_id',  type=int)
    branch_id = request.args.get('branch_id', type=int)
    if not (d and spell_id and branch_id):
        return jsonify({'status': 'error',
                        'message': 'date, spell_id and branch_id required'}), 400
    try:
        db  = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT  w.eb_id,
                    o.emp_code,
                    SUBSTR(COALESCE(p.first_name,''), 1, 7) AS emp_name,
                    w.net_weight,
                    w.daily_doff_frm_wdg_id AS id
              FROM daily_doff_frames_winding w
              LEFT JOIN hrms_ed_official_details o ON o.eb_id = w.eb_id
              LEFT JOIN hrms_ed_personal_details p ON p.eb_id = w.eb_id
             WHERE w.tran_date = %s
               AND (w.spell_id = %s OR w.spell = %s)
               AND w.branch_id = %s
               AND w.spg_wdg   = 'W'
               AND w.net_weight IS NOT NULL
               AND (w.active IS NULL OR w.active = 1)
             ORDER BY w.eb_id, w.daily_doff_frm_wdg_id
        """, (d, spell_id, spell_id, branch_id))
        rows = cur.fetchall()
        cur.close(); db.close()
        from collections import OrderedDict
        grouped = OrderedDict()
        for r in rows:
            key = r['eb_id']
            if key not in grouped:
                grouped[key] = {
                    'eb_id':      int(key) if key is not None else None,
                    'emp_code':   r['emp_code'] or '',
                    'emp_name':   (r['emp_name'] or '').strip(),
                    'weights':    [],
                    'no_of_doff': 0,
                    'total_wt':   0.0,
                }
            wt = float(r['net_weight'] or 0)
            grouped[key]['weights'].append(wt)
            grouped[key]['no_of_doff'] += 1
            grouped[key]['total_wt']   += wt
        summary = list(grouped.values())
        for s in summary:
            s['total_wt'] = round(s['total_wt'], 3)
        return jsonify({'status': 'success', 'summary': summary})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- GET /doff/winding-entry-2-detail -----------------------------------------
@doff_bp.route('/doff/winding-entry-2-detail', methods=['GET'])
def winding_entry2_detail():
    """Individual rows for one employee for Winding Entry (2).
    ?date=YYYY-MM-DD&spell_id=<id>&branch_id=<id>&eb_id=<id>
    """
    _ensure_we2_schema()
    d         = request.args.get('date')
    spell_id  = request.args.get('spell_id',  type=int)
    branch_id = request.args.get('branch_id', type=int)
    eb_id     = request.args.get('eb_id',     type=int)
    if not (d and spell_id and branch_id and eb_id):
        return jsonify({'status': 'error',
                        'message': 'date, spell_id, branch_id and eb_id required'}), 400
    try:
        db  = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT  w.daily_doff_frm_wdg_id AS id,
                    w.eb_id,
                    o.emp_code,
                    SUBSTR(COALESCE(p.first_name,''), 1, 7) AS emp_name,
                    w.sc_type,
                    w.trolly_id,
                    t.trolly_name,
                    w.gross_weight,
                    w.tare_weight,
                    w.net_weight
              FROM daily_doff_frames_winding w
              LEFT JOIN hrms_ed_official_details o ON o.eb_id = w.eb_id
              LEFT JOIN hrms_ed_personal_details p ON p.eb_id = w.eb_id
              LEFT JOIN trolly_mst              t ON t.trolly_id = w.trolly_id
             WHERE w.tran_date = %s
               AND (w.spell_id = %s OR w.spell = %s)
               AND w.branch_id = %s
               AND w.eb_id     = %s
               AND w.spg_wdg   = 'W'
               AND w.net_weight IS NOT NULL
               AND (w.active IS NULL OR w.active = 1)
             ORDER BY w.daily_doff_frm_wdg_id
        """, (d, spell_id, spell_id, branch_id, eb_id))
        rows = cur.fetchall()
        cur.close(); db.close()
        out = []
        for r in rows:
            out.append({
                'id':           r['id'],
                'eb_id':        r['eb_id'],
                'emp_code':     r['emp_code'],
                'emp_name':     (r['emp_name'] or '').strip(),
                'sc_type':      r['sc_type'],
                'trolly_id':    r['trolly_id'],
                'trolly_name':  r['trolly_name'],
                'gross_weight': float(r['gross_weight']) if r['gross_weight'] is not None else None,
                'tare_weight':  float(r['tare_weight'])  if r['tare_weight']  is not None else None,
                'net_weight':   float(r['net_weight'])   if r['net_weight']   is not None else None,
            })
        return jsonify({'status': 'success', 'summary': out})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# SPG DOFF ENTRY 1 - QUALITY-WISE SHIFT-WISE REPORT
@doff_bp.route('/doff/spg1-quality-shift-report', methods=['GET'])
def get_spg1_quality_shift_report():
    try:
        date_str = request.args.get('date')
        branch_id = request.args.get('branch_id', type=int)
        if not date_str:
            return jsonify({'status': 'error', 'message': 'date is required'}), 400
        if not branch_id:
            return jsonify({'status': 'error', 'message': 'branch_id is required'}), 400
        db = get_db()
        cursor = db.cursor(dictionary=True)
        sql="""        SELECT
                COALESCE(concat(spg_type_name,' ',q.spg_quality,' ',q.speed,' RPM') , 'Unknown') AS quality_name,
                COALESCE(SUM(CASE WHEN s.spell_name LIKE '%A%' THEN d.net_weight ELSE 0 END), 0) AS shift_a,
                COALESCE(SUM(CASE WHEN s.spell_name LIKE '%B%' THEN d.net_weight ELSE 0 END), 0) AS shift_b,
                COALESCE(SUM(CASE WHEN s.spell_name LIKE '%C%' THEN d.net_weight ELSE 0 END), 0) AS shift_c,
                COALESCE(SUM(d.net_weight), 0) AS total
            FROM daily_doff_tbl d
            LEFT JOIN spell_mst s ON d.spell = s.spell_id
			left join daily_doff_frames_winding ddfw on ddfw.tran_date =d.doff_date and ddfw.spell =d.spell 
			and ddfw.mc_eb_id =d.mc_id and ddfw.active =1 and spg_wdg='S'
            LEFT JOIN spinning_quality_mst q ON ddfw.quality_id = q.spg_quality_mst_id 
            left join spinning_type_mst stm on stm.spg_type_mst_id =q.spg_type_id 
            WHERE d.doff_date = %s AND d.branch_id = %s
              AND (d.active IS NULL OR d.active = 1)
            GROUP BY concat(spg_type_name,' ',q.spg_quality,' ',q.speed) ORDER BY concat(spg_type_name,' ',q.spg_quality,' ',q.speed)
        """
        query = sql
        cursor.execute(query, (date_str, branch_id))
        report_rows = cursor.fetchall()
        grand_total_a = sum(row['shift_a'] for row in report_rows)
        grand_total_b = sum(row['shift_b'] for row in report_rows)
        grand_total_c = sum(row['shift_c'] for row in report_rows)
        grand_total = sum(row['total'] for row in report_rows)
        cursor.close()
        db.close()
        return jsonify({
            'status': 'success',
            'message': 'Quality-wise shift-wise report generated',
            'report': report_rows,
            'grand_total': {'shift_a': grand_total_a, 'shift_b': grand_total_b, 'shift_c': grand_total_c, 'total': grand_total}
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Spg Running Hours — table: tbl_daily_vvfd_transaction
#   machines: machine_mst where machine_type_id = 36 and branch_id matches
# ─────────────────────────────────────────────────────────────────────────────

@doff_bp.route('/doff/spg-running-machines', methods=['GET'])
def get_spg_running_machines():
    """
    Machines for Spg Running Hours screen.
    Source: machine_mst, filtered by branch_id and machine_type_id = 36.
    Query params: ?branch_id=<id> (required)
    Returns: { status, machines: [ { mc_id, mc_name, mc_code } ] }
    """
    try:
        branch_id = request.args.get('branch_id', type=int)
        if not branch_id:
            return jsonify({'status': 'error', 'message': 'branch_id is required'}), 400

        db = get_db()
        cur = db.cursor(dictionary=True)
        sql="""
            SELECT machine_id    AS mc_id,
                   machine_name  AS mc_name,
                   mech_code     AS mc_code
            FROM machine_mst
            WHERE branch_id       = %s
              AND machine_type_id = 36
              AND (active IS NULL OR active = 1)
            ORDER BY machine_name
        """
        cur.execute(sql, (branch_id,))
        rows = cur.fetchall()
        cur.close(); db.close()
        return jsonify({'status': 'success', 'machines': rows, 'total': len(rows)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@doff_bp.route('/doff/spg-running-hours', methods=['POST'])
def save_spg_running_hours():
    """
    Save a Spg Running Hours row into tbl_daily_vvfd_transaction.
    Body JSON: { date, spell_id, branch_id, mc_id, mc_runs_time,
                 kw_consumption (optional), user_id }
    """
    try:
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        tran_date      = data.get('date')
        spell_id       = data.get('spell_id')
        branch_id      = data.get('branch_id')
        mc_id          = data.get('mc_id')
        mc_runs_time   = data.get('mc_runs_time')
        kw_consumption = data.get('kw_consumption')
        user_id        = data.get('user_id')

        missing = [k for k, v in {
            'date': tran_date, 'spell_id': spell_id, 'branch_id': branch_id,
            'mc_id': mc_id, 'mc_runs_time': mc_runs_time,
        }.items() if v in (None, '', 0, '0')]
        if missing:
            return jsonify({'status': 'error',
                            'message': f'missing/empty: {", ".join(missing)}',
                            'received': data}), 400
        try:
            mc_runs_time = float(mc_runs_time)
        except Exception:
            return jsonify({'status': 'error', 'message': 'mc_runs_time must be numeric'}), 400
        try:
            kw_consumption = float(kw_consumption) if kw_consumption not in (None, '') else None
        except Exception:
            return jsonify({'status': 'error', 'message': 'kw_consumption must be numeric'}), 400

        db = get_db()
        chk = db.cursor()
        chk.execute("""
            SELECT tbl_daily_vvfd_id
            FROM tbl_daily_vvfd_transaction
            WHERE tran_date = %s
              AND spell_id  = %s
              AND branch_id = %s
              AND mc_id     = %s
            LIMIT 1
        """, (tran_date, spell_id, branch_id, mc_id))
        dup = chk.fetchone()
        chk.close()
        if dup:
            db.close()
            return jsonify({'status': 'error', 'message': 'Already Entered'})

        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO tbl_daily_vvfd_transaction
                (tran_date, spell_id, branch_id, mc_id,
                 mc_runs_time, kw_consumption, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (tran_date, spell_id, branch_id, mc_id,
              mc_runs_time, kw_consumption, user_id))
        db.commit()
        new_id = cursor.lastrowid
        cursor.close(); db.close()
        return jsonify({'status': 'success', 'message': 'Saved', 'id': new_id})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@doff_bp.route('/doff/spg-running-hours', methods=['GET'])
def list_spg_running_hours():
    """
    List Spg Running Hours entries for date + spell (+ optional branch filter).
    Query params: ?date=YYYY-MM-DD&spell_id=<id>&branch_id=<id>
                  (date and spell_id required; branch_id optional)
    """
    try:
        date_str  = request.args.get('date')
        spell_id  = request.args.get('spell_id', type=int)
        branch_id = request.args.get('branch_id', type=int)
        if not all([date_str, spell_id]):
            return jsonify({'status': 'error',
                            'message': 'date, spell_id are required'}), 400

        sql = """
            SELECT v.tbl_daily_vvfd_id  AS id,
                   v.tran_date,
                   v.spell_id,
                   v.branch_id,
                   v.mc_id,
                   COALESCE(mm.machine_name, mm.mech_code, CONCAT('MC', v.mc_id)) AS mc_name,
                   v.mc_runs_time,
                   v.kw_consumption,
                   v.updated_by,
                   v.updated_date_time
            FROM tbl_daily_vvfd_transaction v
            LEFT JOIN machine_mst mm ON v.mc_id = mm.machine_id
            WHERE v.tran_date = %s
              AND v.spell_id  = %s
        """
        params = [date_str, spell_id]
        if branch_id:
            sql += " AND v.branch_id = %s"
            params.append(branch_id)
        sql += " ORDER BY v.tbl_daily_vvfd_id DESC"

        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        cursor.close(); db.close()
        for r in rows:
            for k in ('mc_runs_time', 'kw_consumption'):
                if r.get(k) is not None:
                    try: r[k] = float(r[k])
                    except Exception: pass
        return jsonify({'status': 'success', 'entries': rows, 'total': len(rows)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@doff_bp.route('/doff/spg-running-hours/<int:entry_id>', methods=['PUT'])
def update_spg_running_hours(entry_id):
    """
    Update an existing Spg Running Hours row.
    Body JSON: { mc_id, branch_id, mc_runs_time, kw_consumption, user_id }
    (any subset).
    """
    try:
        data = request.get_json(silent=True) or {}
        mc_id          = data.get('mc_id')
        branch_id      = data.get('branch_id')
        mc_runs_time   = data.get('mc_runs_time')
        kw_consumption = data.get('kw_consumption')
        user_id        = data.get('user_id')

        try:
            mc_runs_time = float(mc_runs_time) if mc_runs_time is not None else None
        except Exception:
            return jsonify({'status': 'error', 'message': 'mc_runs_time must be numeric'}), 400
        try:
            kw_consumption = float(kw_consumption) if kw_consumption not in (None, '') else None
        except Exception:
            return jsonify({'status': 'error', 'message': 'kw_consumption must be numeric'}), 400

        sets = []
        params = []
        if mc_id        is not None: sets.append("mc_id = %s");          params.append(mc_id)
        if branch_id    is not None: sets.append("branch_id = %s");      params.append(branch_id)
        if mc_runs_time is not None: sets.append("mc_runs_time = %s");   params.append(mc_runs_time)
        if 'kw_consumption' in data: sets.append("kw_consumption = %s"); params.append(kw_consumption)
        if user_id      is not None: sets.append("updated_by = %s");     params.append(user_id)
        if not sets:
            return jsonify({'status': 'error', 'message': 'no fields to update'}), 400
        sets.append("updated_date_time = CURRENT_TIMESTAMP")

        db = get_db()
        # If the update changes the natural key (mc_id / branch_id), guard duplicates.
        if mc_id is not None or branch_id is not None:
            chk = db.cursor(dictionary=True)
            chk.execute("""
                SELECT tran_date, spell_id, branch_id, mc_id
                FROM tbl_daily_vvfd_transaction
                WHERE tbl_daily_vvfd_id = %s
            """, (entry_id,))
            cur_row = chk.fetchone()
            chk.close()
            if cur_row:
                new_mc_id     = mc_id     if mc_id     is not None else cur_row['mc_id']
                new_branch_id = branch_id if branch_id is not None else cur_row['branch_id']
                chk2 = db.cursor()
                chk2.execute("""
                    SELECT tbl_daily_vvfd_id
                    FROM tbl_daily_vvfd_transaction
                    WHERE tran_date         = %s
                      AND spell_id          = %s
                      AND branch_id         = %s
                      AND mc_id             = %s
                      AND tbl_daily_vvfd_id <> %s
                    LIMIT 1
                """, (cur_row['tran_date'], cur_row['spell_id'],
                      new_branch_id, new_mc_id, entry_id))
                dup = chk2.fetchone()
                chk2.close()
                if dup:
                    db.close()
                    return jsonify({'status': 'error', 'message': 'Already Entered'})

        params.append(entry_id)
        cursor = db.cursor()
        cursor.execute(
            f"UPDATE tbl_daily_vvfd_transaction SET {', '.join(sets)} WHERE tbl_daily_vvfd_id = %s",
            tuple(params)
        )
        db.commit()
        rows = cursor.rowcount
        cursor.close(); db.close()
        if rows == 0:
            return jsonify({'status': 'error', 'message': 'entry not found'}), 404
        return jsonify({'status': 'success', 'message': 'Updated', 'id': entry_id})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@doff_bp.route('/doff/spg-running-hours/<int:entry_id>', methods=['DELETE'])
def delete_spg_running_hours(entry_id):
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "DELETE FROM tbl_daily_vvfd_transaction WHERE tbl_daily_vvfd_id = %s",
            (entry_id,)
        )
        db.commit()
        cursor.close(); db.close()
        return jsonify({'status': 'success', 'message': 'Deleted'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

