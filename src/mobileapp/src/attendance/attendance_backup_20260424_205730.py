import json
import re
try:
    import face_recognition
except ImportError:
    face_recognition = None

import numpy as np
from datetime import datetime, date
from flask import Blueprint, request, jsonify
from src.mobileapp.db import get_db
from src.mobileapp.src.utils import decode_image
from src.mobileapp.src.employees.query import GET_ALL_EMPLOYEES_WITH_FACE, GET_EMPLOYEE_WITH_DETAILS
from src.mobileapp.src.attendance import query as Q
from src.mobileapp.src.schemas.attendance import (MarkAttendanceSchema, ManualAttendanceSchema,
                                    CheckFaceSchema, AttendanceReportSchema)

attendance_bp = Blueprint('attendance', __name__)


def _require_face_recognition():
    if face_recognition is None:
        return jsonify({
            "status": "error",
            "message": "face_recognition dependency is not installed on server"
        }), 503
    return None



# ── Face-based attendance ────────────────────────────────────
@attendance_bp.route('/attendance', methods=['POST'])
def mark_attendance():
    try:
        missing_dep = _require_face_recognition()
        if missing_dep:
            return missing_dep
        data = request.json
        ok, errors = MarkAttendanceSchema.validate(data)
        if not ok:
            return jsonify({"status": "error", "message": errors[0]}), 400

        img_rgb        = decode_image(data['image'])
        live_encodings = face_recognition.face_encodings(img_rgb)
        att_type       = data.get('attendance_type') or data.get('att_type', 'R')

        print(f"📥 Attendance POST data: {  {k: (v[:50] + '...') if k == 'image' and isinstance(v, str) and len(v) > 50 else v for k, v in data.items()}  }")

        if not live_encodings:
            return jsonify({"status": "error",
                            "message": "No face detected!"}), 400

        live_enc = live_encodings[0]
        db       = get_db()
        cursor   = db.cursor(dictionary=True)
        cursor.execute(GET_ALL_EMPLOYEES_WITH_FACE)
        employees = cursor.fetchall()

        if not employees:
            return jsonify({"status": "error",
                            "message": "No employees registered!"}), 404

        stored_encs = [np.array(json.loads(e['face_embedding'])) for e in employees]
        matches     = face_recognition.compare_faces(stored_encs, live_enc, tolerance=0.5)
        distances   = face_recognition.face_distance(stored_encs, live_enc)
        best_idx    = int(np.argmin(distances))

        if not matches[best_idx]:
            return jsonify({"status": "not_recognized",
                            "message": "Face not recognized!"}), 401

        emp            = employees[best_idx]
        eb_id          = emp['eb_id']
        emp_code       = emp['emp_code']
        name           = emp['name'].strip()
        dept           = emp['department_name']
        desig          = emp['designation_name']
        photo_html_val = emp['photo_html']
        branch_id      = emp.get('branch_id')

        att_date       = data.get('attendance_date') or str(date.today())
        shift_id       = data.get('shift_id')
        department_id  = data.get('department_id')
        designation_id = data.get('designation_id')
        shift_hours    = data.get('shift_hours',   0)
        working_hours  = data.get('working_hours', 0)
        idle_hours     = data.get('idle_hours',    0)

        # Get spell name from shift_id if provided
        spell_name = None
        if shift_id:
            cursor.execute("SELECT spell_name FROM spell_mst WHERE spell_id = %s", (shift_id,))
            spell_row = cursor.fetchone()
            spell_name = spell_row['spell_name'] if spell_row else None

        print(f"[ATT] eb_id={eb_id} emp_code={emp_code} att_type={att_type} "
              f"date={att_date} dept={department_id} shift={shift_id} desig={designation_id} "
              f"hrs={shift_hours}/{working_hours}/{idle_hours}")

        cursor.execute(Q.INSERT_ATTENDANCE,
                     (eb_id, att_date,
                    'Face', att_type,
                        'P', branch_id,
                        spell_name, shift_hours, department_id, designation_id,
                        working_hours, idle_hours))
        
        # Get the inserted attendance ID
        attendance_id = cursor.lastrowid
        
        # Save machine data to daily_ebmc_attendance if machines are provided
        machine_ids = data.get('machine_ids', [])
        if machine_ids and isinstance(machine_ids, list):
            for machine_id in machine_ids:
                cursor.execute(Q.INSERT_MACHINE_ATTENDANCE,
                             (attendance_id, eb_id, machine_id, att_date, branch_id))
        
        db.commit()
        cursor.close()
        db.close()

        return jsonify({
            "status":            "success",
            "message":           "Attendance marked!",
            "employee":          name,
            "emp_code":          emp_code,
            "emp_name":          name,
            "photo_html":        photo_html_val,
            "department":        dept,
            "designation":       desig,
            "attendance_status": "Face",
            "att_type":          att_type,
            "status_id":         "3",
            "is_active":         1,
            "time":              datetime.now().strftime("%H:%M:%S"),
            "confidence":        round((1 - float(distances[best_idx])) * 100, 1)
        })
    except Exception as e:
        print(f"❌ Attendance error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Manual attendance ────────────────────────────────────────
@attendance_bp.route('/mark-attendance', methods=['POST'])

def mark_attendance_manual():
    try:
        data = request.json
        ok, errors = ManualAttendanceSchema.validate(data)
        if not ok:


            return jsonify({"status": "error", "message": errors[0]}), 400

        emp_code  = data.get('emp_code', '').strip()
        att_type  = data.get('attendance_type') or data.get('att_type', 'R')
        branch_id = data.get('branch_id')

        if not emp_code:

            return jsonify({"status": "error",
                            "message": "Employee code is required!"}), 400
        if not branch_id:
            return jsonify({"status": "error",
                            "message": "branch_id is required!"}), 400

        db     = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(GET_EMPLOYEE_WITH_DETAILS, (emp_code, branch_id))
        employee = cursor.fetchone()

        if not employee:
            cursor.close(); db.close()
            return jsonify({"status": "error",
                            "message": f"Employee '{emp_code}' not found or inactive!"}), 404

        eb_id          = employee['eb_id']
        name           = employee['name'].strip()
        att_date       = data.get('attendance_date') or str(date.today())
        shift_id       = data.get('shift_id')

        department_id  = data.get('department_id')

        designation_id = data.get('designation_id')

        shift_hours    = data.get('shift_hours',   0)

        working_hours  = data.get('working_hours', 0)
        idle_hours     = data.get('idle_hours',    0)

        # Get spell name from shift_id if provided
        spell_name = None
        if shift_id:
            cursor.execute("SELECT spell_name FROM spell_mst WHERE spell_id = %s", (shift_id,))
            spell_row = cursor.fetchone()
            spell_name = spell_row['spell_name'] if spell_row else None

        print(f"[MANUAL-ATT] eb_id={eb_id} emp_code={emp_code} att_type={att_type} "
              f"date={att_date} dept={department_id} shift={shift_id} desig={designation_id} "
              f"hrs={shift_hours}/{working_hours}/{idle_hours}")

        cursor.execute(Q.INSERT_ATTENDANCE,
                     (eb_id, att_date,
                    'Manual', att_type,
                        'P', branch_id,
                        spell_name, shift_hours, department_id, designation_id,
                        working_hours, idle_hours))
        
        # Get the inserted attendance ID
        attendance_id = cursor.lastrowid
        
        # Save machine data to daily_ebmc_attendance if machines are provided
        machine_ids = data.get('machine_ids', [])
        if machine_ids and isinstance(machine_ids, list):
            for machine_id in machine_ids:
                cursor.execute(Q.INSERT_MACHINE_ATTENDANCE,
                             (attendance_id, eb_id, machine_id, att_date, branch_id))
        
        db.commit()
        cursor.close()
        db.close()

        return jsonify({
            "status":    "success",
            "emp_code":  emp_code,
            "emp_name":  name,
            "status_id": "3",
            "is_active": 1,
            "message":   f"Attendance marked for {name} (Manual)"
        })
    except Exception as e:
        print(f"❌ Manual attendance error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Check face only (no attendance) ─────────────────────────
@attendance_bp.route('/check-face', methods=['POST'])
def check_face():
    try:
        missing_dep = _require_face_recognition()
        if missing_dep:
            return missing_dep
        data = request.json
        ok, errors = CheckFaceSchema.validate(data)
        if not ok:
            return jsonify({"status": "error", "message": errors[0]}), 400

        print(f"📥 Check-face POST: image={len(data.get('image', ''))} chars")

        img_rgb        = decode_image(data['image'])
        live_encodings = face_recognition.face_encodings(img_rgb)

        if not live_encodings:
            return jsonify({"status": "error",
                            "message": "No face detected in image!"}), 400

        live_enc = live_encodings[0]
        db       = get_db()
        cursor   = db.cursor(dictionary=True)
        cursor.execute(GET_ALL_EMPLOYEES_WITH_FACE)
        employees = cursor.fetchall()
        cursor.close()
        db.close()

        if not employees:
            return jsonify({"status": "error",
                            "message": "No employees with face registered!"}), 404

        stored_encs = [np.array(json.loads(e['face_embedding'])) for e in employees]
        distances   = face_recognition.face_distance(stored_encs, live_enc)
        best_idx    = int(np.argmin(distances))
        best_dist   = float(distances[best_idx])

        if best_dist > 0.5:
            return jsonify({"status": "not_recognized",
                            "message": "Face not recognized!"}), 401

        emp            = employees[best_idx]
        name           = emp['name'].strip()
        photo_html_val = emp['photo_html']
        print(f"✅ Face matched: {name} ({emp['emp_code']}) distance={best_dist:.3f}")

        return jsonify({
            "status":      "success",
            "emp_code":    emp['emp_code'],
            "emp_name":    name,
            "photo_html":  photo_html_val,
            "department":  emp['department_name'],
            "designation": emp['designation_name'],
            "confidence":  round((1 - best_dist) * 100, 1),
            "message":     f"Face matched: {name}"
        })
    except Exception as e:
        print(f"❌ Check-face error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Today's report ───────────────────────────────────────────
@attendance_bp.route('/report/today', methods=['GET'])
def today_report():
    try:
        db     = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(Q.GET_TODAY_REPORT)
        rows = cursor.fetchall()
        cursor.close()
        db.close()

        for r in rows:
            r['check_in'] = str(r['check_in'])

        return jsonify({"status": "success",
                        "date":   str(date.today()),
                        "total":  len(rows),
                        "data":   rows})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Monthly report ───────────────────────────────────────────
@attendance_bp.route('/report/monthly', methods=['GET'])
def monthly_report():
    try:
        month  = request.args.get('month', datetime.now().month)
        year   = request.args.get('year',  datetime.now().year)
        db     = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(Q.GET_MONTHLY_REPORT, (month, year))
        rows = cursor.fetchall()
        cursor.close()
        db.close()

        for r in rows:
            r['date']     = str(r['date'])
            r['check_in'] = str(r['check_in'])

        return jsonify({"status": "success",
                        "month": month, "year": year,
                        "total": len(rows), "data": rows})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Attendance report (date-range filter) ────────────────────
@attendance_bp.route('/attendance-report', methods=['GET'])
def attendance_report():
    try:
        ok, errors = AttendanceReportSchema.validate(dict(request.args))
        if not ok:
            return jsonify({'status': 'error', 'message': errors[0]}), 400

        from_date     = request.args.get('from_date')
        to_date       = request.args.get('to_date')
        department_id = request.args.get('department_id')
        emp_code      = request.args.get('emp_code', '').strip()

        db     = get_db()
        cursor = db.cursor(dictionary=True)

        sql    = Q.GET_ATTENDANCE_REPORT_BASE
        params = [from_date, to_date]

        if department_id:
            sql += " AND o.sub_dept_id = %s"
            params.append(department_id)
        if emp_code:
            sql += " AND o.emp_code LIKE %s"
            params.append(f"%{emp_code}%")

        sql += " ORDER BY da.attendance_date DESC, da.entry_time DESC"
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        cursor.close()
        db.close()

        data = [{
            'id':               row['id'],
            'emp_code':         row['emp_code'],
            'emp_name':         row['emp_name'] or '',
            'department_name':  row['department_name'] or '',
            'designation_name': row['designation_name'] or '',
            'shift_name':       row['shift_name'] or '',
            'attendance_date':  str(row['attendance_date']),
            'attendance_time':  str(row['attendance_time']),
            'status':           row['status'] or '',
            'att_type':         row['att_type'] or 'R',
            'shift_hours':      float(row['shift_hours']),
            'working_hours':    float(row['working_hours']),
            'idle_hours':       float(row['idle_hours']),
            'has_photo':        bool(row['has_photo'])
        } for row in rows]

        return jsonify({'status': 'success', 'data': data, 'total': len(data)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Get attendance photo ─────────────────────────────────────
@attendance_bp.route('/attendance-photo/<int:att_id>', methods=['GET'])
def attendance_photo(att_id):
    try:
        db     = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(Q.GET_ATTENDANCE_PHOTO, (att_id,))
        row = cursor.fetchone()
        cursor.close()
        db.close()

        if not row or not row.get('photo_att'):
            return jsonify({'status': 'error', 'message': 'No photo'}), 404

        match     = re.search(r'base64,([^"]+)', row['photo_att'])
        photo_b64 = match.group(1) if match else None

        return jsonify({'status': 'success', 'photo_att': photo_b64})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


