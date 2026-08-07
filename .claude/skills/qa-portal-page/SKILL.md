---
name: qa-portal-page
description: Browser-test a Portal page (dashboardportal) on the dev3 tenant end-to-end — log in as the Empire/Factory test user, make 2+ valid entries, deliberately make wrong entries to probe error handling, fix any backend/frontend/data bug found, and verify persistence in the dev3 DB. Use whenever the user wants to QA / full-flow test / dogfood a freshly-built portal page or form in the real UI, asks how a page handles bad input or exceptions, or says "test the <X> page in the browser" / "QA the new <module> screens on dev3". Dispatches the portal-ui-flow-tester agent. Asks which page path(s) to test if not given.
---

# Skill: qa-portal-page

Reusable full-flow UI test of a portal page as it is built. Thin entry point — the
**`portal-ui-flow-tester`** agent carries the methodology and the baked-in dev3 / Empire / Factory
test credentials.

## When to use

- A new portal page/form was just wired up and needs exercising in a real browser before sign-off.
- The user wants to know how a page surfaces validation errors / handles exceptions (negative testing).
- A portal page errors on load or save and needs reproduce-and-fix in the browser.

Not for: pytest unit tests (use `test-writer`) or non-UI backend changes.

## Inputs (ask if missing)

- **Page path(s)** under `dashboardportal`, e.g. `juteSQC/spreader`, `procurement/inward`. Page URL =
  `http://<tenant>.localhost:3000/dashboardportal/<path>`. Accept several at once.
- **Tenant** (optional) — defaults to `dev3`. Any other tenant must have a row in the login registry.

URL, login, company/branch, and DB creds are NOT asked — they come from the login registry
**`.claude/test-credentials.md`** (single source of truth). The agent reads it directly.

## Steps

1. Confirm the page path(s). If the user named a module instead of a page, list the candidate pages
   under that module's `dashboardportal/<module>/` folder and confirm which to test.
2. Confirm the stack is up (frontend `:3000`, backend `:8000`). If a server is down, say so and stop —
   the agent needs both running and a Chrome window open.
3. Dispatch the **`portal-ui-flow-tester`** agent (via the Agent tool) with the page path(s) as its
   task. It will: log in (Empire / Factory), do ≥2 valid entries per form/tab, run the negative-test
   matrix (missing required, out-of-range, invalid numbers, duplicates), root-cause + fix any defect,
   and verify rows in dev3.
4. Relay the agent's report: entries made, bugs found + fixed (with file:line), the error-handling
   verdict, and anything left uncommitted. Surface any decision the agent flagged (e.g. a dev3 data
   fix needing approval) to the user.

## Notes

- One shared Chrome + backend hot-reload means the test loop is sequential — dispatch a single agent,
  don't fan out parallel browser agents.
- The agent never commits or mutates shared dev3 data without explicit user approval.
