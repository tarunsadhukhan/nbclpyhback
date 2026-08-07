from flask import Blueprint, request, jsonify
import mysql.connector
from src.mobileapp.db import get_db
from src.mobileapp.src.masters import query as Q

departments_bp = Blueprint('departments', __name__)

@departments_bp.route('/departments', methods=['GET'])
def get_departments():
    try:
        branch_id = request.args.get('branch_id', type=int)
        co_id     = request.args.get('co_id',     type=int)

        db     = get_db()
        cursor = db.cursor(dictionary=True)

        if branch_id:
            # Strict: show only departments of this branch
            cursor.execute(Q.GET_DEPARTMENTS_BY_BRANCH, (branch_id,))
        elif co_id:
            cursor.execute(Q.GET_DEPARTMENTS_BY_COMPANY, (co_id,))
        else:
            cursor.execute(Q.GET_ALL_DEPARTMENTS)

        rows = cursor.fetchall()
        cursor.close()
        db.close()
        return jsonify({"status": "success", "total": len(rows), "data": rows})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@departments_bp.route('/departments', methods=['POST'])
def add_department():
    try:
        name = request.json.get('name', '').strip()
        if not name:
            return jsonify({"status": "error",
                            "message": "Department name is required!"}), 400

        db     = get_db()
        cursor = db.cursor()
        cursor.execute(Q.INSERT_DEPARTMENT, (name,))
        db.commit()
        new_id = cursor.lastrowid
        cursor.close()
        db.close()
        return jsonify({"status": "success",
                        "message": f"Department '{name}' added!",
                        "id": new_id})
    except mysql.connector.IntegrityError:
        return jsonify({"status": "error",
                        "message": "Department already exists!"}), 409
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@departments_bp.route('/departments/<int:dept_id>', methods=['PUT'])
def edit_department(dept_id):
    try:
        name = request.json.get('name', '').strip()
        if not name:
            return jsonify({"status": "error",
                            "message": "Department name is required!"}), 400

        db     = get_db()
        cursor = db.cursor()
        cursor.execute(Q.UPDATE_DEPARTMENT, (name, dept_id))
        db.commit()

        if cursor.rowcount == 0:
            return jsonify({"status": "error",
                            "message": "Department not found!"}), 404

        cursor.close()
        db.close()
        return jsonify({"status": "success",
                        "message": f"Department updated to '{name}'!"})
    except mysql.connector.IntegrityError:
        return jsonify({"status": "error",
                        "message": "Department name already exists!"}), 409
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@departments_bp.route('/departments/<int:dept_id>', methods=['DELETE'])
def delete_department(dept_id):
    try:
        db     = get_db()
        cursor = db.cursor()
        cursor.execute(Q.DELETE_DEPARTMENT, (dept_id,))
        db.commit()

        if cursor.rowcount == 0:
            return jsonify({"status": "error",
                            "message": "Department not found!"}), 404

        cursor.close()
        db.close()
        return jsonify({"status": "success", "message": "Department deleted!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
