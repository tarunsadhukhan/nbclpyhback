"""
OnBoarding Blueprint - Face Registration for Employees
Allows registering up to 3 face photos per employee (by emp_code)
"""

import json
import base64
import traceback

try:
    import face_recognition
except ImportError:
    face_recognition = None

from flask import Blueprint, request, jsonify
from src.mobileapp.db import get_db
from src.mobileapp.src.onboarding import query as Q

onboarding_bp = Blueprint('onboarding', __name__)


# Maximum dimension (px) and JPEG quality used to shrink face photos
# before persisting them, so we stay well under MySQL max_allowed_packet.
_MAX_IMAGE_DIM = 800
_JPEG_QUALITY = 75


def _shrink_image(image_bytes):
    """
    Downscale + re-encode the input image as JPEG so the stored row
    is small enough for MySQL's max_allowed_packet.

    Returns (compressed_bytes, base64_str). Falls back to the original
    bytes if PIL is unavailable or anything goes wrong.
    """
    try:
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(image_bytes))
        # JPEG cannot store alpha channel
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        w, h = img.size
        scale = min(1.0, float(_MAX_IMAGE_DIM) / float(max(w, h)))
        if scale < 1.0:
            new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            img = img.resize(new_size, Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=_JPEG_QUALITY, optimize=True)
        compressed = buf.getvalue()
        return compressed, base64.b64encode(compressed).decode('ascii')
    except Exception as e:
        print(f"[onboarding] _shrink_image fallback: {e}")
        return image_bytes, base64.b64encode(image_bytes).decode('ascii')


def _generate_face_embedding(image_bytes):
    """
    Generate 128-d face embedding from image bytes.
    Returns embedding list or None if no face detected.
    """
    if face_recognition is None:
        return None
    
    try:
        import numpy as np
        from PIL import Image
        import io
        
        # Load image from bytes
        image = Image.open(io.BytesIO(image_bytes))
        image_np = np.array(image)
        
        # Get face encodings
        face_encodings = face_recognition.face_encodings(image_np)
        
        if len(face_encodings) == 0:
            return None
        
        # Return first face encoding as list
        return face_encodings[0].tolist()
    except Exception as e:
        print(f"Error generating face embedding: {e}")
        return None


# ══════════════════════════════════════════════════════════════════
# GET Employee by emp_code
# ══════════════════════════════════════════════════════════════════

