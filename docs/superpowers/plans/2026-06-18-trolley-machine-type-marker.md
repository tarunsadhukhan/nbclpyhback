# Trolley Machine-Type Marker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tag each `trolly_mst` row with one production machine type so Spinning and Winding doff-entry pages list only their own trolleys.

**Architecture:** Add a nullable `machine_type_id` column on `trolly_mst` (FK `machine_type_mst`). The shared `get_trollies_query` / `get_winding_trollies_query` gain an optional `:machine_type_name` bind that resolves the name → id and filters strictly (untagged rows excluded when a stage is passed; the master list passes `NULL` to show all). The Trolly Master page gets a required Machine Type picker fed by a new 4-stage list endpoint.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 (raw `text()` queries) · MySQL/PyMySQL · Pytest · Next.js + MUI (frontend).

## Global Constraints

- Backend repo: `c:\code\vowerp3be`. Frontend repo: `c:\code\vowerp3ui`.
- Portal persona: routers use `Depends(get_tenant_db)` + `Depends(get_current_user_with_refresh)`.
- All endpoints return `{"data": ...}` — never raw lists.
- SQL NULL = Python `None` (never the string `"null"`); bind names match `:name` exactly; type-cast ints.
- Keep the production column typo `busket_weight` (aliased `bucket_weight` in responses). Never rename it.
- `machine_type_mst` is global (no `co_id`): columns `machine_type_id`, `machine_type_name`, `active`. Stage names live in `src/juteProduction/constants.py`: `SPREADER_MACHINE_TYPE_NAME="Spreader"`, `DRAWING_MACHINE_TYPE_NAME="Drawing"`, `SPINNING_MACHINE_TYPE_NAME="Spinning"`, `WINDING_MACHINE_TYPE_NAME="Winding"`.
- Migrations: no Alembic, no `mysql` CLI. Apply via pymysql in the project venv; **target DB `dev3`** (confirm tenant before running).
- Run backend tests from repo root: `source .venv/Scripts/activate && pytest src/test/<file> -v`.

---

### Task 1: Migration + ORM model

**Files:**
- Create: `dbqueries/migrations/add_machine_type_id_to_trolly_mst.sql`
- Modify: `src/juteProduction/spinning_models.py:157-165` (class `TrollyMst`)

**Interfaces:**
- Produces: `trolly_mst.machine_type_id` (INT NULL) in DB + on the `TrollyMst` ORM model; also adds the `trolly_type` column to the model (DB already has it).

- [ ] **Step 1: Write the migration file**

Create `dbqueries/migrations/add_machine_type_id_to_trolly_mst.sql`:

```sql
-- Add a production machine-type marker to trolly_mst so each jute-production
-- stage (Spreader/Drawing/Spinning/Winding) lists only its own trolleys.
-- Target DB: dev3 (confirm before running on other tenants).
ALTER TABLE trolly_mst ADD COLUMN machine_type_id INT NULL;

-- Rollback:
-- ALTER TABLE trolly_mst DROP COLUMN machine_type_id;
```

- [ ] **Step 2: Update the ORM model**

In `src/juteProduction/spinning_models.py`, class `TrollyMst`, after the `branch_id` line add the two columns so the model matches the DB:

```python
class TrollyMst(Base):
    __tablename__ = "trolly_mst"

    trolly_id = Column(Integer, primary_key=True, autoincrement=True)
    trolly_name = Column(String(100), nullable=True)
    trolly_weight = Column(DECIMAL(10, 3), nullable=True)
    busket_weight = Column(DECIMAL(10, 3), nullable=True)  # TYPO kept — alias AS bucket_weight in responses
    trolly_posting_code = Column(String(50), nullable=True)
    branch_id = Column(Integer, nullable=True)
    trolly_type = Column(String(1), nullable=True)  # 'T'=trolly, 'S'=spool
    machine_type_id = Column(Integer, nullable=True)  # FK machine_type_mst — production stage marker
```

- [ ] **Step 3: Verify the model imports cleanly**

Run: `source .venv/Scripts/activate && python -c "from src.juteProduction.spinning_models import TrollyMst; print(TrollyMst.__table__.c.keys())"`
Expected: list printed containing `machine_type_id` and `trolly_type`.

- [ ] **Step 4: Apply the migration to dev3**

Read credentials from `env/database.env`. Run (confirm `dev3` is the intended tenant first):

