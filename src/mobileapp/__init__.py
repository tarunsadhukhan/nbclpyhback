"""Mobile app (HRMS / attendance) — a Flask sub-application embedded in the
FastAPI backend.

It is mounted as a WSGI app in ``src.main`` so the whole stack runs from a
single ``uv run -m src.main``. The target tenant database is selected from the
request Host subdomain (e.g. ``sls.localhost:8000`` -> ``sls`` DB); see
``src.mobileapp.src.DatabaseRouterMiddleware``.
"""
