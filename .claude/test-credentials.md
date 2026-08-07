# Browser-Test Login Registry (Portal / Admin)

Single source of truth for **URLs + logins + company/branch** used by browser-driven QA
(the `qa-portal-page` skill, `portal-ui-flow-tester` agent, and any `/loop` that drives the
real UI). Any agent that needs to log a tenant in should read THIS file — do not re-ask the
user and do not hardcode creds elsewhere.

> These are **dev/QA-tenant** credentials for local development only. DB password is NOT here —
> read it from `env/database.env` (pymysql; no `mysql` CLI on dev machines).

## How a loop / agent uses this

1. Pick the row for the target **tenant** (default `dev3`).
2. Navigate to the **App URL**. Choose the **Login type** (Portal vs Admin/Console).
3. Enter **Username / Password**.
4. After login, set company + branch: `localStorage.sidebar_selectedCompany` = `co_id`,
   `localStorage.sidebar_selectedBranches` = `[branch_id]` (assert via `evaluate_script`; the
   collapsed sidebar selectors don't always render).
5. Go to the menu: `<App URL>/dashboardportal/<page-path>` (e.g. `sales/enquiry`,
   `juteSQC/spreader`, `procurement/inward`).
6. Newly-seeded menus are cached in `localStorage.sidebar_companies` — a fresh **sign-out/sign-in**
   is required for them to appear (a token refresh is not enough).

## Portal logins (dashboardportal — daily operations)

| Tenant (subdomain) | App URL | Login type | Username | Password | Company (co_id) | Branch (branch_id) | Notes |
|--------------------|---------|-----------|----------|----------|-----------------|--------------------|-------|
| **dev3** | http://dev3.localhost:3000 | Portal | `user1@empirejute.com` | `vowjute@1234` | The Empire Jute Company Limited (`1`) | Factory (`2`) | Default QA target. Test on Factory only — deselect "Head Office" (`sidebar_selectedBranches` must be `[2]`). |
| **sls** | http://sls.localhost:3000 | Portal | `slsuser@vowerp.co.in` | `sls#123456` | co_id `106` | "FACTORY" = branches `4` / `29` / `87` | Prod-ish tenant. Confirm before writing any data. |
| **amcl** | http://amcl.localhost:3000 | Portal | _TBD — add when known_ | _TBD_ | _TBD_ | _TBD_ | amcl admin role is `17` (`amclsuperadmin`), not `1`. |

## Console/Admin logins (dashboardctrldesk / dashboardadmin)

| Persona | App URL | Login endpoint | Username | Password | Notes |
|---------|---------|----------------|----------|----------|-------|
| Control Desk (VOW team) | http://localhost:3000 | `/api/authRoutes/loginconsole` | _TBD_ | _TBD_ | `con_user_type=0`, `con_org_id IS NULL`. DB `vowconsole3`. |
| Tenant Admin | http://<tenant>.localhost:3000 | `/api/authRoutes/loginconsole` | _TBD_ | _TBD_ | `con_user_type=1`, scoped by `con_org_id`. |

## Stack (must be up before browser tests)

- Frontend: Next.js on `:3000` (`vowerp3ui`, Turbopack — hot-reloads `.tsx`).
- Backend: FastAPI on `:8000` (`uvicorn src.main:app --reload` — hot-reloads `src/**.py`).
- DB: creds in `env/database.env` (host `3.7.255.145`, db per tenant). Query via pymysql + project venv:
  `source .venv/Scripts/activate && python -c "..."`.

## Maintenance

- Add a row per tenant you get portal creds for; fill the `_TBD_` cells.
- Keep `co_id` / `branch_id` accurate — the browser step sets them directly in `localStorage`.
- This file is the ONLY place creds live. If you find them hardcoded in an agent/skill, replace
  with a pointer here.
