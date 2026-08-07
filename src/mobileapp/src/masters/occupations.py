from flask import Blueprint, request, jsonify
import mysql.connector
from src.mobileapp.db import get_db
from src.mobileapp.src.masters import query as Q

occupations_bp = Blueprint('occupations', __name__)


@occupations_bp.route('/occupations', methods=['GET'])
def get_occupations():
    try:
        db     = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(Q.GET_ALL_OCCUPATIONS)
        rows = cursor.fetchall()
        for r in rows:
            r['created_at'] = str(r['created_at'])
        cursor.close()
        db.close()
        return jsonify({"status": "success", "total": len(rows), "data": rows})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@occupations_bp.route('/occupations', methods=['POST'])
def add_occupation():
    try:
        name = request.json.get('name', '').strip()
        if not name:
            return jsonify({"status": "error",
                            "message": "Occupation name is required!"}), 400

        db     = get_db()
        cursor = db.cursor()
        cursor.execute(Q.INSERT_OCCUPATION, (name,))
        db.commit()
        new_id = cursor.lastrowid
        cursor.close()
        db.close()
        return jsonify({"status": "success",
                        "message": f"Occupation '{name}' added!",
                        "id": new_id})
    except mysql.connector.IntegrityError:
        return jsonify({"status": "error",
                        "message": "Occupation already exists!"}), 409
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@occupations_bp.route('/occupations/<int:occ_id>', methods=['PUT'])
def edit_occupation(occ_id):
    try:
        name = request.json.get('name', '').strip()
        if not name:
            return jsonify({"status": "error",
                            "message": "Occupation name is required!"}), 400

        db     = get_db()
        cursor = db.cursor()
        cursor.execute(Q.UPDATE_OCCUPATION, (name, occ_id))
        db.commit()

        if cursor.rowcount == 0:
            return jsonify({"status": "error",
                            "message": "Occupation not found!"}), 404

        cursor.close()
        db.close()
        return jsonify({"status": "success",
                        "message": f"Occupation updated to '{name}'!"})
    except mysql.connector.IntegrityError:
        return jsonify({"status": "error",
                        "message": "Occupation name already exists!"}), 409
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@occupations_bp.route('/occupations/<int:occ_id>', methods=['DELETE'])
def delete_occupation(occ_id):
    try:
        db     = get_db()
        cursor = db.cursor()
        cursor.execute(Q.DELETE_OCCUPATION, (occ_id,))
        db.commit()

        if cursor.rowcount == 0:
            return jsonify({"status": "error",
                            "message": "Occupation not found!"}), 404

        cursor.close()
        db.close()
        return jsonify({"status": "success", "message": "Occupation deleted!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
