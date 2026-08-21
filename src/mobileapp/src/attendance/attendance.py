import json
import os
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
from src.mobileapp.src.attendance import face_cache
from src.mobileapp.src.schemas.attendance import (MarkAttendanceSchema, ManualAttendanceSchema,
                                    CheckFaceSchema, AttendanceReportSchema)

attendance_bp = Blueprint('attendance', __name__)


# ── Face-match tuning ────────────────────────────────────────
# A live face is accepted only when the closest stored embedding is within
# MATCH_THRESHOLD *and* clearly closer than the nearest *different* employee
# by at least MATCH_MARGIN. The margin rejects near-ties (two people almost
# equally close); the threshold is the real defence against an *unregistered*
# person being matched to whoever happens to be their nearest enrolled
# neighbour (the margin can't help there — there is no second identity to
# compare against).
#
# 0.46 is chosen from the live data, not guessed: across all enrolled faces
# the worst *same-person* distance is 0.437 while the closest *different-person*
# distance is 0.490. 0.50 sat ABOVE that 0.490 collision, so two genuinely
# different people already fell inside the window and any unregistered face
# within 0.50 of someone validated wrongly. 0.46 lands in the clean gap
# (0.437 < 0.46 < 0.490): every legitimate match is still accepted while the
# different-person collision and unregistered faces are rejected.
MATCH_THRESHOLD = 0.46
MATCH_MARGIN    = 0.08


# ── Live-face detection scale ────────────────────────────────
# face_recognition.face_encodings() detects at number_of_times_to_upsample=1,
# which doubles the image before the HOG scan — a 540x720 phone selfie (what
# FaceValidateActivity.kt actually uploads) gets scanned at 1080x1440. Measured:
# ~465 ms at upsample=1 vs ~99 ms at upsample=0, and detection is the dominant
# cost of a punch. The face already fills a selfie; upsampling finds nothing
# extra.
#
# The risk this carries: a different detection scale shifts the box, which
# shifts the alignment, which shifts the 128-d embedding — and MATCH_THRESHOLD
# below has almost no room (worst same-person 0.437, closest different-person
# 0.490). scripts/validate_face_upsample.py measures that shift against the
# real enrolled set, and scripts/backfill_face_upsample.py re-encodes the
# stored side if validation says it is needed.
#
# Defaults to 1 — the OLD, slow, known-good scale. The fast path is deliberately
# off until scripts/validate_face_upsample.py has been run against the enrolled
# set: shipping an unvalidated change to face matching means workers who cannot
# clock in, which is worse than a slow punch. Once validation passes, set
# FACE_UPSAMPLE=0 in the container env to switch it on — no code change.
FACE_UPSAMPLE = int(os.getenv("FACE_UPSAMPLE", "1"))


def _encode_live_face(img_rgb):
    """Live 128-d encodings for img_rgb, detecting at FACE_UPSAMPLE.

    Falls back to upsample=1 when the faster scale finds nothing, so this can
    only ever detect *more* faces than the old code, never fewer — a worker
    whose face needs the slower scan still gets in instead of hitting
    "No face detected". Those fallback punches are encoded at a different scale
    than the stored embeddings; MATCH_THRESHOLD and MATCH_MARGIN are what stop a
    drifted embedding from landing on the wrong person."""
    locs = face_recognition.face_locations(
        img_rgb, number_of_times_to_upsample=FACE_UPSAMPLE)
    if not locs and FACE_UPSAMPLE != 1:
        locs = face_recognition.face_locations(img_rgb, number_of_times_to_upsample=1)
    if not locs:
        return []
    # Only the first detection is ever used by the callers below, so encode one
    # face rather than every face that happens to be in frame.
    return face_recognition.face_encodings(img_rgb, known_face_locations=locs[:1])


def _match_face(stored_encs, employees, live_enc):
    """Return (emp, best_dist) for the best confident match, or (None, best_dist)
    when the face is unrecognised or too ambiguous to call.

    employees[i] is the metadata for stored_encs[i]; an employee may have
    several stored embeddings, so the ambiguity check compares against the
    nearest embedding belonging to a *different* eb_id."""
    distances = face_recognition.face_distance(stored_encs, live_enc)
    order     = np.argsort(distances)
    best_idx  = int(order[0])
    best_dist = float(distances[best_idx])

    # 1) Closest face must actually be close enough.
    if best_dist > MATCH_THRESHOLD:
        return None, best_dist

    # 2) Ambiguity guard: the nearest *different* employee must be clearly
    #    farther away, otherwise the match is a coin-flip → reject.
    best_eb = employees[best_idx]['eb_id']
    for idx in order[1:]:
        if employees[int(idx)]['eb_id'] != best_eb:
            if float(distances[int(idx)]) - best_dist < MATCH_MARGIN:
                return None, best_dist
            break

    return employees[best_idx], best_dist


def _leave_payable(cursor, eb_id, att_date):
    """The leave-type `payable` flag ('Y'/'N') if the employee is on leave on
    att_date per vw_leave_dates, else None (not on leave)."""
    cursor.execute(
        "SELECT payable FROM vw_leave_dates WHERE eb_id = %s AND leave_date = %s LIMIT 1",
        (eb_id, att_date))
    row = cursor.fetchone()
    return (row['payable'] or 'N').strip().upper() if row else None


def _leave_conflict(cursor, eb_id, att_date, att_type):
    """Error message if attendance collides with a leave on att_date, else None.

    payable='Y' (paid leave): the day is already paid — only Cash/OT allowed,
    a Regular mark would double-pay it. Otherwise (unpaid leave): nothing
    may be saved."""
    payable = _leave_payable(cursor, eb_id, att_date)
    if payable is None:
        return None
    if payable == 'Y':
        if str(att_type or 'R').strip().upper() == 'R':
            return ("Employee is on paid leave on this date — only Cash or "
                    "Over Time attendance is allowed, not Regular")
        return None
    return "Employee is on leave on this date — attendance cannot be saved"