```bash
source .venv/Scripts/activate && python -c "
import pymysql, os
# host/user/pass from env/database.env
conn = pymysql.connect(host='<HOST>', port=3306, user='<USER>', password='<PASS>', database='dev3')
cur = conn.cursor()
with open('dbqueries/migrations/add_machine_type_id_to_trolly_mst.sql') as f:
    for stmt in f.read().split(';'):
        s = stmt.strip()
        if s and not s.startswith('--'):
            cur.execute(s)
conn.commit(); conn.close()
print('Migration applied to dev3')
"
```

Expected: `Migration applied to dev3`. (Idempotency note: if the column already exists MySQL errors `Duplicate column name` — safe to treat as already-applied.)

- [ ] **Step 5: Commit**

```bash
git add dbqueries/migrations/add_machine_type_id_to_trolly_mst.sql src/juteProduction/spinning_models.py
git commit -m "feat: add machine_type_id column + ORM to trolly_mst"
```

---

### Task 2: Backend — query filter, master CRUD, types endpoint, spinning wiring

**Files:**
- Modify: `src/juteProduction/spinning_query.py:80-97` (`get_trollies_query`)
- Modify: `src/juteProduction/spinning_masters.py` (imports; `TrollyCreate`/`TrollyUpdate`; `trolly_list`; `trolly_create`; `trolly_edit`; new `trolly_machine_types` endpoint)
- Modify: `src/juteProduction/spinning_entry.py:332-333` (doff setup trolley loop)
- Test: `src/test/test_spinning_masters.py`

**Interfaces:**
- Consumes: `trolly_mst.machine_type_id` (Task 1); stage-name constants from `src/juteProduction/constants.py`.
- Produces:
  - `get_trollies_query()` now **requires** binds `:branch_id` and `:machine_type_name` (pass `None` for "all").
  - `GET /api/spinningMasters/trolly_machine_types` → `{"data": [{"machine_type_id": int, "machine_type_name": str}, ...]}`.
  - `TrollyCreate.machine_type_id: int` (required); `TrollyUpdate.machine_type_id: Optional[int]`.
  - Trolly list/create/edit responses include/persist `machine_type_id`.

- [ ] **Step 1: Write the failing tests**

In `src/test/test_spinning_masters.py`, **replace** `test_trolly_create_success` (the body now must include `machine_type_id`, else it 422s) and **add** the new tests. Inside class `TestTrollyMaster`:

```python
    def test_trolly_create_success(self):
        insert_result = MagicMock()
        insert_result.lastrowid = 15
        self._mock_session.execute.side_effect = [insert_result]
        body = {
            "trolly_name": "T-15",
            "trolly_weight": 9.5,
            "busket_weight": 1.5,
            "trolly_posting_code": "TP15",
            "branch_id": 4,
            "machine_type_id": 3,
        }
        resp = client.post("/api/spinningMasters/trolly_create", json=body)
        assert resp.status_code == 200
        assert resp.json()["data"]["trolly_id"] == 15
        ins = _exec_params(self._mock_session, 0)
        assert ins["busket_weight"] == 1.5
        assert ins["trolly_weight"] == 9.5
        assert ins["machine_type_id"] == 3

    def test_trolly_create_requires_machine_type(self):
        body = {
            "trolly_name": "T-16",
            "trolly_weight": 9.5,
            "busket_weight": 1.5,
        }
        resp = client.post("/api/spinningMasters/trolly_create", json=body)
        assert resp.status_code == 422

    def test_trolly_list_passes_null_machine_type(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        resp = client.get("/api/spinningMasters/trolly_list?co_id=1")
        assert resp.status_code == 200
        params = _exec_params(self._mock_session, 0)
        assert params["machine_type_name"] is None

    def test_trolly_edit_persists_machine_type(self):
        select_result = MagicMock()
        select_result.fetchone.return_value = _row(trolly_id=15)
        update_result = MagicMock()
        self._mock_session.execute.side_effect = [select_result, update_result]
        resp = client.put(
            "/api/spinningMasters/trolly_edit/15",
            json={"machine_type_id": 4},
        )
        assert resp.status_code == 200
        upd = _exec_params(self._mock_session, 1)
        assert upd["machine_type_id"] == 4

    def test_trolly_machine_types_returns_stages(self):
        rows = [
            _mapping_row({"machine_type_id": 3, "machine_type_name": "Spinning"}),
            _mapping_row({"machine_type_id": 4, "machine_type_name": "Winding"}),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows
        resp = client.get("/api/spinningMasters/trolly_machine_types")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert {d["machine_type_name"] for d in data} == {"Spinning", "Winding"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source .venv/Scripts/activate && pytest src/test/test_spinning_masters.py -v`
