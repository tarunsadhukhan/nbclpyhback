import bcrypt
import mysql.connector
from flask import Blueprint, request, jsonify
from src.mobileapp.db import get_auth_db
from src.mobileapp.src.auth import query as Q
from src.mobileapp.src.schemas.user import SignupSchema, LoginSchema

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/signup', methods=['POST'])
def signup():
    try:
        data = request.json
        ok, errors = SignupSchema.validate(data)
        if not ok:
            return jsonify({"status": "error", "message": errors[0]}), 400

        email_id  = data.get('email_id', '').strip()
        name      = data.get('name', '').strip()
        password  = data.get('password', '')

        hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        db        = get_auth_db()
        cursor    = db.cursor()
        cursor.execute(Q.INSERT_USER, (email_id, name, hashed_pw))
        db.commit()
        cursor.close()
        db.close()
        return jsonify({"status": "success",
                        "message": f"User '{email_id}' created!"})
    except mysql.connector.IntegrityError:
        return jsonify({"status": "error",
                        "message": "Email already exists!"}), 409
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.json or {}

        # ── Debug: show exactly what the client sent and which DB we resolved ──
        from src.mobileapp.db import current_db_name, DB_CONFIG
        resolved_db = current_db_name(DB_CONFIG.get("database"))
        _pw = data.get('password', '')
        #print("\n=== LOGIN REQUEST ===")
        #print(f"  Host header   : {request.headers.get('Host')}")
        #print(f"  X-Tenant      : {request.headers.get('X-Tenant')}")
        #print(f"  X-Subdomain   : {request.headers.get('X-Subdomain')}")
        #print(f"  Resolved DB   : {resolved_db}")
        print(f"  email_id      : {data.get('email_id')}")
        print(f"  username      : {data.get('username')}")
        print(f"  password      : {data.get('password')}")
        print(f"  password      : {'*' * len(_pw)} ({len(_pw)} chars)")
        #print("=====================")

        ok, errors = LoginSchema.validate(data)
        if not ok:
            return jsonify({"status": "error", "message": errors[0]}), 400

        # accept email_id or username (legacy Android client)
        email_id = (data.get('email_id') or data.get('username', '')).strip()
        password = data.get('password', '')

        db     = get_auth_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(Q.GET_USER_BY_EMAIL, (email_id,))
        user = cursor.fetchone()
        cursor.close()
        db.close()
        print(f"  Found user: {user['email_id'] if user else None}")
        if not user or not bcrypt.checkpw(password.encode(), user['password'].encode()):
            return jsonify({"status": "error",
                            "message": "Invalid email or password!"}), 401

        return jsonify({
            "status":  "success",
            "message": "Login successful!",
            "user": {
                "user_id":  user['user_id'],
                "email_id": user['email_id'],
                "name":     user['name'],
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