def _spell_hours_conflict(cursor, eb_id, att_date, spell_id, spell_cap,
                          working_hours, idle_hours, exclude_atten_id=None):
    """Error message when this entry's net hours (working - idle) plus the
    employee's other active attendance for the same date + spell would exceed
    the spell's working hours, else None. exclude_atten_id skips the row being
    edited so an update doesn't count itself."""
    try:
        cap     = float(spell_cap or 0)
        new_net = float(working_hours or 0) - float(idle_hours or 0)
    except (TypeError, ValueError):
        return None
    if cap <= 0 or not spell_id:
        return None
    sql = ("SELECT COALESCE(SUM(COALESCE(working_hours,0) - COALESCE(idle_hours,0)), 0) AS worked "
           "FROM daily_attendance "
           "WHERE eb_id = %s AND attendance_date = %s AND spell_id = %s AND is_active = 1")
    params = [eb_id, att_date, spell_id]
    if exclude_atten_id is not None:
        sql += " AND daily_atten_id <> %s"
        params.append(exclude_atten_id)
    cursor.execute(sql, tuple(params))
    already = float(cursor.fetchone()['worked'] or 0)
    if already + new_net > cap:
        return (f"Worked hours for this date/spell would total {already + new_net:g} "
                f"({already:g} already saved + {new_net:g} new) — more than the "
                f"spell hours ({cap:g})")
    return None


