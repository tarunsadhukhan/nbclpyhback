from flask import Blueprint, request, jsonify
from src.mobileapp.db import get_db
from src.mobileapp.src.masters import query as Q

company_branch_bp = Blueprint('company_branch', __name__)


@company_branch_bp.route('/masters/get_company', methods=['GET'])
def get_company():
    try:
        user_id = request.args.get('user_id', type=int)
        db = get_db()
        cursor = db.cursor(dictionary=True)
        # Scope to the companies the user is mapped to in user_role_map.
        if user_id:
            cursor.execute(Q.GET_COMPANIES_BY_USER, (user_id,))
        else:
            cursor.execute(Q.GET_ALL_COMPANIES)
        rows = cursor.fetchall()
        cursor.close()
        db.close()
        return jsonify({
            "status": "success",
            "total": len(rows),
            "companies": rows,
            "data": rows
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@company_branch_bp.route('/masters/get_branch', methods=['GET'])
def get_branch():
    try:
        raw_company_id = request.args.get('company_id') or request.args.get('co_id')
        if not raw_company_id:
            return jsonify({
                "status": "error",
                "message": "company_id (or co_id) is required"
            }), 400

        try:
            company_id = int(raw_company_id)
            if company_id <= 0:
                raise ValueError
        except ValueError:
            return jsonify({
                "status": "error",
                "message": "company_id must be a positive integer"
            }), 400

        user_id = request.args.get('user_id', type=int)
        db = get_db()
        cursor = db.cursor(dictionary=True)
        # Scope to the branches the user is mapped to for this company.
        if user_id:
            cursor.execute(Q.GET_BRANCHES_BY_USER_COMPANY, (user_id, company_id))
        else:
            cursor.execute(Q.GET_BRANCHES_BY_COMPANY, (company_id,))
        rows = cursor.fetchall()
        cursor.close()
        db.close()

        return jsonify({
            "status": "success",
            "total": len(rows),
            "branches": rows,
            "data": rows
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

