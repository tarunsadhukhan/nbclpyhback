from flask import Blueprint, request, jsonify
from src.mobileapp.db import get_db

machines_bp = Blueprint('machines', __name__)

GET_MACHINES_BY_DESIGNATION = """
    SELECT mm.machine_id id, CONCAT(mm.mech_code, ' ', mm.machine_name) AS name,
    mech_code , mech_posting_code machine_no
    FROM machine_mst mm
    LEFT JOIN mech_occu_link mol ON mm.machine_id = mol.mech_id
    WHERE mol.occu_id = %s order by mm.mech_code,mm.machine_name
"""
print ('GET MC', GET_MACHINES_BY_DESIGNATION)

@machines_bp.route('/machines', methods=['GET'])
def get_machines():
    try:
        designation_id = request.args.get('designation_id', type=int)
        if not designation_id:
            return jsonify({"status": "error", "message": "designation_id is required"}), 400

        db     = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(GET_MACHINES_BY_DESIGNATION, (designation_id,))
        rows = cursor.fetchall()
        cursor.close()
        db.close()

        return jsonify({"status": "success", "total": len(rows), "data": rows})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