def _photo_b64(photo_html):
    """Base64 payload out of a stored photo_html, or None.

    The column holds either an HTML wrapper —
    <img src="data:image/jpeg;base64,XXXX" /> — or a bare base64 string, and in
    this database most rows are the bare form. A regex-only read returns None
    for those, which is why /attendance-photo answered 'success' with a null
    photo."""
    if not photo_html:
        return None
    match = re.search(r'base64,([^"]+)', photo_html)
    if match:
        return match.group(1).strip() or None
    stripped = photo_html.strip()
    return stripped if stripped and '<' not in stripped else None


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
        live_encodings = _encode_live_face(img_rgb)
        att_type       = data.get('attendance_type') or data.get('att_type', 'R')

        print(f"📥 Attendance POST data: {  {k: (v[:50] + '...') if k == 'image' and isinstance(v, str) and len(v) > 50 else v for k, v in data.items()}  }")

        if not live_encodings:
            return jsonify({"status": "error",
                            "message": "No face detected!"}), 400

        live_enc = live_encodings[0]

        # Scope face matching to the selected branch only.
        req_branch_id = data.get('branch_id')
        stored_encs, employees = face_cache.load(req_branch_id)
        if stored_encs.shape[0] == 0:
            return jsonify({"status": "error",
                            "message": "No employees registered for this branch!"}), 404

        emp, best_dist = _match_face(stored_encs, employees, live_enc)
        if emp is None:
            return jsonify({"status": "not_recognized",
                            "message": "Face not recognized!"}), 401

        eb_id          = emp['eb_id']
        emp_code       = emp['emp_code']
        name           = emp['name'].strip()
        dept           = emp['department_name']
        desig          = emp['designation_name']
        photo_html_val = face_cache.get_photo_html(eb_id)
        branch_id      = emp.get('branch_id')

        db     = get_db()
        cursor = db.cursor(dictionary=True)

        att_date       = data.get('attendance_date') or str(date.today())
        shift_id       = data.get('shift_id')
        department_id  = data.get('department_id')
        designation_id = data.get('designation_id')
        shift_hours    = data.get('shift_hours',   0)
        working_hours  = data.get('working_hours', 0)
        idle_hours     = data.get('idle_hours',    0)
        geo_location   = data.get('get_location') or None  # "latitude,longitude" or None

        # Spell working-hours cap from spell_mst (shift_id IS the spell_id)
        spell_cap = None  # spell_mst.working_hours — cap for the date+spell total
        if shift_id:
            cursor.execute("SELECT working_hours FROM spell_mst WHERE spell_id = %s", (shift_id,))
            spell_row = cursor.fetchone()
            spell_cap = spell_row['working_hours'] if spell_row else None

        print(f"[ATT] eb_id={eb_id} emp_code={emp_code} att_type={att_type} "
              f"date={att_date} dept={department_id} shift={shift_id} desig={designation_id} "
              f"hrs={shift_hours}/{working_hours}/{idle_hours} geo={geo_location}")

        conflict = (_leave_conflict(cursor, eb_id, att_date, att_type)
                    or _spell_hours_conflict(cursor, eb_id, att_date, shift_id,
                                             spell_cap or shift_hours,
                                             working_hours, idle_hours))
        if conflict:
            cursor.close(); db.close()
            return jsonify({"status": "error", "message": conflict}), 400

        cursor.execute(Q.INSERT_ATTENDANCE,
                     (eb_id, att_date,
                    'F', att_type,
                        'P', branch_id,
                        shift_id, shift_hours, department_id, designation_id,
                        working_hours, idle_hours, geo_location))

        # Get the inserted attendance ID
        attendance_id = cursor.lastrowid

        # Save machine data to daily_ebmc_attendance if machines are provided
        machine_ids = data.get('machine_ids', [])
        if machine_ids and isinstance(machine_ids, list):
            for machine_id in machine_ids:
                cursor.execute(Q.INSERT_MACHINE_ATTENDANCE,
                             (attendance_id, eb_id, machine_id, shift_id, branch_id))

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
            "confidence":        round((1 - best_dist) * 100, 1)
        })
    except Exception as e:
        print(f"❌ Attendance error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Offline replay support ───────────────────────────────────
# Records queued by the Android app while it had no network arrive here later,
# carrying the time they actually happened plus (for an on-device face match)
# the capture, so the server can re-verify it with dlib. All of it is optional:
# a live submit sends none of these fields and behaves exactly as before, and a
# tenant database without offline_sync.sql simply ignores the extras.

def _offline_columns_present(cursor):
    """Which offline columns exist on daily_attendance in THIS tenant DB."""
    try:
        cursor.execute(
            """SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'daily_attendance'
                 AND COLUMN_NAME IN ('client_uuid','entry_source_time','sync_received_time',
                                     'clock_skew_secs','face_verify_status','match_confidence',
                                     'needs_review','dup_of')""")
        return {r[0] if not isinstance(r, dict) else r['COLUMN_NAME'] for r in cursor.fetchall()}
    except Exception:
        return set()


def _offline_context(data, cursor, eb_id, att_date, att_type, shift_id):
    """Everything the offline path needs, or a no-op context for a live submit."""
    ctx = {
        'queued': bool(data.get('offline_queued')),
        'source': None,
        'punch_time': None,
        'dup_of': None,
        'supersedes': None,
        'face_verify_status': None,
        'needs_review': 0,
        'client_uuid': data.get('client_uuid'),
        'clock_skew_secs': data.get('clock_skew_secs'),
        'match_confidence': data.get('match_confidence'),
        'entry_time': None,
        'columns': set(),
    }
    if not ctx['queued']:
        return ctx

    from src.mobileapp.src.sync.routes import parse_client_time, reverify_offline_face, store_offline_photo

    ctx['columns'] = _offline_columns_present(cursor)
    ctx['entry_time'] = parse_client_time(data.get('entry_time'))
    ctx['punch_time'] = ctx['entry_time'] or datetime.now()

    # Cross-device duplicate rule: keep the EARLIEST entry_time for the same
    # employee/date/spell/type, park the later one inactive.
    if 'dup_of' in ctx['columns']:
        cursor.execute(Q.FIND_DUPLICATE_ATTENDANCE, (eb_id, att_date, att_type, shift_id))
        existing = cursor.fetchone()
        if existing:
            existing_time = existing['entry_time'] if isinstance(existing, dict) else existing[1]
            existing_id = existing['daily_atten_id'] if isinstance(existing, dict) else existing[0]
            if existing_time and existing_time <= ctx['punch_time']:
                ctx['dup_of'] = existing_id          # ours is the later one
            else:
                ctx['supersedes'] = existing_id      # ours is earlier

    # An on-device match is the weaker engine, so it is never final: re-run dlib
    # on the capture and record the verdict for HR to review in the web ERP.
    face_image_b64 = data.get('face_image_b64')
    if data.get('matched_offline') and face_image_b64:
        store_offline_photo(face_image_b64)
        ctx['face_verify_status'] = reverify_offline_face(face_image_b64, eb_id)
        if ctx['face_verify_status'] in ('MISMATCH', 'NO_FACE'):
            ctx['needs_review'] = 1
    return ctx


def _apply_offline_columns(cursor, attendance_id, ctx):
    """Write the offline bookkeeping onto the row we just inserted.

    Done as an UPDATE rather than widening the INSERT so the column list stays
    valid on a tenant that has not run the migration.
    """
    if not ctx['queued'] or not ctx['columns']:
        return
    values = {
        'client_uuid': ctx['client_uuid'],
        'entry_source_time': ctx['entry_time'],
        'sync_received_time': datetime.now(),
        'clock_skew_secs': ctx['clock_skew_secs'],
        'face_verify_status': ctx['face_verify_status'],
        'match_confidence': ctx['match_confidence'],
        'needs_review': ctx['needs_review'],
        'dup_of': ctx['dup_of'],
    }
    usable = [(c, v) for c, v in values.items() if c in ctx['columns']]
    if not usable:
        return
    sets = ', '.join(f"{c} = %s" for c, _ in usable)
    try:
        cursor.execute(f"UPDATE daily_attendance SET {sets} WHERE daily_atten_id = %s",
                       tuple(v for _, v in usable) + (attendance_id,))
    except Exception as e:
        print(f"⚠️  offline columns not written: {e}")


def _supersede(cursor, older_id, winner_id):
    """Retire a row our earlier offline punch beat."""
    try:
        cursor.execute(
            "UPDATE daily_attendance SET is_active = 0, dup_of = %s, update_date_time = NOW() "
            "WHERE daily_atten_id = %s", (winner_id, older_id))
    except Exception as e:
        print(f"⚠️  could not supersede duplicate {older_id}: {e}")


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
        # Attendance source: live face-validation (4th button) sends status="Face";
        # plain manual entry sends "Manual" (default). Stored as one-letter
        # codes: F = face, A = manual.
        att_source = data.get('status') or data.get('attendance_source') or 'Manual'
        att_source = 'F' if att_source == 'Face' else 'A'

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
            # GET_EMPLOYEE_WITH_DETAILS is JOINED-only (status 35). Say why when the
            # code exists in another HR status, so the operator / Sync Center row is
            # actionable instead of "not found".
            from src.mobileapp.src.onboarding.query import GET_EMPLOYEE_STATUS_ANY
            cursor.execute(GET_EMPLOYEE_STATUS_ANY, (emp_code, branch_id, branch_id))
            other = cursor.fetchone()
            cursor.close(); db.close()
            if other:
                return jsonify({"status": "error", "message":
                    f"Employee {emp_code} ({other['name']}) is in HR status "
                    f"{other['status_name'] or 'UNKNOWN'} - not eligible for attendance. "
                    f"Update the employee's status to JOINED in HR first."}), 403
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
        geo_location   = data.get('get_location') or None  # "latitude,longitude" or None

        # Spell working-hours cap from spell_mst (shift_id IS the spell_id)
        spell_cap = None  # spell_mst.working_hours — cap for the date+spell total
        if shift_id:
            cursor.execute("SELECT working_hours FROM spell_mst WHERE spell_id = %s", (shift_id,))
            spell_row = cursor.fetchone()
            spell_cap = spell_row['working_hours'] if spell_row else None

        print(f"[MANUAL-ATT] eb_id={eb_id} emp_code={emp_code} src={att_source} att_type={att_type} "
              f"date={att_date} dept={department_id} shift={shift_id} desig={designation_id} "
              f"hrs={shift_hours}/{working_hours}/{idle_hours} geo={geo_location}")

        conflict = (_leave_conflict(cursor, eb_id, att_date, att_type)
                    or _spell_hours_conflict(cursor, eb_id, att_date, shift_id,
                                             spell_cap or shift_hours,
                                             working_hours, idle_hours))
        if conflict:
            cursor.close(); db.close()
            return jsonify({"status": "error", "message": conflict}), 400

        # ── Offline replay handling ──────────────────────────────
        # Only records the app queued offline take this path. A live submit is
        # unchanged: it still gets its timestamp from the server clock and skips
        # the cross-device duplicate check, which some workflows rely on.
        offline = _offline_context(data, cursor, eb_id, att_date, att_type, shift_id)
        # attendance_source stays 'F'/'A' as today — reports filter on those two
        # codes, so an offline punch must not invent a third. Its offline-ness is
        # recorded in entry_source_time / face_verify_status instead.
        offline['source'] = att_source

        if offline['queued']:
            cursor.execute(Q.INSERT_ATTENDANCE_AT,
                         (eb_id, att_date,
                          offline['source'], att_type,
                          'P', 0 if offline['dup_of'] else 1, branch_id,
                          shift_id, shift_hours, department_id, designation_id,
                          working_hours, idle_hours, geo_location,
                          offline['punch_time']))
        else:
            cursor.execute(Q.INSERT_ATTENDANCE,
                         (eb_id, att_date,
                          offline['source'], att_type,
                          'P', branch_id,
                          shift_id, shift_hours, department_id, designation_id,
                          working_hours, idle_hours, geo_location))

        # Get the inserted attendance ID
        attendance_id = cursor.lastrowid

        _apply_offline_columns(cursor, attendance_id, offline)

        # Our punch was the earlier one — retire the row that beat us here.
        if offline['supersedes']:
            _supersede(cursor, offline['supersedes'], attendance_id)

        # Save machine data to daily_ebmc_attendance if machines are provided.
        # Skipped for a duplicate: the winning row already carries them.
        machine_ids = data.get('machine_ids', [])
        if machine_ids and isinstance(machine_ids, list) and not offline['dup_of']:
            for machine_id in machine_ids:
                cursor.execute(Q.INSERT_MACHINE_ATTENDANCE,
                             (attendance_id, eb_id, machine_id, shift_id, branch_id))

        db.commit()
        cursor.close()
        db.close()

        message = f"Attendance marked for {name} (Manual)"
        if offline['dup_of']:
            message = (f"{name} already marked from another device — "
                       f"kept the earlier punch")

        return jsonify({
            "status":    "success",
            "id":        attendance_id,
            "emp_code":  emp_code,
            "emp_name":  name,
            "status_id": "3",
            "is_active": 0 if offline['dup_of'] else 1,
            "duplicate_of": offline['dup_of'],
            "face_verify_status": offline['face_verify_status'],
            "needs_review": bool(offline['needs_review']),
            "message":   message
        })
    except Exception as e:
        print(f"❌ Manual attendance error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Leave status (vw_leave_dates) ────────────────────────────
@attendance_bp.route('/attendance_leave_status', methods=['GET'])
def attendance_leave_status():
    """Is the employee on leave on the given date? Drives the app entry
    form's leave check. Returns on_leave + payable ('Y'/'N')."""
    try:
        eb_id    = request.args.get('eb_id')
        att_date = request.args.get('attendance_date')
        if not eb_id or not att_date:
            return jsonify({"data": {"on_leave": False, "payable": None}})
        db     = get_db()
        cursor = db.cursor(dictionary=True)
        payable = _leave_payable(cursor, int(eb_id), att_date)
        cursor.close(); db.close()
        return jsonify({"data": {"on_leave": payable is not None, "payable": payable}})
    except Exception as e:
        print(f"❌ Leave status error: {str(e)}")
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

        #print(f"📥 Check-face POST: image={len(data.get('image', ''))} chars")

        img_rgb        = decode_image(data['image'])
        live_encodings = _encode_live_face(img_rgb)

        if not live_encodings:
            return jsonify({"status": "error",
                            "message": "No face detected in image!"}), 400

        live_enc = live_encodings[0]

        # Scope face matching to the selected branch only.
        req_branch_id = data.get('branch_id')
        stored_encs, employees = face_cache.load(req_branch_id)
        if stored_encs.shape[0] == 0:
            return jsonify({"status": "error",
                            "message": "No employees with face registered for this branch!"}), 404

        emp, best_dist = _match_face(stored_encs, employees, live_enc)
        if emp is None:
            return jsonify({"status": "not_recognized",
                            "message": "Face not recognized!"}), 401

        name           = emp['name'].strip()
        photo_html_val = face_cache.get_photo_html(emp['eb_id'])
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

        # Support BOTH single date and date range
        attendance_date = request.args.get('date')
        from_date       = request.args.get('from_date')
        to_date         = request.args.get('to_date')
        department_id   = request.args.get('department_id')
        emp_code        = request.args.get('emp_code', '').strip()
        emp_name        = request.args.get('emp_name', '').strip()
        shift_name      = request.args.get('shift_name', '').strip()
        spell_id        = request.args.get('spell_id', type=int)
        branch_id       = request.args.get('branch_id', type=int)
        designation_id  = request.args.get('designation_id', type=int)
        att_type        = request.args.get('att_type', '').strip()

        # Determine which query mode
        if attendance_date:
            # Single date mode
            date_condition = "da.attendance_date = %s"
            leave_date_condition = "v.leave_date = %s"
            date_params = [attendance_date]
        elif from_date and to_date:
            # Date range mode
            date_condition = "da.attendance_date BETWEEN %s AND %s"
            leave_date_condition = "v.leave_date BETWEEN %s AND %s"
            date_params = [from_date, to_date]
        else:
            return jsonify({'status': 'error', 'message': 'Either date or from_date/to_date is required'}), 400

        db     = get_db()
        cursor = db.cursor(dictionary=True)

        # Build dynamic SQL query
        sql = f"""
            SELECT da.daily_atten_id AS id, o.emp_code, o.eb_id,
                   CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ', COALESCE(p.last_name, '')) AS emp_name,
                   COALESCE(s.sub_dept_desc, '') AS department_name,
                   COALESCE(d.desig, '')         AS designation_name,
                   COALESCE(sm.spell_name, da.spell, '') AS shift_name,
                   da.spell_id                   AS shift_id,
                   da.attendance_date,
                   TIME(da.entry_time)           AS attendance_time,
				   time(da.exit_time )	         as exit_time,
                   da.attendance_source          AS status,
                   COALESCE(da.attendance_type, 'R') AS att_type,
                   COALESCE(da.spell_hours,   0) AS shift_hours,
                   COALESCE(da.working_hours, 0) AS working_hours,
                   COALESCE(da.idle_hours,    0) AS idle_hours,
                   COALESCE(da.remarks, '')      AS remarks,
                   IF(EXISTS(
                     SELECT 1
                     FROM employee_face_mst ef
                     WHERE ef.eb_id = da.eb_id AND ef.active = 1
                   ), 1, 0) AS has_photo
            FROM daily_attendance da
            LEFT JOIN hrms_ed_personal_details p ON da.eb_id = p.eb_id
            LEFT JOIN hrms_ed_official_details o ON da.eb_id = o.eb_id and o.active=1
            LEFT JOIN sub_dept_mst    s ON da.worked_department_id     = s.sub_dept_id
            LEFT JOIN designation_mst d ON da.worked_designation_id = d.designation_id
            LEFT JOIN spell_mst      sm ON sm.spell_id = da.spell_id
            WHERE {date_condition} AND da.is_active = 1
              -- Drop rejected (4) and cancelled (6) ATTENDANCE rows -- this is
              -- da.status_id, not the employee's. COALESCE keeps rows with a
              -- NULL status (legacy / bio-imported), which are still real.
              -- p.active = 1 also drops attendance rows whose employee record
              -- is missing entirely (NULL = 1 is false), which is the intent --
              -- those are orphaned rows, not people.
              -- NOTE: o.active = 1 stays in the JOIN above on purpose. It picks
              -- the current official-details row among an employee's history;
              -- moving it here would change the join, not add a filter.
              AND p.active = 1
              AND COALESCE(CAST(da.status_id AS UNSIGNED), 0) NOT IN (4, 6)
        """
        # Copy, don't alias: the leave UNION below re-uses date_params, and every
        # filter here appends to params. Sharing one list would feed the whole
        # accumulated filter set back in as the leave query's date arguments.
        params = list(date_params)

        # Add filters
        if branch_id:
            sql += " AND da.branch_id = %s"
            params.append(branch_id)
        
        if department_id:
            # match all sibling ids sharing the same name (dropdowns are deduped by name)
            sql += """ AND da.worked_department_id IN (
                SELECT s2.sub_dept_id FROM sub_dept_mst s1
                JOIN sub_dept_mst s2 ON s2.sub_dept_desc = s1.sub_dept_desc
                WHERE s1.sub_dept_id = %s)"""
            params.append(department_id)
        
        if emp_code:
            # Exact match, not LIKE %..% — an EB No is an identifier, and the
            # substring search meant typing "EJCL" returned 294 employees.
            # TRIM because the column is utf8mb4_0900_ai_ci (NO PAD), so stored
            # values with trailing spaces — there are a few — would never equal
            # the stripped input. emp_code carries no index, so TRIM costs
            # nothing here. The collation is already case/accent-insensitive.
            # emp_name below stays a substring search; that one is a name lookup.
            sql += " AND TRIM(o.emp_code) = %s"
            params.append(emp_code)
        
        if emp_name:
            sql += " AND (p.first_name LIKE %s OR p.middle_name LIKE %s OR p.last_name LIKE %s)"
            params.extend([f"%{emp_name}%", f"%{emp_name}%", f"%{emp_name}%"])
        
        if spell_id:
            sql += """ AND da.spell_id IN (
                SELECT p2.spell_id FROM spell_mst p1
                JOIN spell_mst p2 ON p2.spell_name = p1.spell_name
                WHERE p1.spell_id = %s)"""
            params.append(spell_id)
        elif shift_name and shift_name != 'All Shifts':
            sql += " AND COALESCE(sm.spell_name, da.spell) = %s"
            params.append(shift_name)

        if designation_id:
            sql += """ AND da.worked_designation_id IN (
                SELECT d2.designation_id FROM designation_mst d1
                JOIN designation_mst d2 ON d2.desig = d1.desig
                WHERE d1.designation_id = %s)"""
            params.append(designation_id)

        if att_type:
            sql += " AND da.attendance_type = %s"
            params.append(att_type)

        # ── Approved leave, unioned in ────────────────────────────
        # Leave has no daily_attendance row, so a worker's leave days are
        # otherwise invisible next to their punches. Gated on emp_code: without
        # that filter this would add every approved leave for every employee in
        # the range and swamp the report — hence "when EB No is there, else the
        # current query". vw_leave_dates already expands each transaction into
        # one row per date and filters to approved (status = '3').
        #
        # Department and designation come from the employee master (o.*), not
        # from da.worked_* — a leave day has no worked department.
        #
        # Column ORDER here must match the SELECT above exactly; UNION binds by
        # position, not by name.
        # att_type in the guard, not the WHERE: filtering the report to R/O/C
        # means the caller does not want leave rows at all, so skip the union
        # rather than bolting on a condition that is always true or always false.
        if emp_code and att_type.upper() in ('', 'L'):
            sql += f"""
            UNION ALL
            SELECT 0                      AS id,     -- not an editable attendance row
                   o.emp_code, o.eb_id,
                   CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ', COALESCE(p.last_name, '')) AS emp_name,
                   COALESCE(ms.sub_dept_desc, '')        AS department_name,
                   COALESCE(md.desig, '')                AS designation_name,
                   ''                     AS shift_name,
                   NULL                   AS shift_id,
                   v.leave_date           AS attendance_date,
                   NULL                   AS attendance_time,
                   NULL                   AS exit_time,
                   COALESCE(v.leave_type_code, '')       AS status,
                   'L'                    AS att_type,
                   8                      AS shift_hours,
                   8                      AS working_hours,
                   0                      AS idle_hours,
                   COALESCE(v.leave_type_description, '') AS remarks,
                   0                      AS has_photo
            FROM vw_leave_dates v
            JOIN hrms_ed_official_details o ON o.eb_id = v.eb_id AND o.active = 1
            JOIN hrms_ed_personal_details p ON p.eb_id = v.eb_id
            LEFT JOIN sub_dept_mst    ms ON o.sub_dept_id    = ms.sub_dept_id
            LEFT JOIN designation_mst md ON o.designation_id = md.designation_id
            WHERE {leave_date_condition}
              AND p.active = 1
              AND TRIM(o.emp_code) = %s
              -- No status_id filter here on purpose: 4/6 are rejected/cancelled
              -- ATTENDANCE states and a leave day has none. vw_leave_dates is
              -- already scoped to approved transactions (status = '3').
            """
            params.extend(date_params)
            params.append(emp_code)
            if branch_id:
                sql += " AND v.branch_id = %s"
                params.append(branch_id)

        # Ordered by output alias, not da.* — with the UNION above there is no
        # single `da` to sort on.
        sql += " ORDER BY attendance_date DESC, attendance_time DESC"
        print("Executing attendance report SQL:", sql)
        print("With parameters:", params)
        
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()

        # Machine numbers for every row, batched. This used to be one query per
        # row, which costs ~0.5s each against a remote DB — a single shift
        # (343 rows) took ~190s, long enough for the proxy in front of us to give
        # up and hand the browser a 500. Chunked so a wide date range cannot
        # exceed max_allowed_packet.
        machines = {}
        # Leave rows carry id = 0 and have no machines — skip them so the IN
        # list stays the size of the real attendance rows.
        ids = [row['id'] for row in rows if row['id']]
        for start in range(0, len(ids), 1000):
            chunk = ids[start:start + 1000]
            placeholders = ','.join(['%s'] * len(chunk))
            cursor.execute(f"""
                SELECT dea.daily_atten_id, mm.mech_code
                FROM daily_ebmc_attendance dea
                JOIN machine_mst mm ON dea.mc_id = mm.machine_id
                WHERE dea.daily_atten_id IN ({placeholders}) AND dea.is_active = 1
                ORDER BY dea.daily_atten_id, mm.mech_code
            """, tuple(chunk))
            for m in cursor.fetchall():
                if m['mech_code']:
                    machines.setdefault(m['daily_atten_id'], []).append(m['mech_code'])

        # Build response with machine numbers
        data = []
        for row in rows:
            machine_nos = ', '.join(machines.get(row['id'], []))

            data.append({
                'id':               row['id'],
                'emp_code':         row['emp_code'],
                'eb_id':            row['eb_id'],
                'emp_name':         row['emp_name'] or '',
                'department_name':  row['department_name'] or '',
                'designation_name': row['designation_name'] or '',
                'shift_name':       row['shift_name'] or '',
                'shift_id':         row['shift_id'],
                'attendance_date':  str(row['attendance_date']),
                # Same None-guard as exit_time below: leave rows have no punch
                # time, and str(None) would ship the literal text "None".
                'attendance_time':  ('' if row.get('attendance_time') in (None, '') else str(row['attendance_time'])),
                'exit_time':        ('' if row.get('exit_time') in (None, '') else str(row['exit_time'])),
                'status':           row['status'] or '',
                'att_type':         row['att_type'] or 'R',
                'shift_hours':      float(row['shift_hours']),
                'working_hours':    float(row['working_hours']),
                'idle_hours':       float(row['idle_hours']),
                'has_photo':        bool(row['has_photo']),
                'machine_nos':      machine_nos,
                'remarks':          row['remarks'] or ''
            })

        cursor.close()
        db.close()

        return jsonify({'status': 'success', 'data': data, 'total': len(data)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


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

        photo_b64 = _photo_b64(row['photo_att'])
        if not photo_b64:
            return jsonify({'status': 'error', 'message': 'No photo'}), 404

        return jsonify({'status': 'success', 'photo_att': photo_b64})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@attendance_bp.route('/employee-face/<int:eb_id>', methods=['GET'])
def employee_face(eb_id):
    """Registered face for one employee, by eb_id.

    /employee/<emp_code> also returns this photo, but alongside last-worked
    department and machine lookups that exist to pre-fill the attendance ENTRY
    form. Measured against this database those add ~1.3 s, which a read-only
    view pays for nothing. This is the single indexed lookup on its own —
    ~33 ms."""
    try:
        photo_b64 = _photo_b64(face_cache.get_photo_html(eb_id))
        if not photo_b64:
            return jsonify({'status': 'error', 'message': 'No photo'}), 404
        return jsonify({'status': 'success', 'photo_att': photo_b64})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# -- Update Attendance (Edit Attendance dialog) --------------------------
# Updates an existing daily_attendance row and re-syncs daily_ebmc_attendance
# (marks all existing machine rows as is_active=0, then inserts new machines).
# ── Employee-wise Attendance Report ─────────────────────────────────────
@attendance_bp.route('/emp-wise-attendance', methods=['GET'])
def emp_wise_attendance():
    try:
        from collections import defaultdict
        from datetime import date as date_cls, timedelta

        from_date      = request.args.get('from_date')
        to_date        = request.args.get('to_date')
        spell_id       = request.args.get('spell_id',       type=int)
        dept_id        = request.args.get('dept_id',        type=int)
        designation_id = request.args.get('designation_id', type=int)
        att_type       = request.args.get('att_type', '').strip()
        report_type    = request.args.get('report_type', 'date_wise').strip()
        branch_id      = request.args.get('branch_id',      type=int)

        if not from_date or not to_date:
            return jsonify({'status': 'error', 'message': 'from_date and to_date are required'}), 400

        db     = get_db()
        cursor = db.cursor(dictionary=True)

        spell_name_filter = None
        if spell_id:
            cursor.execute("SELECT spell_name FROM spell_mst WHERE spell_id = %s", (spell_id,))
            row = cursor.fetchone()
            spell_name_filter = row['spell_name'] if row else None

        fd = datetime.strptime(from_date, '%Y-%m-%d').date()
        td = datetime.strptime(to_date,   '%Y-%m-%d').date()

        if report_type == 'monthly':
            periods = []
            cur_d = date_cls(fd.year, fd.month, 1)
            while cur_d <= td:
                next_month = date_cls(cur_d.year + (cur_d.month // 12),
                                      (cur_d.month % 12) + 1, 1) if cur_d.month < 12 \
                             else date_cls(cur_d.year + 1, 1, 1)
                periods.append({'label': cur_d.strftime('%b-%Y'),
                                 'from': cur_d.strftime('%Y-%m-%d'),
                                 'to': (next_month - timedelta(days=1)).strftime('%Y-%m-%d')})
                cur_d = next_month
        elif report_type == 'fn_wise':
            try:
                cursor.execute("""
                    SELECT fne_name,
                           DATE_FORMAT(from_date, '%%Y-%%m-%%d') AS `from`,
                           DATE_FORMAT(to_date,   '%%Y-%%m-%%d') AS `to`
                    FROM fne_master
                    WHERE to_date >= %s AND from_date <= %s
                    ORDER BY from_date
                """, (from_date, to_date))
                fne_rows = cursor.fetchall()
            except Exception:
                fne_rows = []
            if fne_rows:
                periods = [{'label': r['fne_name'], 'from': r['from'], 'to': r['to']} for r in fne_rows]
            else:
                periods = []
                cur_d = fd
                while cur_d <= td:
                    end_d = min(cur_d + timedelta(days=14), td)
                    periods.append({'label': cur_d.strftime('%d-%b') + ' to ' + end_d.strftime('%d-%b'),
                                    'from': cur_d.strftime('%Y-%m-%d'), 'to': end_d.strftime('%Y-%m-%d')})
                    cur_d = end_d + timedelta(days=1)
        else:  # date_wise
            periods = []
            cur_d = fd
            while cur_d <= td:
                periods.append({'label': cur_d.strftime('%d-%b'),
                                 'from': cur_d.strftime('%Y-%m-%d'),
                                 'to':   cur_d.strftime('%Y-%m-%d')})
                cur_d += timedelta(days=1)

        # ── Rows: one per (employee, worked dept, shift, designation, type) ──
        # The old report emitted one row per employee holding summed hours. This
        # emits a muster line per distinct working context, because an employee
        # can work different departments / shifts / designations inside the same
        # range and merging those into one figure hides it.
        #
        # A cell is a DAY COUNT, not hours: 1 for a day with any record in that
        # context, and a leave day counts 1 the same way. For monthly / fn_wise
        # report types the cell is the number of such days inside the period.
        att_sql = """
            SELECT da.eb_id,
                   DATE_FORMAT(da.attendance_date, '%Y-%m-%d')     AS att_date,
                   COALESCE(s.sub_dept_desc, '')                   AS dept_name,
                   COALESCE(sh.shift_name, da.spell, '')           AS shift_name,
                   COALESCE(d.desig, '')                           AS desig_name,
                   COALESCE(da.attendance_type, 'R')               AS att_type
            FROM daily_attendance da
            LEFT JOIN sub_dept_mst    s  ON da.worked_department_id  = s.sub_dept_id
            LEFT JOIN designation_mst d  ON da.worked_designation_id = d.designation_id
            -- Shift, not spell: A1 and A2 are spells of shift A (spell_mst.shift_id
            -- -> shift_mst). Grouping on the shift also stops a split shift being
            -- counted as two days — both spells collapse into one row per date.
            LEFT JOIN spell_mst      sm  ON sm.spell_id = da.spell_id
            LEFT JOIN shift_mst      sh  ON sh.shift_id = sm.shift_id
            WHERE da.attendance_date BETWEEN %s AND %s
              AND da.is_active = 1
              AND COALESCE(CAST(da.status_id AS UNSIGNED), 0) NOT IN (4, 6)
        """
        att_params = [from_date, to_date]
        if branch_id:
            att_sql += " AND da.branch_id = %s"
            att_params.append(branch_id)
        if spell_id:
            att_sql += " AND (da.spell_id = %s OR da.spell = %s)"
            att_params.extend([spell_id, spell_name_filter])
        if att_type:
            att_sql += " AND da.attendance_type = %s"
            att_params.append(att_type)
        if dept_id:
            att_sql += " AND da.worked_department_id = %s"
            att_params.append(dept_id)
        if designation_id:
            att_sql += " AND da.worked_designation_id = %s"
            att_params.append(designation_id)
        # Group on the shift expression, not the `shift_name` alias: that alias
        # now collides with the real shift_mst.shift_name column, so MySQL binds
        # it to the column and only_full_group_by then rejects the da.spell
        # fallback inside the COALESCE.
        att_sql += (" GROUP BY da.eb_id, att_date, dept_name,"
                    " COALESCE(sh.shift_name, da.spell, ''), desig_name, att_type")

        cursor.execute(att_sql, tuple(att_params))
        att_rows = cursor.fetchall()

        # Leave days, as type L. Department / designation come from the employee
        # master (a leave day has no worked department) and the shift is blank.
        # vw_leave_dates is already one row per date, approved transactions only.
        if not att_type or att_type.strip().upper() == 'L':
            leave_sql = """
                SELECT v.eb_id,
                       DATE_FORMAT(v.leave_date, '%Y-%m-%d')  AS att_date,
                       COALESCE(ms.sub_dept_desc, '')         AS dept_name,
                       ''                                     AS shift_name,
                       COALESCE(md.desig, '')                 AS desig_name,
                       'L'                                    AS att_type
                FROM vw_leave_dates v
                JOIN hrms_ed_official_details o ON o.eb_id = v.eb_id AND o.active = 1
                LEFT JOIN sub_dept_mst    ms ON o.sub_dept_id    = ms.sub_dept_id
                LEFT JOIN designation_mst md ON o.designation_id = md.designation_id
                WHERE v.leave_date BETWEEN %s AND %s
            """
            leave_params = [from_date, to_date]
            if branch_id:
                leave_sql += " AND v.branch_id = %s"
                leave_params.append(branch_id)
            if dept_id:
                leave_sql += " AND o.sub_dept_id = %s"
                leave_params.append(dept_id)
            if designation_id:
                leave_sql += " AND o.designation_id = %s"
                leave_params.append(designation_id)
            leave_sql += " GROUP BY v.eb_id, att_date, dept_name, desig_name"
            cursor.execute(leave_sql, tuple(leave_params))
            att_rows.extend(cursor.fetchall())

        # Identity only for people who actually appear — an employee with nothing
        # in the range is omitted rather than carried as an empty line.
        eb_ids = sorted({r['eb_id'] for r in att_rows})
        emp_meta = {}
        for chunk_start in range(0, len(eb_ids), 1000):
            chunk = eb_ids[chunk_start:chunk_start + 1000]
            placeholders = ','.join(['%s'] * len(chunk))
            cursor.execute(f"""
                SELECT o.eb_id,
                       COALESCE(o.emp_code, '') AS emp_code,
                       TRIM(CONCAT(COALESCE(p.first_name,''), ' ',
                                   COALESCE(p.middle_name,''), ' ',
                                   COALESCE(p.last_name,''))) AS emp_name
                FROM hrms_ed_official_details o
                LEFT JOIN hrms_ed_personal_details p ON o.eb_id = p.eb_id
                WHERE o.eb_id IN ({placeholders}) AND o.active = 1
            """, tuple(chunk))
            for m in cursor.fetchall():
                emp_meta.setdefault(m['eb_id'], m)

        cursor.close()
        db.close()

        # date -> period label, so each row buckets with one dict hit instead of
        # rescanning the period list.
        day_period = {}
        for period in periods:
            pf = datetime.strptime(period['from'], '%Y-%m-%d').date()
            pt = datetime.strptime(period['to'],   '%Y-%m-%d').date()
            d = pf
            while d <= pt:
                day_period[d.strftime('%Y-%m-%d')] = period['label']
                d += timedelta(days=1)

        labels = [p['label'] for p in periods]
        TYPES  = ('R', 'O', 'C', 'L', 'H')

        # (eb_id, dept, shift, desig, type) -> {period label: day count}
        groups = defaultdict(lambda: defaultdict(int))
        for r in att_rows:
            label = day_period.get(r['att_date'])
            if label is None:
                continue
            t = (r['att_type'] or 'R').strip().upper()
            if t not in TYPES:
                t = 'R'
            key = (r['eb_id'], r['dept_name'] or '', r['shift_name'] or '',
                   r['desig_name'] or '', t)
            groups[key][label] += 1

        def _zero_totals():
            return {'tot_' + t.lower(): 0 for t in TYPES}

        def _make_row(meta, dept, shift, desig, t, counts):
            row = {
                'emp_code':    meta.get('emp_code', ''),
                'emp_name':    meta.get('emp_name', ''),
                'dept':        dept,
                'shift':       shift,
                'designation': desig,
                'att_type':    t,
                'attendance':  {lb: (counts.get(lb) or '') for lb in labels},
                'is_subtotal': False,
                'tot_all':     sum(counts.values()),
            }
            row.update(_zero_totals())
            row['tot_' + t.lower()] = sum(counts.values())
            return row

        result_rows = []
        by_emp = defaultdict(list)
        for key in groups:
            by_emp[key[0]].append(key)

        for eb_id in sorted(by_emp, key=lambda e: emp_meta.get(e, {}).get('emp_code', '')):
            meta = emp_meta.get(eb_id, {})
            keys = sorted(by_emp[eb_id], key=lambda k: (k[1], k[2], k[3], k[4]))
            emp_rows = [_make_row(meta, k[1], k[2], k[3], k[4], groups[k]) for k in keys]
            result_rows.extend(emp_rows)

            # A subtotal only earns its line when the employee spans more than
            # one context; otherwise it would just repeat the row above it.
            if len(emp_rows) > 1:
                merged = defaultdict(int)
                sub = {'emp_code': meta.get('emp_code', ''),
                       'emp_name': meta.get('emp_name', ''),
                       'dept': '', 'shift': '', 'designation': '',
                       'att_type': 'TOTAL', 'is_subtotal': True}
                sub.update(_zero_totals())
                for er in emp_rows:
                    for lb in labels:
                        v = er['attendance'][lb]
                        if v != '':
                            merged[lb] += v
                    for t in TYPES:
                        sub['tot_' + t.lower()] += er['tot_' + t.lower()]
                sub['attendance'] = {lb: (merged.get(lb) or '') for lb in labels}
                sub['tot_all'] = sum(merged.values())
                result_rows.append(sub)

        return jsonify({
            'status':          'success',
            'report_type':     report_type,
            'from_date':       from_date,
            'to_date':         to_date,
            'columns':         labels,
            'total_types':     list(TYPES),
            # H stays 0: this tenant has no holiday calendar. src/hrms/
            # reportQueries.py reached the same conclusion. Fill it here if one
            # is ever added.
            'total_employees': len(by_emp),
            'employees':       result_rows,
        })
    except Exception as e:
        print(f'[EMP-WISE-ATT] error: {str(e)}')
        return jsonify({'status': 'error', 'message': str(e)}), 500


@attendance_bp.route('/attendance/<int:atten_id>', methods=['PUT'])
def update_attendance(atten_id):
    try:
        data = request.json or {}
        att_type        = (data.get('attendance_type') or data.get('att_type') or 'R')
        department_id   = data.get('department_id')
        designation_id  = data.get('designation_id')
        working_hours   = data.get('working_hours', 0) or 0
        idle_hours      = data.get('idle_hours', 0) or 0
        machine_ids     = data.get('machine_ids') or []
        db     = get_db()
        cursor = db.cursor(dictionary=True)
        # Fetch eb_id (needed to insert into daily_ebmc_attendance)
        cursor.execute(Q.GET_ATTENDANCE_EB_ID, (atten_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close(); db.close()
            return jsonify({'status': 'error',
                            'message': f'Attendance id {atten_id} not found'}), 404
        eb_id = row['eb_id']
        # Shift can be changed from the edit dialog; falls back to the stored one.
        new_shift_id    = data.get('shift_id') or row['spell_id']
        new_shift_hours = data.get('shift_hours')
        spell_cap       = row['spell_hours']
        if data.get('shift_id'):
            cursor.execute("SELECT working_hours FROM spell_mst WHERE spell_id = %s",
                           (data['shift_id'],))
            sp = cursor.fetchone()
            if sp:
                spell_cap = sp['working_hours']
                if new_shift_hours is None:
                    new_shift_hours = sp['working_hours']
        # Editing hours can also breach the date+spell cap — same rule as entry,
        # excluding this row's own saved hours from the "already worked" sum.
        conflict = _spell_hours_conflict(cursor, eb_id, row['attendance_date'],
                                         new_shift_id, spell_cap,
                                         working_hours, idle_hours,
                                         exclude_atten_id=atten_id)
        if conflict:
            cursor.close(); db.close()
            return jsonify({'status': 'error', 'message': conflict}), 400
        # 1) Update the attendance row
        cursor.execute(Q.UPDATE_ATTENDANCE,
                       (att_type, department_id, designation_id,
                        working_hours, idle_hours,
                        data.get('shift_id'), new_shift_hours, atten_id))
        # 2) Mark existing machine rows for this attendance as inactive
        cursor.execute(Q.DEACTIVATE_MACHINE_ATTENDANCE, (atten_id,))
        # 3) Insert new active machine rows
        if isinstance(machine_ids, list):
            for mc_id in machine_ids:
                try:
                    mc_id_int = int(mc_id)
                except (TypeError, ValueError):
                    continue
                if mc_id_int <= 0:
                    continue
                cursor.execute(Q.INSERT_MACHINE_ATTENDANCE,
                               (atten_id, eb_id, mc_id_int,
                                new_shift_id, row['branch_id']))
        db.commit()
        cursor.close()
        db.close()
        print(f'[ATT-UPDATE] id={atten_id} type={att_type} dept={department_id} '
              f'desig={designation_id} wh={working_hours} ih={idle_hours} '
              f'machines={machine_ids}')
        return jsonify({
            'status':         'success',
            'message':        'Attendance updated',
            'attendance_id':  atten_id,
            'machines_saved': len([m for m in (machine_ids or []) if m])
        })
    except Exception as e:
        print(f'X Update attendance error: {str(e)}')
        return jsonify({'status': 'error', 'message': str(e)}), 500