Expected: FAIL — `test_trolly_create_success` (KeyError `machine_type_id`), `test_trolly_list_passes_null_machine_type` (KeyError `machine_type_name`), `test_trolly_machine_types_returns_stages` (404, route not defined).

- [ ] **Step 3: Update `get_trollies_query`**

Replace the body of `get_trollies_query` in `src/juteProduction/spinning_query.py` with:

```python
def get_trollies_query():
    """Trolly master rows (branch + machine-type optional). Keep busket_weight
    column name; alias bucket_weight in the response.

    :machine_type_name NULL -> all rows (master list). When a stage name is
    passed it resolves to its machine_type_id and filters strictly, so untagged
    (NULL) trolleys are excluded from that stage's page.
    """
    return text(
        """
        SELECT
            t.trolly_id,
            t.trolly_name,
            t.trolly_weight,
            t.busket_weight AS bucket_weight,
            t.trolly_posting_code,
            t.branch_id,
            COALESCE(t.trolly_type, 'T') AS trolly_type,
            t.machine_type_id,
            mt.machine_type_name
        FROM trolly_mst t
        LEFT JOIN machine_type_mst mt ON mt.machine_type_id = t.machine_type_id
        WHERE (:branch_id IS NULL OR t.branch_id = :branch_id)
          AND (
                :machine_type_name IS NULL
                OR t.machine_type_id = (
                    SELECT machine_type_id FROM machine_type_mst
                    WHERE machine_type_name = :machine_type_name AND active = 1
                    LIMIT 1)
              )
        ORDER BY t.trolly_name
        """
    )
```

- [ ] **Step 4: Update imports + Pydantic models in `spinning_masters.py`**

Replace the import line `from src.juteProduction.spinning_query import get_trollies_query` with:

```python
from src.juteProduction.spinning_query import get_trollies_query
from src.juteProduction.constants import (
    SPREADER_MACHINE_TYPE_NAME,
    DRAWING_MACHINE_TYPE_NAME,
    SPINNING_MACHINE_TYPE_NAME,
    WINDING_MACHINE_TYPE_NAME,
)
```

Add `machine_type_id` to both models:

```python
class TrollyCreate(BaseModel):
    trolly_name: str
    trolly_weight: float = Field(ge=0)
    busket_weight: float = Field(default=0.0, ge=0)
    trolly_posting_code: Optional[str] = None
    branch_id: Optional[int] = None
    trolly_type: str = "T"  # 'T'=trolly, 'S'=spool (winding doff distinguishes them)
    machine_type_id: int  # required — production stage marker


class TrollyUpdate(BaseModel):
    trolly_name: Optional[str] = None
    trolly_weight: Optional[float] = Field(default=None, ge=0)
    busket_weight: Optional[float] = Field(default=None, ge=0)
    trolly_posting_code: Optional[str] = None
    branch_id: Optional[int] = None
    trolly_type: Optional[str] = None
    machine_type_id: Optional[int] = None
```

- [ ] **Step 5: Pass `machine_type_name=None` in `trolly_list`**

In `trolly_list`, change the execute params (around line 84):

```python
        rows = db.execute(
            get_trollies_query(),
            {"branch_id": branch_id, "machine_type_name": None},
        ).fetchall()
```

- [ ] **Step 6: Persist `machine_type_id` in create + edit**

In `trolly_create`, add the column to the INSERT and a bind:

```python
                INSERT INTO trolly_mst
                    (trolly_name, trolly_weight, busket_weight, trolly_posting_code, branch_id, trolly_type, machine_type_id)
                VALUES
                    (:trolly_name, :trolly_weight, :busket_weight, :trolly_posting_code, :branch_id, :trolly_type, :machine_type_id)
```

```python
                "trolly_type": (body.trolly_type or "T").upper()[:1],
                "machine_type_id": int(body.machine_type_id),
```

In `trolly_edit`, after the `trolly_type` block add:

```python
        if body.machine_type_id is not None:
            fields.append("machine_type_id = :machine_type_id")
            params["machine_type_id"] = int(body.machine_type_id)
```

