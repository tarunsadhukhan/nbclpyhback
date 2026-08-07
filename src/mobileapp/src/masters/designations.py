from flask import Blueprint, request, jsonify
from src.mobileapp.db import get_db
from src.mobileapp.src.masters import query as Q

designations_bp = Blueprint('designations', __name__)


@designations_bp.route('/designations', methods=['GET'])
def get_designations():
    """
    Returns designations from designation_mst.
    ?branch_id=29              → all active designations for that branch
    ?branch_id=29&sub_dept_id=1 → designations for that branch + department
    """
    try:
        branch_id   = request.args.get('branch_id',   type=int)
        sub_dept_id = request.args.get('sub_dept_id', type=int)

        db     = get_db()
        cursor = db.cursor(dictionary=True)

        if branch_id and sub_dept_id:
            cursor.execute(Q.GET_DESIGNATIONS_BY_DEPT_BRANCH, (sub_dept_id, branch_id))
        elif branch_id:
            cursor.execute(Q.GET_DESIGNATIONS_BY_BRANCH, (branch_id,))
        else:
            return jsonify({"status": "error", "message": "branch_id is required"}), 400

        rows = cursor.fetchall()
        cursor.close()
        db.close()
        return jsonify({"status": "success", "total": len(rows), "data": rows})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