@onboarding_bp.route('/onboarding/employee/<emp_code>', methods=['GET'])
def get_employee(emp_code):
    """
    Lookup employee by emp_code.
    Returns employee details + current face count (max 3 allowed).
    emp_code must exist in hrms_ed_official_details.
    """
    try:
        # Optional branch_id filter via query string
        branch_id = request.args.get('branch_id', type=int)

        db = get_db()
        cursor = db.cursor(dictionary=True)

        # Get employee by emp_code (+ branch_id when supplied)
        if branch_id:
            print(f"[onboarding.get_employee] QUERY: {Q.GET_EMPLOYEE_BY_EMP_CODE_AND_BRANCH}")
            print(f"[onboarding.get_employee] PARAMS: emp_code={emp_code!r}, branch_id={branch_id!r}")
            cursor.execute(Q.GET_EMPLOYEE_BY_EMP_CODE_AND_BRANCH, (emp_code, branch_id))
        else:
            print(f"[onboarding.get_employee] QUERY: {Q.GET_EMPLOYEE_BY_EMP_CODE}")
            print(f"[onboarding.get_employee] PARAMS: emp_code={emp_code!r}")
            cursor.execute(Q.GET_EMPLOYEE_BY_EMP_CODE, (emp_code,))
        employee = cursor.fetchone()
        print(f"[onboarding.get_employee] ROW: {employee}")

        if not employee:
            cursor.close()
            db.close()
            scope = f' in branch {branch_id}' if branch_id else ' or not in official records'
            return jsonify({
                'status': 'error',
                'message': f'Employee with emp_code {emp_code} not found{scope}'
            }), 404
        
        eb_id = employee['eb_id']
        
        # Count existing registered faces
        cursor.execute(Q.GET_FACE_COUNT, (eb_id,))
        face_count = cursor.fetchone()['cnt']
        
        cursor.close()
        db.close()
        
        return jsonify({
            'status': 'success',
            'eb_id': eb_id,
            'emp_code': employee['emp_code'],
            'name': employee['name'].strip(),
            'department_name': employee['department_name'] or '',
            'designation_name': employee['designation_name'] or '',
            'branch_id': employee['branch_id'],
            'face_count': face_count,
            'can_register': face_count < 3
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# POST Register Face
# ══════════════════════════════════════════════════════════════════

def _has_mobile_embedding_columns(cursor):
    """Has this tenant database had migration_offline_sync.sql applied?"""
    try:
        cursor.execute(
            """SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'employee_face_mst'
                 AND COLUMN_NAME = 'face_embedding_mobile'""")
        return cursor.fetchone() is not None
    except Exception:
        return False


@onboarding_bp.route('/onboarding/register-face', methods=['POST'])
def register_face():
    """
    Register a face for an employee.
    Body: { emp_code, face_image (base64) }
    Max 3 faces allowed per employee.
    emp_code must exist in hrms_ed_official_details.
    """
    try:
        data = request.get_json(silent=True) or {}
        emp_code = data.get('emp_code')
        face_image_b64 = data.get('face_image')
        branch_id = data.get('branch_id')
        # branch_id may also arrive as a query string param (defensive)
        if branch_id is None:
            branch_id = request.args.get('branch_id', type=int)
        try:
            branch_id = int(branch_id) if branch_id not in (None, '') else None
        except (TypeError, ValueError):
            branch_id = None

        if not emp_code:
            return jsonify({'status': 'error', 'message': 'emp_code is required'}), 400
        if not face_image_b64:
            return jsonify({'status': 'error', 'message': 'face_image is required'}), 400

        # Strip optional data-URL prefix (e.g. "data:image/jpeg;base64,....") and whitespace
        if isinstance(face_image_b64, str) and face_image_b64.startswith('data:'):
            comma = face_image_b64.find(',')
            if comma != -1:
                face_image_b64 = face_image_b64[comma + 1:]
        face_image_b64 = ''.join(str(face_image_b64).split())

        db = get_db()
        cursor = db.cursor(dictionary=True)

        # Verify employee exists - lookup by emp_code (+ branch_id) in official_details
        if branch_id:
            cursor.execute(Q.GET_EMPLOYEE_BY_EMP_CODE_AND_BRANCH, (emp_code, branch_id))
        else:
            cursor.execute(Q.GET_EMPLOYEE_BY_EMP_CODE, (emp_code,))
        employee = cursor.fetchone()

        if not employee:
            cursor.close()
            db.close()
            scope = f' in branch {branch_id}' if branch_id else ''
            return jsonify({
                'status': 'error',
                'message': f'Employee with emp_code {emp_code} not found{scope}'
            }), 404

        eb_id = employee['eb_id']

        # Check face count - max 3
        cursor.execute(Q.GET_FACE_COUNT, (eb_id,))
        face_count = cursor.fetchone()['cnt']

        if face_count >= 3:
            cursor.close()
            db.close()
            return jsonify({
                'status': 'error',
                'message': f'Maximum 3 faces already registered for {employee["name"].strip()}. Cannot add more.'
            }), 400

        # Decode base64 image
        try:
            image_bytes = base64.b64decode(face_image_b64, validate=False)
        except Exception as decode_err:
            cursor.close()
            db.close()
            return jsonify({
                'status': 'error',
                'message': f'Invalid base64 image data: {decode_err}'
            }), 400

        # Shrink + re-encode so we stay under MySQL max_allowed_packet
        shrunk_bytes, shrunk_b64 = _shrink_image(image_bytes)
        print(f"[onboarding] image bytes: original={len(image_bytes)}, "
              f"shrunk={len(shrunk_bytes)}, b64_len={len(shrunk_b64)}")

        # Generate face embedding from shrunk bytes (don't 500 if lib missing/errors)
        embedding = None
        try:
            embedding = _generate_face_embedding(shrunk_bytes)
        except Exception as emb_err:
            print(f"[onboarding] embedding error: {emb_err}")
            traceback.print_exc()

        face_embedding_json = json.dumps(embedding) if embedding is not None else None

        # Only enforce face-detection check when the library IS available
        if face_recognition is not None and not face_embedding_json:
            cursor.close()
            db.close()
            return jsonify({
                'status': 'error',
                'message': 'No face detected in the image. Please try again.'
            }), 400

        # Insert new face record (store the SHRUNKEN base64, not the raw upload).
        # The device may also send the MobileFaceNet embedding it computed from
        # the same photo, so a newly onboarded worker is matchable offline
        # immediately instead of waiting for the next backfill run. Those columns
        # only exist after migration_offline_sync.sql, hence the guarded insert.
        embedding_mobile = data.get('embedding_mobile')
        mobile_model_ver = data.get('mobile_model_ver')
        if embedding_mobile and _has_mobile_embedding_columns(cursor):
            cursor.execute(Q.INSERT_FACE_WITH_MOBILE,
                           (eb_id, face_embedding_json, shrunk_b64,
                            json.dumps(embedding_mobile),
                            mobile_model_ver or 'mobilefacenet-v1'))
        else:
            cursor.execute(Q.INSERT_FACE, (eb_id, face_embedding_json, shrunk_b64))
        db.commit()

        new_face_count = face_count + 1
        cursor.close()
        db.close()

        # New embedding is now in the DB -- drop the in-memory match cache
        # so the next /check-face / /attendance reload sees it.
        try:
            from src.mobileapp.src.attendance import face_cache
            face_cache.invalidate()
        except Exception as cache_err:
            print(f"[onboarding] face_cache invalidate skipped: {cache_err}")

        return jsonify({
            'status': 'success',
            'message': f'Face registered successfully for {employee["name"].strip()} ({emp_code}) - {new_face_count}/3',
            'face_count': new_face_count,
            'can_register': new_face_count < 3
        })
    except Exception as e:
        print(f"[onboarding] register_face 500: {e}")
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500