- [ ] **Step 7: Add the `trolly_machine_types` endpoint**

In `spinning_masters.py`, after `trolly_list` (before `trolly_create`) add:

```python
@router.get("/trolly_machine_types")
async def trolly_machine_types(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Production machine types (4 stages) eligible for trolley tagging."""
    try:
        rows = db.execute(
            text(
                """
                SELECT machine_type_id, machine_type_name
                FROM machine_type_mst
                WHERE active = 1
                  AND machine_type_name IN (:t1, :t2, :t3, :t4)
                ORDER BY machine_type_name
                """
            ),
            {
                "t1": SPREADER_MACHINE_TYPE_NAME,
                "t2": DRAWING_MACHINE_TYPE_NAME,
                "t3": SPINNING_MACHINE_TYPE_NAME,
                "t4": WINDING_MACHINE_TYPE_NAME,
            },
        ).fetchall()
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 8: Wire spinning doff setup to filter by Spinning**

In `src/juteProduction/spinning_entry.py` (doff setup, around line 333), pass the stage name:

```python
        trollies = []
        for r in db.execute(
            get_trollies_query(),
            {"branch_id": branch_id, "machine_type_name": SPINNING_MACHINE_TYPE_NAME},
        ).fetchall():
```

(`SPINNING_MACHINE_TYPE_NAME` is already imported in `spinning_entry.py`.)

- [ ] **Step 9: Run the spinning-masters tests to verify they pass**

Run: `source .venv/Scripts/activate && pytest src/test/test_spinning_masters.py -v`
Expected: PASS (all `TestTrollyMaster` tests).

- [ ] **Step 10: Run the broader spinning suites for regressions**

Run: `source .venv/Scripts/activate && pytest src/test/test_spinning_entry.py src/test/test_spinning_planning_grid.py -v`
Expected: PASS. (If any test asserts `get_trollies_query` params, update it to include `"machine_type_name": SPINNING_MACHINE_TYPE_NAME`.)

- [ ] **Step 11: Commit**

```bash
git add src/juteProduction/spinning_query.py src/juteProduction/spinning_masters.py src/juteProduction/spinning_entry.py src/test/test_spinning_masters.py
git commit -m "feat: machine-type marker on trolly master + spinning filter + types endpoint"
```

---

### Task 3: Backend — winding query filter + winding wiring

**Files:**
- Modify: `src/juteProduction/winding_query.py:63-85` (`get_winding_trollies_query`)
- Modify: `src/juteProduction/winding_entry.py:259-285` (trolley + spool loops)
- Test: `src/test/test_winding_entry.py`

**Interfaces:**
- Consumes: `trolly_mst.machine_type_id` (Task 1); `WINDING_MACHINE_TYPE_NAME` (already imported in `winding_entry.py`).
- Produces: `get_winding_trollies_query()` now **requires** binds `:trolly_type`, `:branch_id`, `:machine_type_name`.

- [ ] **Step 1: Write the failing test**

In `src/test/test_winding_entry.py`, find the doff-setup test that exercises the trolley/spool lists (the one asserting the `get_winding_trollies_query` calls). Add an assertion that both calls pass `machine_type_name="Winding"`. If no such test exists, add one to the setup test class:

```python
    def test_winding_setup_filters_trollies_by_machine_type(self):
        # Arrange the mocked session as the existing setup test does, then:
        # locate the two get_winding_trollies_query calls and assert their binds.
        winding_calls = [
            c.args[1]
            for c in self._mock_session.execute.call_args_list
            if isinstance(c.args[1], dict) and "trolly_type" in c.args[1]
        ]
        assert winding_calls, "expected winding trolley queries"
        assert all(p.get("machine_type_name") == "Winding" for p in winding_calls)
        assert {p["trolly_type"] for p in winding_calls} == {"T", "S"}
```

> If `test_winding_entry.py` uses a different mock/override style, mirror that file's existing doff-setup test exactly (same fixtures, same client call) and only add the two assertions above.

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/Scripts/activate && pytest src/test/test_winding_entry.py -k machine_type -v`
Expected: FAIL — params have no `machine_type_name` key.

- [ ] **Step 3: Update `get_winding_trollies_query`**

Replace its body in `src/juteProduction/winding_query.py` with:

