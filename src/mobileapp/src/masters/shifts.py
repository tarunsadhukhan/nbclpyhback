from flask import Blueprint, request, jsonify
import mysql.connector
from src.mobileapp.db import get_db
from src.mobileapp.src.masters import query as Q

shifts_bp = Blueprint('shifts', __name__)


@shifts_bp.route('/shifts', methods=['GET'])
def get_shifts():
    try:
        branch_id = request.args.get('branch_id', type=int)
        
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        if branch_id:
            # Query with branch_id filter using spell_mst and shift_mst
            # ponytail: GROUP BY name — same spell can exist under several shifts;
            # report filters match sibling ids by name so MIN(id) is safe
            cursor.execute("""
                SELECT MIN(sm.spell_id) AS id,
                       sm.spell_name AS name,
                       MIN(sm.starting_time) AS start_time,
                       MIN(sm.end_time) AS end_time,
                       MIN(sm.working_hours) AS shift_hours
                FROM spell_mst sm
                LEFT JOIN shift_mst sm2 ON sm.shift_id = sm2.shift_id
                WHERE sm2.branch_id = %s
                GROUP BY sm.spell_name
                ORDER BY sm.spell_name
            """, (branch_id,))
        else:
            # Query without branch filter
            cursor.execute("""
                SELECT MIN(spell_id) AS id,
                       spell_name AS name,
                       MIN(starting_time) AS start_time,
                       MIN(end_time) AS end_time,
                       MIN(working_hours) AS shift_hours
                FROM spell_mst
                GROUP BY spell_name
                ORDER BY spell_name
            """)
        
        rows = cursor.fetchall()
        
        # Convert time fields to string
        for r in rows:
            if r.get('start_time'):
                r['start_time'] = str(r['start_time'])
            if r.get('end_time'):
                r['end_time'] = str(r['end_time'])
            # Ensure shift_hours is a float
            if r.get('shift_hours') is not None:
                r['shift_hours'] = float(r['shift_hours'])
            else:
                r['shift_hours'] = 0.0
        
        cursor.close()
        db.close()
        return jsonify({"status": "success", "total": len(rows), "data": rows})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@shifts_bp.route('/shifts', methods=['POST'])
def add_shift():
    try:
        data       = request.json
        name       = data.get('name', '').strip()
        start_time = data.get('start_time', '').strip()
        end_time   = data.get('end_time', '').strip()

        if not name or not start_time or not end_time:
            return jsonify({"status": "error",
                            "message": "name, start_time, and end_time are required!"}), 400

        db     = get_db()
        cursor = db.cursor()
        cursor.execute(Q.INSERT_SHIFT, (name, start_time, end_time))
        db.commit()
        new_id = cursor.lastrowid
        cursor.close()
        db.close()
        return jsonify({"status": "success",
                        "message": f"Shift '{name}' added!",
                        "id": new_id})
    except mysql.connector.IntegrityError:
        return jsonify({"status": "error",
                        "message": "Shift already exists!"}), 409
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@shifts_bp.route('/shifts/<int:shift_id>', methods=['PUT'])
def edit_shift(shift_id):
    try:
        data       = request.json
        name       = data.get('name', '').strip()
        start_time = data.get('start_time', '').strip()
        end_time   = data.get('end_time', '').strip()

        if not name or not start_time or not end_time:
            return jsonify({"status": "error",
                            "message": "name, start_time, and end_time are required!"}), 400

        db     = get_db()
        cursor = db.cursor()
        cursor.execute(Q.UPDATE_SHIFT, (name, start_time, end_time, shift_id))
        db.commit()

        if cursor.rowcount == 0:
            return jsonify({"status": "error",
                            "message": "Shift not found!"}), 404

        cursor.close()
        db.close()
        return jsonify({"status": "success",
                        "message": f"Shift updated to '{name}'!"})
    except mysql.connector.IntegrityError:
        return jsonify({"status": "error",
                        "message": "Shift name already exists!"}), 409
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@shifts_bp.route('/shifts/<int:shift_id>', methods=['DELETE'])
def delete_shift(shift_id):
    try:
        db     = get_db()
        cursor = db.cursor()
        cursor.execute(Q.DELETE_SHIFT, (shift_id,))
        db.commit()

        if cursor.rowcount == 0:
            return jsonify({"status": "error",
                            "message": "Shift not found!"}), 404

        cursor.close()
        db.close()
        return jsonify({"status": "success", "message": "Shift deleted!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
