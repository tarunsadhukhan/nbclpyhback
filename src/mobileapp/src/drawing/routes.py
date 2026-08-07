"""
Drawing Module - API Routes
All endpoint handlers for drawing meter entry functionality

Tables:
  tbl_drawing_mst    (drg_mst_id, mc_id, short_name, shed_type, const_meter,
                      drg_type, branch_id, updated_by, updated_date_time)
  tbl_daily_drawing  (tbl_daily_drg_id, mc_id, tran_date, spell_id,
                      opening_meter, closing_meter, difference, const_meter,
                      running_hours, branch_id, updated_by, updated_date_time)
"""
import traceback
from flask import request, jsonify
from . import drawing_bp
from ..database import get_db
from ..models.drawing import DrawingMst, DailyDrawing


@drawing_bp.route('/sheds', methods=['GET'])
def get_drawing_sheds():
    """
    GET /drawing/sheds
    Query params: ?branch_id=<id> (optional)
    Returns distinct shed_type values from tbl_drawing_mst.
    """
    try:
        branch_id = request.args.get('branch_id', type=int)

        db = get_db()
        cursor = db.cursor(dictionary=True)

        query = "SELECT DISTINCT shed_type FROM tbl_drawing_mst WHERE shed_type IS NOT NULL"
        params = []

        if branch_id:
            query += " AND branch_id = %s"
            params.append(branch_id)

        query += " ORDER BY shed_type"

        cursor.execute(query, params if params else None)
        sheds = cursor.fetchall()
        cursor.close()
        db.close()

        return jsonify({
            'status': 'success',
            'sheds': [s['shed_type'] for s in sheds]
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@drawing_bp.route('/machines', methods=['GET'])
def get_drawing_machines():
    """
    GET /drawing/machines
    Query params:
        ?shed_type=<type>  (required)
        ?branch_id=<id>    (optional)
    Returns: [{drg_mst_id, mc_id, short_name, const_meter}, ...]
    """
    try:
        shed_type = request.args.get('shed_type')
        branch_id = request.args.get('branch_id', type=int)

        if not shed_type:
            return jsonify({'status': 'error', 'message': 'shed_type required'}), 400

        db = get_db()
        cursor = db.cursor(dictionary=True)

        query = """
            SELECT drg_mst_id, mc_id, short_name, const_meter, drg_type
            FROM tbl_drawing_mst
            WHERE shed_type = %s
        """
        params = [shed_type]

        if branch_id:
            query += " AND branch_id = %s"
            params.append(branch_id)

        query += " ORDER BY short_name"

        print("Executing query:", query, "with params:", params)
        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
        db.close()
        print("Fetched machines:", rows)
        machines = [DrawingMst.from_row(r).to_dict() for r in rows]
        print("Transformed machines:", machines)
        return jsonify({'status': 'success', 'machines': machines})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@drawing_bp.route('/opening-meter', methods=['GET'])
def get_drawing_opening_meter():
    """
    GET /drawing/opening-meter
    Query params:
        ?date=YYYY-MM-DD  (required)
        ?spell_id=<id>    (required)
        ?mc_id=<id>       (required)
    Returns the closing_meter from the most recent previous entry for
    the same machine (before the given tran_date+spell_id).
    """
    try:
        date_str = request.args.get('date')
        spell_id = request.args.get('spell_id', type=int)
        mc_id    = request.args.get('mc_id',    type=int)

        if not all([date_str, spell_id, mc_id]):
            return jsonify({'status': 'error',
                            'message': 'date, spell_id and mc_id required'}), 400

        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute("""
            SELECT closing_meter
            FROM tbl_daily_drawing
            WHERE mc_id = %s
              AND (tran_date < %s OR (tran_date = %s AND spell_id = %s))
            ORDER BY tran_date DESC, spell_id DESC
            LIMIT 1
        """, (mc_id, date_str, date_str, spell_id))

        result = cursor.fetchone()
        cursor.close()
        db.close()

        opening_meter = int(result['closing_meter']) if result and result['closing_meter'] is not None else 0
        return jsonify({'status': 'success', 'opening_meter': opening_meter})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@drawing_bp.route('/entry', methods=['POST'])
def save_drawing_entry():
    """
    POST /drawing/entry
    Body (JSON):
    {
        "date":           "YYYY-MM-DD",
        "spell_id":       <int>,
        "mc_id":          <int>,
        "opening_meter":  <int>,
        "closing_meter":  <int>,
        "running_hours":  <float>,
        "branch_id":      <int>,
        "user_id":        <int>   (stored as updated_by)
    }
    Calculates difference = closing_meter - opening_meter.
    Fetches const_meter from tbl_drawing_mst for the mc_id.
    Efficiency (not stored) = round(difference /(const_meter/8*running_hours)*100,2)
    Upserts on (tran_date, spell_id, mc_id).
    """
    #((difference / running_hours * 8) / const_meter * 100).
  
    try:
        data = request.get_json(silent=True) or {}

        date_str      = data.get('date')
        spell_id      = data.get('spell_id')
        mc_id         = data.get('mc_id')
        opening_meter = int(data.get('opening_meter') or 0)
        closing_meter = int(data.get('closing_meter') or 0)
        running_hours = float(data.get('hours') or 0)
        branch_id     = data.get('branch_id')
        updated_by    = data.get('user_id') or 0
        print("Received drawing entry data:", data)
        print("Parsed values - date:", date_str, "spell_id:", spell_id, "mc_id:", mc_id,
              "opening_meter:", opening_meter, "closing_meter:", closing_meter, "running_hours:", running_hours, "branch_id:", branch_id, "updated_by:", updated_by)    
        if not all([date_str, spell_id, mc_id]):
            return jsonify({'status': 'error',
                            'message': 'date, spell_id and mc_id required'}), 400

        difference = closing_meter - opening_meter

        db = get_db()
        cursor = db.cursor(dictionary=True)

        # Fetch const_meter from master
        cursor.execute(
            "SELECT const_meter FROM tbl_drawing_mst WHERE mc_id = %s LIMIT 1",
            (mc_id,)
        )
        mst = cursor.fetchone()
        const_meter = int(mst['const_meter']) if mst and mst['const_meter'] else 0

        # Calculate efficiency (for response only, not stored)
        if running_hours > 0 and const_meter > 0:
            eff =difference /(const_meter/8*running_hours)*100
            eff = round(eff, 2)
            #round(((difference / running_hours * 8) / const_meter * 100), 2)
        else:
            eff = 0.0

        # Upsert
        cursor2 = db.cursor()
        cursor2.execute("""
            SELECT tbl_daily_drg_id
            FROM tbl_daily_drawing
            WHERE tran_date = %s AND spell_id = %s AND mc_id = %s
            LIMIT 1
        """, (date_str, spell_id, mc_id))
        existing = cursor2.fetchone()

        if existing:
            cursor2.execute("""
                UPDATE tbl_daily_drawing
                SET opening_meter = %s, closing_meter = %s, difference = %s,
                    const_meter = %s, running_hours = %s,
                    branch_id = %s, updated_by = %s
                WHERE tbl_daily_drg_id = %s
            """, (opening_meter, closing_meter, difference,
                  const_meter, running_hours,
                  branch_id, updated_by, existing[0]))
            entry_id = existing[0]
            message  = 'Entry updated successfully'
        else:
            cursor2.execute("""
                INSERT INTO tbl_daily_drawing
                    (mc_id, tran_date, spell_id, opening_meter, closing_meter,
                     difference, const_meter, running_hours, branch_id, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (mc_id, date_str, spell_id, opening_meter, closing_meter,
                  difference, const_meter, running_hours, branch_id, updated_by))
            entry_id = cursor2.lastrowid
            message  = 'Entry saved successfully'

        db.commit()
        cursor.close()
        cursor2.close()
        db.close()

        return jsonify({
            'status':     'success',
            'message':    message,
            'id':         entry_id,
            'difference': difference,
            'eff':        eff,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@drawing_bp.route('/summary', methods=['GET'])
def get_drawing_summary():
    """
    GET /drawing/summary
    Query params:
        ?date=YYYY-MM-DD  (required)
        ?spell_id=<id>    (required)
        ?branch_id=<id>   (optional)
    Returns per-machine entries with difference and calculated efficiency.
    """
    try:
        date_str  = request.args.get('date')
        spell_id  = request.args.get('spell_id',  type=int)
        branch_id = request.args.get('branch_id', type=int)

        if not all([date_str, spell_id]):
            return jsonify({'status': 'error',
                            'message': 'date and spell_id required'}), 400

        db = get_db()
        cursor = db.cursor(dictionary=True)

        query = """
            SELECT
                d.tbl_daily_drg_id,
                d.mc_id,
                d.tran_date,
                d.spell_id,
                m.short_name,
                m.shed_type,
                d.opening_meter,
                d.closing_meter,
                d.difference ,
                d.difference as unit,
                d.const_meter,
                d.running_hours
            FROM tbl_daily_drawing d
            JOIN tbl_drawing_mst m ON m.mc_id = d.mc_id
            WHERE d.tran_date = %s AND d.spell_id = %s
        """
        params = [date_str, spell_id]

        if branch_id:
            query += " AND d.branch_id = %s"
            params.append(branch_id)

        query += " ORDER BY d.tbl_daily_drg_id"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
        db.close()
        
        summary = []
        for r in rows:
            entry = DailyDrawing.from_row(r)
            d = entry.to_dict()
            d['short_name'] = r.get('short_name')
            d['shed_type']  = r.get('shed_type')
            summary.append(d)
        print("Drawings summary data:", summary)
        return jsonify({'status': 'success', 'summary': summary})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500




@drawing_bp.route('/spells', methods=['GET'])
def get_drawing_spells():
    """
    GET /drawing/spells
    Query: ?branch_id=<id> (optional)
    Returns: { "status":"success",
               "spells":[{spell_id,spell_name,working_hours}],
               "total":N }
    """
    try:
        branch_id = request.args.get('branch_id', type=int)

        db = get_db()
        cursor = db.cursor(dictionary=True)

        if branch_id:
            cursor.execute("""
                SELECT sm.spell_id,
                       sm.spell_name,
                       COALESCE(sm.working_hours, 8.0) AS working_hours
                FROM spell_mst sm
                JOIN shift_mst sh ON sm.shift_id = sh.shift_id
                WHERE sh.branch_id = %s
                ORDER BY sm.spell_name
            """, (branch_id,))
        else:
            cursor.execute("""
                SELECT sm.spell_id,
                       sm.spell_name,
                       COALESCE(sm.working_hours, 8.0) AS working_hours
                FROM spell_mst sm
                ORDER BY sm.spell_name
            """)

        spells = cursor.fetchall()
        cursor.close()
        db.close()

        # Ensure working_hours is a JSON-serialisable float
        for r in spells:
            if r.get('working_hours') is not None:
                r['working_hours'] = float(r['working_hours'])
            else:
                r['working_hours'] = 8.0

        return jsonify({
            'status': 'success',
            'spells': spells,
            'total':  len(spells),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@drawing_bp.route('/shifts', methods=['GET'])
def get_shifts():
    try:
        branch_id = request.args.get('branch_id', type=int)

        db = get_db()
        cursor = db.cursor(dictionary=True)

        if branch_id:
            cursor.execute("""
                SELECT sm.spell_id AS id, sm.spell_name AS name,
                       sm.starting_time AS start_time, sm.end_time,
                       COALESCE(sm.working_hours, 8.0) AS working_hours
                FROM spell_mst sm
                JOIN shift_mst sh ON sm.shift_id = sh.shift_id
                WHERE sh.branch_id = %s
                ORDER BY sm.spell_name
            """, (branch_id,))
        else:
            cursor.execute("""
                SELECT spell_id AS id, spell_name AS name,
                       starting_time AS start_time, end_time,
                       COALESCE(working_hours, 8.0) AS working_hours
                FROM spell_mst ORDER BY spell_name
            """)

        data = cursor.fetchall()
        cursor.close()
        db.close()
        return jsonify({'status': 'success', 'shifts': data, 'total': len(data)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
