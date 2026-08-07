import json
import re
try:
    import face_recognition
except ImportError:
    face_recognition = None

import numpy as np
import mysql.connector
from flask import Blueprint, request, jsonify
from src.mobileapp.db import get_db
from src.mobileapp.src.utils import decode_image
from src.mobileapp.src.employees import query as Q
from src.mobileapp.src.schemas.employee import RegisterEmployeeSchema, UpdateFaceSchema

employees_bp = Blueprint('employees', __name__)


def _require_face_recognition():
    if face_recognition is None:
        return jsonify({
            "status": "error",
            "message": "face_recognition dependency is not installed on server"
        }), 503
    return None


# ── GET all employees ────────────────────────────────────────
@employees_bp.route('/employees', methods=['GET'])
def get_employees():
    try:
        db     = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(Q.GET_ALL_EMPLOYEES)
        rows = cursor.fetchall()
        cursor.close()
        db.close()

        for r in rows:
            if r.get('photo_html'):
                match = re.search(r'base64,([^"]+)', r['photo_html'])
                if match:
                    r['photo_base64'] = match.group(1)
            r.pop('photo_html', None)

        return jsonify({"status": "success", "total": len(rows), "data": rows})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── GET employee by emp_code ─────────────────────────────────
@employees_bp.route('/employee/<emp_code>', methods=['GET'])
def get_employee_by_code(emp_code):
    try:
        branch_id = request.args.get('branch_id')
        if not branch_id:
            return jsonify({"status": "error", "message": "branch_id is required"}), 400
        print(f"[employees.get_employee_by_code] Looking up employee by emp_code={emp_code!r}, branch_id={branch_id!r}")
        db     = get_db()
        cursor = db.cursor(dictionary=True)
        #print(f"[employees.get_employee_by_code] QUERY: {Q.GET_EMPLOYEE_BY_CODE}")
        #print(f"[employees.get_employee_by_code] PARAMS: emp_code={emp_code!r}, branch_id={branch_id!r}")
        cursor.execute(Q.GET_EMPLOYEE_BY_CODE, (emp_code, branch_id))
        employee = cursor.fetchone()
        _row_log = ({**employee, 'photo_html': f'<{len(employee["photo_html"])} chars>'}
                    if employee and employee.get('photo_html') else employee)
        #print(f"[employees.get_employee_by_code] ROW: {_row_log}")

        if not employee:
            cursor.close()
            db.close()
            return jsonify({"status": "error", "message": "Employee not found"}), 404

        # Last-worked department/designation + machines (most recent attendance)
        # so the attendance-entry screen can pre-fill designation and machine
        # numbers when the selected department matches where the employee last
        # worked. Null / empty when the employee has no prior attendance.
        default_department_id  = None
        default_designation_id = None
        default_machine_ids    = []
        cursor.execute(Q.GET_LAST_WORKED_BY_EB, (employee['eb_id'], branch_id))
        last = cursor.fetchone()
        #print(f"[employees.get_employee_by_code] Last worked: {last}")
        if last:
            default_department_id  = last['worked_department_id']
            default_designation_id = last['worked_designation_id']
            cursor.execute(Q.GET_LAST_WORKED_MACHINES, (last['daily_atten_id'],))
            default_machine_ids = [m['mc_id'] for m in cursor.fetchall() if m['mc_id']]

        cursor.close()
        db.close()
        print(f"{default_department_id} {default_designation_id}  Returning employee data for emp_code={emp_code!r}, branch_id={branch_id!r}"    )
        return jsonify({
            "status":                 "success",
            "eb_id":                  employee['eb_id'],
            "emp_code":               employee['emp_code'],
            "emp_name":               employee['name'].strip(),
            "department":             employee['department_name'] or '',
            "designation":            employee['designation_name'] or '',
            "branch_id":              employee['branch_id'],
            "photo_html":             employee.get('photo_html'),
            "default_department_id":  default_department_id,
            "default_designation_id": default_designation_id,
            "default_machine_ids":    default_machine_ids,
            "message":                f"Employee found: {employee['name'].strip()}"
        })
    except Exception as e:
        print(f"❌ Employee lookup error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Register employee ────────────────────────────────────────
@employees_bp.route('/register', methods=['POST'])
def register():
    try:
        missing_dep = _require_face_recognition()
        if missing_dep:
            return missing_dep
        data = request.json
        ok, errors = RegisterEmployeeSchema.validate(data)
        if not ok:
            return jsonify({"status": "error", "message": errors[0]}), 400

        print(f"📥 Register POST data: {  {k: (v[:50] + '...') if k == 'image' and isinstance(v, str) and len(v) > 50 else v for k, v in data.items()}  }")

        img_rgb   = decode_image(data['image'])
        encodings = face_recognition.face_encodings(img_rgb)
        #print(f"🔍 Detected {len(encodings)} face(s) for {data['name']}")

        if not encodings:
            return jsonify({"status": "error",
                            "message": "No face detected!"}), 400

        embedding = encodings[0].tolist()
        db        = get_db()
        cursor    = db.cursor()

        dept_id  = data.get('department_id')
        desig_id = data.get('designation_id')
        shift_id = data.get('shift_id')

        if not dept_id and data.get('department'):
            cursor.execute(Q.GET_DEPT_ID_BY_NAME, (data['department'],))
            row = cursor.fetchone()
            dept_id = row[0] if row else None

        if not desig_id and data.get('designation'):
            cursor.execute(Q.GET_DESIG_ID_BY_NAME, (data['designation'],))
            row = cursor.fetchone()
            desig_id = row[0] if row else None

        if not shift_id and data.get('shift'):
            cursor.execute(Q.GET_SHIFT_ID_BY_NAME, (data['shift'],))
            row = cursor.fetchone()
            shift_id = row[0] if row else None

        print(f"Registering {data['name']} with emp_code {data['emp_code']} "
              f"dept={dept_id} desig={desig_id} shift={shift_id}")

        photo_html = None
        try:
            photo_html = f'<img src="data:image/jpeg;base64,{data["image"]}" />'
            print(f"📸 Photo stored as HTML ({len(photo_html)} chars)")
        except Exception as pe:
            print(f"⚠️ Photo HTML build failed: {pe}")

        cursor.execute(Q.INSERT_EMPLOYEE,
                       (data['emp_code'], data['name'], dept_id, desig_id, shift_id,
                        json.dumps(embedding), photo_html))
        db.commit()
        cursor.close()
        db.close()
        return jsonify({"status": "success",
                        "message": f"{data['name']} registered!"})
    except mysql.connector.IntegrityError:
        return jsonify({"status": "error",
                        "message": "Employee code already exists!"}), 409
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Update employee face ─────────────────────────────────────
@employees_bp.route('/register/<emp_code>', methods=['PUT'])
def update_face(emp_code):
    try:
        missing_dep = _require_face_recognition()
        if missing_dep:
            return missing_dep
        data = request.json
        ok, errors = UpdateFaceSchema.validate(data)
        if not ok:
            return jsonify({"status": "error", "message": errors[0]}), 400

        img_rgb   = decode_image(data['image'])
        encodings = face_recognition.face_encodings(img_rgb)

        if not encodings:
            return jsonify({"status": "error",
                            "message": "No face detected!"}), 400

        embedding = encodings[0].tolist()
        db        = get_db()
        cursor    = db.cursor()
        cursor.execute(Q.UPDATE_EMPLOYEE_FACE, (json.dumps(embedding), emp_code))
        db.commit()

        if cursor.rowcount == 0:
            return jsonify({"status": "error",
                            "message": "Employee not found!"}), 404

        cursor.close()
        db.close()
        return jsonify({"status": "success",
                        "message": f"Face updated for emp_code {emp_code}!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Update employee details ──────────────────────────────────
@employees_bp.route('/employees/<int:emp_id>', methods=['PUT'])
def update_employee(emp_id):
    try:
        data   = request.json
        db     = get_db()
        cursor = db.cursor()

        fields = []
        values = []

        if 'name' in data:
            fields.append("name = %s"); values.append(data['name'])
        if 'emp_code' in data:
            fields.append("emp_code = %s"); values.append(data['emp_code'])
        if 'department_id' in data:
            fields.append("department_id = %s"); values.append(data['department_id'])
        if 'designation_id' in data:
            fields.append("designation_id = %s"); values.append(data['designation_id'])
        if 'shift_id' in data:
            fields.append("shift_id = %s"); values.append(data['shift_id'])

        if 'face_image' in data and data['face_image']:
            missing_dep = _require_face_recognition()
            if missing_dep:
                return missing_dep
            try:
                img_rgb   = decode_image(data['face_image'])
                encodings = face_recognition.face_encodings(img_rgb)
                if encodings:
                    fields.append("face_embedding = %s")
                    values.append(json.dumps(encodings[0].tolist()))
                    photo_html = f'<img src="data:image/jpeg;base64,{data["face_image"]}" />'
                    fields.append("photo_html = %s")
                    values.append(photo_html)
            except Exception as fe:
                print(f"⚠️ Face update skipped: {fe}")

        if not fields:
            return jsonify({"status": "error",
                            "message": "No fields to update!"}), 400

        values.append(emp_id)
        sql = f"UPDATE employees SET {', '.join(fields)} WHERE id = %s"
        cursor.execute(sql, tuple(values))
        db.commit()

        if cursor.rowcount == 0:
            return jsonify({"status": "error",
                            "message": "Employee not found!"}), 404

        cursor.close()
        db.close()
        return jsonify({"status": "success", "message": "Employee updated!"})
    except mysql.connector.IntegrityError:
        return jsonify({"status": "error",
                        "message": "Employee code already exists!"}), 409
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Delete (soft) employee ───────────────────────────────────
@employees_bp.route('/employees/<int:emp_id>', methods=['DELETE'])
def delete_employee(emp_id):
    try:
        db     = get_db()
        cursor = db.cursor()
        cursor.execute(Q.SOFT_DELETE_EMPLOYEE, (emp_id,))
        db.commit()

        if cursor.rowcount == 0:
            return jsonify({"status": "error",
                            "message": "Employee not found!"}), 404

        cursor.close()
        db.close()
        return jsonify({"status": "success", "message": "Employee deleted!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
# -- Search employees by emp_code or name --------------------------------------
@employees_bp.route('/employees/search', methods=['GET'])
def search_employees():
    """Search employees by emp_code or name (partial match), optionally filtered by branch_id."""
    try:
        query     = (request.args.get('q') or '').strip()
        branch_id = request.args.get('branch_id', type=int)
        if not query:
            return jsonify({'status': 'error', 'message': 'Search query is required'}), 400
        db     = get_db()
        cursor = db.cursor(dictionary=True)
        like   = f'%{query}%'
        sql = """
            SELECT p.eb_id AS id, o.emp_code,
                   TRIM(CONCAT(
                       COALESCE(p.first_name,''), ' ',
                       COALESCE(p.middle_name,''), ' ',
                       COALESCE(p.last_name,''))) AS name,
                   o.branch_id,
                   o.sub_dept_id  AS department_id,
                   o.designation_id,
                   NULL           AS photo_html
            FROM hrms_ed_personal_details p
            INNER JOIN hrms_ed_official_details o ON p.eb_id = o.eb_id
            WHERE (p.active IS NULL OR p.active != 0)
              AND (o.emp_code LIKE %s
                   OR p.first_name  LIKE %s
                   OR p.last_name   LIKE %s
                   OR CONCAT(p.first_name,' ',COALESCE(p.last_name,'')) LIKE %s)
        """
        params = [like, like, like, like]
        if branch_id:
            sql += " AND o.branch_id = %s"
            params.append(branch_id)
        sql += " ORDER BY p.first_name LIMIT 20"
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        cursor.close()
        db.close()
        return jsonify({'status': 'success', 'data': rows, 'employees': rows, 'total': len(rows)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
