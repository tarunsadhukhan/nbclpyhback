import re

from flask import Flask, jsonify
from flask_cors import CORS

from src.mobileapp.db import DB_NAME_ENVIRON_KEY
from src.mobileapp.src.auth.auth import auth_bp
from src.mobileapp.src.attendance.attendance import attendance_bp
from src.mobileapp.src.config import get_config_object
from src.mobileapp.src.dashboard.dashboard import dashboard_bp
from src.mobileapp.src.dashboard.attendance_dashboard import attendance_dashboard_bp
from src.mobileapp.src.employees.employees import employees_bp
from src.mobileapp.src.masters.company_branch import company_branch_bp
from src.mobileapp.src.masters.departments import departments_bp
from src.mobileapp.src.masters.designations import designations_bp
from src.mobileapp.src.masters.machines import machines_bp
from src.mobileapp.src.masters.occupations import occupations_bp
from src.mobileapp.src.masters.shifts import shifts_bp
from src.mobileapp.src.onboarding.onboarding import onboarding_bp
from src.mobileapp.src.leave.leave import leave_bp
from src.mobileapp.src.doff.doff import doff_bp
from src.mobileapp.src.drawing import drawing_bp
from src.mobileapp.src.permissions import permissions_bp
from src.mobileapp.src.sync import sync_bp, install_idempotency


# Allow only safe identifiers as a database name (the leading Host label).
_DB_NAME_RE = re.compile(r'^[A-Za-z0-9_]+$')

# Host suffixes that are NOT tenants. The label in front of one of these is the
# tenant subdomain (``sls.localhost`` -> ``sls``); the bare host with no leading
# label (``localhost``, ``vowerp.co.in``) falls back to the default database.
_BASE_HOSTS = ('localhost', 'vowerp.co.in')


def tenant_from_host(host):
	"""Return the tenant/database name encoded in the request Host, or None.

	``sls.localhost:8000``  -> ``sls``
	``amcl.vowerp.co.in``   -> ``amcl``
	``localhost`` / ``vowerp.co.in`` / an IPv4 address -> None (default db)
	"""
	host = (host or '').split(':', 1)[0].strip().lower()  # drop the :port
	if not host:
		return None
	# A bare IPv4 address (e.g. 13.126.47.172) is never a tenant.
	if host.replace('.', '').isdigit():
		return None
	for base in _BASE_HOSTS:
		if host == base:
			return None
		suffix = '.' + base
		if host.endswith(suffix):
			sub = host[: -len(suffix)].split('.')[0]
			return sub if _DB_NAME_RE.match(sub) else None
	# Unknown host shape: treat the left-most label as the tenant when there is
	# at least one dotted suffix (``sls.example.com`` -> ``sls``).
	parts = host.split('.')
	if len(parts) >= 2 and _DB_NAME_RE.match(parts[0]):
		return parts[0]
	return None