```python
def get_winding_trollies_query():
    """Trolly / spool master rows filtered by trolly_type ('T'=trolly, 'S'=spool)
    and constrained to a production machine type.

    :machine_type_name resolves to machine_type_id; untagged rows are excluded.
    Keeps the busket_weight column name; the response aliases it bucket_weight.
    """
    return text(
        """
        SELECT
            t.trolly_id,
            t.trolly_name,
            t.trolly_weight,
            t.busket_weight AS bucket_weight,
            t.trolly_posting_code,
            t.trolly_type,
            t.branch_id,
            t.machine_type_id
        FROM trolly_mst t
        WHERE t.trolly_type = :trolly_type
          AND (:branch_id IS NULL OR t.branch_id = :branch_id)
          AND t.machine_type_id = (
                SELECT machine_type_id FROM machine_type_mst
                WHERE machine_type_name = :machine_type_name AND active = 1
                LIMIT 1)
        ORDER BY t.trolly_name
        """
    )
```

- [ ] **Step 4: Pass `machine_type_name` at both winding call sites**

In `src/juteProduction/winding_entry.py`, update the two `get_winding_trollies_query` calls (lines ~261 and ~275):

```python
            get_winding_trollies_query(),
            {"trolly_type": "T", "branch_id": branch_id, "machine_type_name": WINDING_MACHINE_TYPE_NAME},
```

```python
            get_winding_trollies_query(),
            {"trolly_type": "S", "branch_id": branch_id, "machine_type_name": WINDING_MACHINE_TYPE_NAME},
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `source .venv/Scripts/activate && pytest src/test/test_winding_entry.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/juteProduction/winding_query.py src/juteProduction/winding_entry.py src/test/test_winding_entry.py
git commit -m "feat: filter winding doff trollies/spools by Winding machine type"
```

---

### Task 4: Frontend — Trolly Master machine-type picker

**Files:**
- Modify: `c:\code\vowerp3ui\src\utils\api.ts:826-829` (add `TROLLY_MACHINE_TYPES`)
- Modify: `c:\code\vowerp3ui\src\app\dashboardportal\juteProduction\masters\trollyMaster\page.tsx`

**Interfaces:**
- Consumes: `GET /api/spinningMasters/trolly_machine_types` → `{"data": [{machine_type_id, machine_type_name}]}` (Task 2); `machine_type_id` now returned by `TROLLY_LIST` and accepted by create/edit.
- Produces: master page that requires + persists `machine_type_id`.

- [ ] **Step 1: Add the API route constant**

In `c:\code\vowerp3ui\src\utils\api.ts`, inside `apiRoutesPortalMasters`, after the `TROLLY_DELETE` line add:

```ts
    TROLLY_DELETE: `${API_URL}/spinningMasters/trolly_delete`,
    TROLLY_MACHINE_TYPES: `${API_URL}/spinningMasters/trolly_machine_types`,
```

- [ ] **Step 2: Extend types + form state for `machine_type_id`**

In `page.tsx`, add a machine-type type and extend `TrollyRow`; remove the stale "backend does not persist" comments on `trolly_type`/`branch_id`.

```tsx
type MachineType = { machine_type_id: number; machine_type_name: string };

type TrollyRow = {
	trolly_id: number;
	trolly_name: string | null;
	trolly_weight: number | null;
	bucket_weight: number | null;
	trolly_posting_code: string | null;
	branch_id: number | null;
	trolly_type?: string | null;
	machine_type_id: number | null;
};
```

Add `machine_type_id: ""` to the initial `form` state object (alongside `trolly_type`), and a state holder for the loaded list:

```tsx
	const [machineTypes, setMachineTypes] = React.useState<MachineType[]>([]);
```

- [ ] **Step 3: Load machine types on mount**

After the `refresh` callback / its `useEffect`, add:

```tsx
	React.useEffect(() => {
		void (async () => {
			const { data } = await fetchWithCookie<{ data: MachineType[] }>(
				apiRoutesPortalMasters.TROLLY_MACHINE_TYPES,
				"GET"
			);
			setMachineTypes(data?.data ?? []);
		})();
	}, []);
```

- [ ] **Step 4: Seed `machine_type_id` in openCreate / openEdit**

In `openCreate`, add `machine_type_id: ""` to the `setForm({...})` object. In `openEdit`, add:

```tsx
			machine_type_id: r.machine_type_id != null ? String(r.machine_type_id) : "",
