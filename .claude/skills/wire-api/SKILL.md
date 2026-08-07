---
name: wire-api
description: End-to-end FE+BE API wiring for VoWERP3 — backend query function, FastAPI endpoint, main.py registration, and pytest stub, plus the frontend constant in src/utils/api.ts and service function. Use whenever a frontend feature needs a new backend endpoint (the most repeated process in this codebase). Asks persona, module, and payload shape first.
---

# Skill: wire-api

Last verified: 2026-06-12

## When to use

A page/hook needs data or an action the backend doesn't expose yet, or a backend endpoint exists but
has no frontend constant/service function. This is the single most repeated process across both repos
— follow it instead of improvising.

## Questions to ask the user FIRST (never assume)

1. **Persona?** Control Desk / Tenant Admin / Portal — controls DB dependency, code location, prefix
   (see `CLAUDE.md` → Choosing the Right DB Dependency).
2. **Module + router prefix?** Existing module (e.g. `/api/procurementIndent`) or a new prefix?
3. **Request/response shape?** Query params vs body; what columns/fields come back.
4. **Which route object** in `vowerp3ui/src/utils/api.ts`: `apiRoutes` (tenant admin/auth),
   `apiRoutesconsole` (control desk), or `apiRoutesPortalMasters` (portal business)?
5. **Scope:** does it filter by `co_id`/`branch_id` (portal endpoints almost always do)?

## Procedure

### Backend (this repo) — build first; never ship a dead frontend constant

1. **Query function** in `src/{module}/query.py` — `sqlalchemy.text()` with named binds
   (`:co_id`, `:search`...). Pattern: `src/procurement/query.py`.
2. **Endpoint** in `src/{module}/{feature}.py` — follow `CLAUDE.md` → "Quick Reference: Adding a New
   Endpoint" exactly: validate params → type-cast → execute → return `{"data": [...]}`.
   Reference: `src/procurement/indent.py`. Use the right DB dependency for the persona.
3. **Register** in `src/main.py` if the router is new:
   `app.include_router(router, prefix="/api/{moduleName}", tags=["..."])`.
4. **Test stub** in `src/test/test_{module}_{feature}.py` — mock `get_tenant_db` +
   `get_current_user_with_refresh` (see `.claude/agents/test-writer.md`). Run it.

### Frontend (`../vowerp3ui`)

5. **Constant** in `src/utils/api.ts` in the route object confirmed above —
   `MY_FEATURE_TABLE: '/myModule/get_my_table'` (no `/api` prefix; the client adds it).
6. **Service function** in `src/utils/{module}Service.ts` using `fetchWithCookie` from
   `src/utils/apiClient2.ts`. Pattern: `src/utils/indentService.ts`. Pass `co_id`/`branch_id` from
   the sidebar context for portal calls.
7. Hook/page consumes the service function — never `fetchWithCookie` directly in components.

### Afterwards

8. If the endpoint serves a module with a guide agent, offer to update the module's knowledge doc
   (endpoint table) — ask the user first (team maintenance norm).

## Verification

- `pytest src/test/test_{module}_{feature}.py -v` passes.
- `curl "http://localhost:8000/api/{prefix}/{path}?co_id=1"` returns `{"data": [...]}`.
- Frontend: `npx tsc --noEmit` clean; the page loads data through the new service function.