class DatabaseRouterMiddleware:
	"""Pick the target database from a tenant header, the Host subdomain, or the
	first URL segment.

	Three access styles are supported, so the same server works behind a
	subdomain-per-tenant proxy *and* when hit directly by IP:

	* Header     -- ``192.168.0.133:8000/login`` + ``X-Tenant: sls`` -> db ``sls``
	* Subdomain  -- ``sls.vowerp.co.in/login``      -> db ``sls``, path ``/login``
	* Path prefix -- ``192.168.0.181:8000/sls/login`` -> db ``sls``, path ``/login``

	The chosen name is stored in ``environ[DB_NAME_ENVIRON_KEY]`` so
	get_db()/get_auth_db() connect to it. A tenant header (``X-Tenant`` or
	``subdomain``) takes priority and leaves the path untouched -- this is the
	style to use when the client connects to the bare IP, since ``sls.<ip>`` is
	not DNS-resolvable. When a tenant subdomain is present the path is left
	untouched; otherwise the leading ``/<db>`` segment is stripped (the original
	attendance-system scheme). A bare host with no header, subdomain, or leading
	segment falls back to the default database.
	"""

	def __init__(self, wsgi_app):
		self.wsgi_app = wsgi_app

	def __call__(self, environ, start_response):
		# 1) Explicit tenant header wins. WSGI exposes request headers as
		#    HTTP_<NAME> with dashes converted to underscores, so 'X-Tenant'
		#    arrives as 'HTTP_X_TENANT' and 'subdomain' as 'HTTP_SUBDOMAIN'.
		header_tenant = (environ.get('HTTP_X_TENANT')
						 or environ.get('HTTP_X_SUBDOMAIN')
						 or environ.get('HTTP_SUBDOMAIN') or '').strip()
		if header_tenant and _DB_NAME_RE.match(header_tenant):
			environ[DB_NAME_ENVIRON_KEY] = header_tenant
			return self.wsgi_app(environ, start_response)

		# 2) X-Forwarded-Host before Host: behind the Next.js dev proxy (and any
		#    reverse proxy) Host is the proxy target (localhost:8000) while the
		#    tenant subdomain only survives in X-Forwarded-Host — same order as
		#    src/config/db.py. Take the first value of a comma-separated chain.
		forwarded_host = environ.get('HTTP_X_FORWARDED_HOST', '').split(',')[0]
		db_name = tenant_from_host(forwarded_host) or tenant_from_host(environ.get('HTTP_HOST', ''))
		if db_name:
			# Tenant came from the subdomain; leave the path as-is.
			environ[DB_NAME_ENVIRON_KEY] = db_name
		else:
			# No subdomain (e.g. accessed by IP): treat the first URL path
			# segment as the database name and strip it from the route.
			path = environ.get('PATH_INFO', '')
			parts = path.split('/', 2)  # '/<db>/<rest>' -> ['', '<db>', '<rest>']
			if len(parts) >= 2 and _DB_NAME_RE.match(parts[1]):
				db_name = parts[1]
				rest = parts[2] if len(parts) > 2 else ''
				environ[DB_NAME_ENVIRON_KEY] = db_name
				environ['SCRIPT_NAME'] = environ.get('SCRIPT_NAME', '') + '/' + db_name
				environ['PATH_INFO'] = '/' + rest
		return self.wsgi_app(environ, start_response)


def create_app(config_object=None, enable_cors=True):
	app = Flask(__name__)
	app.config.from_object(config_object or get_config_object())
	# When embedded in the FastAPI app (src.main), CORS is handled there; skip
	# Flask's own CORS so responses don't carry duplicate headers.
	if enable_cors:
		CORS(app, resources={r"/*": {"origins": app.config.get('CORS_ORIGINS', '*')}})

	# Route requests to the database named in the Host subdomain.
	app.wsgi_app = DatabaseRouterMiddleware(app.wsgi_app)

	@app.route('/', methods=['GET'])
	def home():
		return jsonify({
			'status': 'success',
			'message': 'Attendance Server Running!'
		})

	app.register_blueprint(auth_bp)
	app.register_blueprint(attendance_bp)
	app.register_blueprint(dashboard_bp)
	app.register_blueprint(attendance_dashboard_bp)
	app.register_blueprint(employees_bp)

	app.register_blueprint(company_branch_bp)
	app.register_blueprint(departments_bp)
	app.register_blueprint(designations_bp)
	app.register_blueprint(machines_bp)
	app.register_blueprint(occupations_bp)
	app.register_blueprint(shifts_bp)

	app.register_blueprint(onboarding_bp)
	app.register_blueprint(leave_bp)
	app.register_blueprint(doff_bp)
	app.register_blueprint(drawing_bp)
	app.register_blueprint(permissions_bp)

	# Offline-first sync: /sync/* endpoints plus the app-wide client_uuid replay
	# guard that makes every mobile POST safe to retry. Registered last so the
	# guard wraps the blueprints above. Both no-op on a tenant database that has
	# not had dbqueries/migrations/offline_sync.sql applied.
	app.register_blueprint(sync_bp)
	install_idempotency(app)

	return app