```

- [ ] **Step 5: Send `machine_type_id` in the save body**

In `handleSave`, add to the `body` object:

```tsx
			machine_type_id: form.machine_type_id !== "" ? Number(form.machine_type_id) : null,
```

- [ ] **Step 6: Add the required Machine Type select to the dialog**

In the dialog `<Box>`, after the existing Type select, add:

```tsx
							<TextField
								select
								label="Machine Type"
								value={form.machine_type_id}
								onChange={(e) => setForm({ ...form, machine_type_id: e.target.value })}
								size="small"
								required
								helperText={machineTypes.length === 0 ? "Loading machine types…" : "Required"}
							>
								{machineTypes.map((mt) => (
									<MenuItem key={mt.machine_type_id} value={String(mt.machine_type_id)}>
										{mt.machine_type_name}
									</MenuItem>
								))}
							</TextField>
```

- [ ] **Step 7: Disable Save until a machine type is chosen**

Update the Save button `disabled` prop to also require `machine_type_id`:

```tsx
							disabled={
								!form.trolly_name ||
								form.trolly_weight === "" ||
								form.busket_weight === "" ||
								form.machine_type_id === ""
							}
```

- [ ] **Step 8: Add the Machine Type grid column**

In `columns`, after the existing `trolly_type` column add:

```tsx
			{
				field: "machine_type_id",
				headerName: "Machine Type",
				width: 150,
				valueGetter: (value) => {
					if (value == null) return "—";
					const mt = machineTypes.find((m) => m.machine_type_id === value);
					return mt ? mt.machine_type_name : value;
				},
			},
```

- [ ] **Step 9: Add a Machine Type filter to the header bar**

Add a filter state alongside the existing `typeFilter`:

```tsx
	const [machineTypeFilter, setMachineTypeFilter] = React.useState<"ALL" | number>("ALL");
```

In the header `<Box>` filter row (next to the existing Type `<TextField>`), add:

```tsx
						<TextField
							select
							label="Machine Type"
							value={String(machineTypeFilter)}
							onChange={(e) =>
								setMachineTypeFilter(e.target.value === "ALL" ? "ALL" : Number(e.target.value))
							}
							size="small"
							sx={{ minWidth: 150 }}
						>
							<MenuItem value="ALL">All</MenuItem>
							{machineTypes.map((mt) => (
								<MenuItem key={mt.machine_type_id} value={String(mt.machine_type_id)}>
									{mt.machine_type_name}
								</MenuItem>
							))}
						</TextField>
```

Extend `filteredRows` to also apply this filter:

```tsx
	const filteredRows = React.useMemo(() => {
		return rows.filter((r) => {
			const typeOk = typeFilter === "ALL" || (r.trolly_type === "S" ? "S" : "T") === typeFilter;
			const mtOk = machineTypeFilter === "ALL" || r.machine_type_id === machineTypeFilter;
			return typeOk && mtOk;
		});
	}, [rows, typeFilter, machineTypeFilter]);
```

- [ ] **Step 10: Build / type-check the frontend**

Run (in `c:\code\vowerp3ui`): `npm run build` (or `npx tsc --noEmit`).
Expected: no type errors in `trollyMaster/page.tsx` or `api.ts`.

- [ ] **Step 11: Manual smoke check**

Start the FE + BE dev servers. On the Trolly Master page: create a trolley → Machine Type required, saves; the grid shows the Machine Type column. Then open the Spinning doff entry and confirm only Spinning-tagged trolleys appear (untagged ones are gone — expected, strict filter). Same for Winding.

- [ ] **Step 12: Commit**

```bash
cd c:\code\vowerp3ui
git add src/utils/api.ts src/app/dashboardportal/juteProduction/masters/trollyMaster/page.tsx
git commit -m "feat: Machine Type marker on Trolly Master page"
```

---

## Notes for the implementer

- **Strict filtering is intentional.** After Tasks 2–3, Spinning/Winding pages show only trolleys tagged with their stage. Pre-existing trolleys are untagged → invisible on those pages until re-tagged via the master page. There is **no** automatic backfill (a trolley's stage isn't derivable). This was the user's explicit choice.
- The master list endpoint (`trolly_list`) deliberately passes `machine_type_name=None` so it still shows every trolley — it's the place to fix untagged rows.
- Two repos: Tasks 1–3 in `vowerp3be`, Task 4 in `vowerp3ui` (separate git commits per repo).
