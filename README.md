# BDSA Market Intelligence Analyst

A self-hosted analytical chat application over BDSA cannabis retail
sell-through data in Neon Postgres. Claude calls real query tools against the
database; the UI renders the results and exposes the exact SQL behind every
number.

**The application must never state a figure it did not retrieve from the
database.**

---

## Database role setup

The application connects with a dedicated **read-only** role. It never connects
as the owner or loader role, because the agent executes model-generated SQL
through the `run_sql` escape hatch and privilege is the only real backstop.

### Do not create this role in the Neon console

Roles created through the Neon UI are automatically granted membership in
`neon_superuser`, which inherits `pg_write_all_data`. A console-created role
named "Read Only" can `INSERT`, `UPDATE`, `DELETE` and `TRUNCATE` every table
in the database. Verify any role you did not create with the SQL below:

```sql
SELECT r.rolname,
       ARRAY(SELECT b.rolname FROM pg_auth_members m
             JOIN pg_roles b ON b.oid = m.roleid
             WHERE m.member = r.oid) AS member_of
FROM pg_roles r WHERE r.rolname NOT LIKE 'pg\_%';
```

If `member_of` contains `neon_superuser`, the role can write.

### Create the role via SQL

Run this in the Neon **SQL Editor** as `neondb_owner`. A role created this way
does not inherit `neon_superuser`.

```sql
-- Remove the console-created role, which can write despite its name.
DROP ROLE IF EXISTS "Read Only";

-- Create a login role with no inherited privileges and no ability to
-- create anything.
CREATE ROLE bdsa_readonly WITH LOGIN PASSWORD 'PUT_A_STRONG_PASSWORD_HERE'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

-- Read access, and nothing else.
GRANT CONNECT ON DATABASE neondb TO bdsa_readonly;
GRANT USAGE  ON SCHEMA public    TO bdsa_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO bdsa_readonly;

-- Granted explicitly rather than relying on ALL TABLES covering relkind='m'.
GRANT SELECT ON public.mv_brand_monthly, public.mv_category_monthly
    TO bdsa_readonly;

-- Tables created later by the loader are readable without re-granting.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO bdsa_readonly;

-- Belt and braces. Even if a write privilege is ever granted by mistake,
-- the session itself refuses to write.
ALTER ROLE bdsa_readonly SET default_transaction_read_only = on;

-- Enforced per the spec; the pool sets this too, but a role-level default
-- means a stray psql session cannot run away either.
ALTER ROLE bdsa_readonly SET statement_timeout = '8s';
```

### Build the connection string

Neon's console will not show a connection string for a role created via SQL,
and cannot recover its password. Construct it by substituting the new role and
password into the same host and database as the owner string:

```
postgresql://bdsa_readonly:PASSWORD@<same-host>/<same-db>?sslmode=require&channel_binding=require
```

Put it in `.env` as `NEON_READONLY_URL`. Keep the owner string in
`NEON_INTROSPECT_URL` for schema introspection and data loads only.

### Verify it is actually read-only

```sql
-- Connected as bdsa_readonly, all of these must FAIL:
INSERT INTO bdsa_sales (state) VALUES ('test');
UPDATE bdsa_sales SET state = 'x' WHERE false;
DELETE FROM bdsa_sales WHERE false;
CREATE TABLE nope (i int);

-- and this must SUCCEED:
SELECT count(*) FROM bdsa_sales;
```

### Verify it is actually read-only

```bash
python scripts/verify_readonly.py
```

Checks both layers independently. `default_transaction_read_only` blocking a
write is *not* sufficient — anything that can turn that flag off could then
write. The script disables it on a fresh autocommit connection and requires the
writes to still fail with `permission denied`, i.e. blocked by privilege.

---

## Query performance and the 8s statement timeout

Warm timings against the live database (7.45M-row fact table):

| query | fact table | materialized view |
| --- | --- | --- |
| rows + sales by year | **9.19 s — exceeds timeout** | 0.12 s |
| state × year coverage | 1.79 s | 0.26 s |
| distinct `brand` | 1.05 s | 0.16 s |
| distinct `category_l2` | 1.25 s | 0.06 s |
| fast-acting penetration, 2025 | 0.29 s | 0.06 s |
| top 20 brands in edibles, 2025 | — | 0.12 s |

**Route through the materialized views wherever the required columns exist.**
They are 10–70x faster, and they already exclude suppressed rows, which matches
the default the tools want anyway. Only fall back to `bdsa_sales` for columns
the views do not carry (`category_l4`, `category_l5`, `product`, `strain`,
`flavor`, `pack_size`, `infusion_type`, `items_per_pack`, potency, price).

The one query that blows the 8s budget — summing `total_retail_sales` across
all 7.45M rows grouped by year — has an exact view equivalent at 0.12 s.

### Cold starts

Neon scales the compute to zero when idle. The **first** query after a suspend
pays a cold-start penalty and can exceed 8s regardless of how cheap it is: an
unqualified `count(*)` took 8s+ cold and 0.62s warm. The connection pool must
issue a cheap warm-up query on checkout and retry once on `QueryCanceled`,
otherwise the first question of every session fails intermittently. Disabling
scale-to-zero on the Neon endpoint is the alternative, at higher cost.

---

## Data loading

The ingestion pipeline lives in `data_cleaning_tool/`. BDSA exports arrive in
inconsistent shapes, so loading is three steps, not one:

```bash
# 1. Reframe raw exports (.xlsx, headerless, comma- or tab-delimited,
#    Year- or Month-grain) into what the cleaner expects.
python data_cleaning_tool/normalize_raw.py --input ./raw_exports --output ./raw_normalized

# 2. Clean, type, dedupe, flag suppression.
python data_cleaning_tool/clean_bdsa.py --input ./raw_normalized --output ./clean --delimiter ','

# 3. Collapse any month-grain rows to annual so the table stays uniform.
python data_cleaning_tool/aggregate_to_annual.py --input ./clean/bdsa_clean.parquet --output ./clean/bdsa_annual.csv

# 4. Load. Dry run first -- it rolls back and prints exactly what would change.
python data_cleaning_tool/load_states.py --csv ./clean/bdsa_annual.csv
python data_cleaning_tool/load_states.py --csv ./clean/bdsa_annual.csv --commit --refresh-views
```

`load_states.py` replaces exactly the `(state, period_year)` combinations the
extract contains, inside one transaction. It never deletes by state alone —
that would destroy years present in the table but absent from the extract.

**Always refresh the materialized views after a load.** They exclude suppressed
rows and will otherwise serve stale numbers.

---

## Backup, machine migration, and restore

**The data is not on this machine.** It lives in Neon. Wiping the workstation
does not touch the database, and the fact table is the only thing here that
would be genuinely painful to lose.

### What has to travel

| What | Where | Size | Back up? |
| --- | --- | --- | --- |
| Application (code, system prompt, reports, schema) | git, 48 files | small | **yes** |
| `data_cleaning_tool/raw_exports/` — original BDSA exports | gitignored | ~67 MB | **yes** |
| `data_cleaning_tool/raw_normalized/`, `clean/` | gitignored | ~295 MB | no — regenerated by re-running the pipeline |
| `.venv/` | gitignored | ~122 MB | **never** — absolute paths are baked into `pyvenv.cfg` and every console script; it will not work on another machine or another profile path |
| `.env` | gitignored | tiny | see below |
| The BDSA data itself | Neon (cloud) | — | already safe |

### Do not back up `.env`

Every value in it is re-obtainable, and a copy of it sitting in a zip on
another machine is a credential leak waiting to happen:

- `NEON_READONLY_URL` — rebuild from the Neon console (or re-run the
  `CREATE ROLE` block above and set a fresh password)
- `ANTHROPIC_API_KEY` — issue a new key at console.anthropic.com and revoke
  the old one, which is what you want after wiping a machine anyway
- `EXISTING_API_BASE_URL` / key — from the Render dashboard

Copy `.env.example` to `.env` on the new machine and refill it. Two minutes.

### Backing up

Two options. The second is better.

**A zip.** Archive the repo folder *excluding* `.venv`, plus `raw_exports`:

```powershell
$src = 'C:\Users\Mike`\Documents\Claude Project - Cannabis Data Analyst'
Compress-Archive -Path "$src\*" -DestinationPath 'D:\bdsa-analyst-backup.zip' `
  -CompressionLevel Optimal
# then delete .venv from inside the zip, or exclude it first
```

**A private git remote.** Better: it preserves the full commit history (every
milestone, every decision, every reason recorded in a commit message), and
`git clone` on the new machine restores everything tracked in one command.

> ⚠️ **The repository must be PRIVATE.** `reports/` contains BDSA figures,
> brand-level detail, and state-level sales — licensed third-party data. It must
> not go into a public repository. `raw_exports/` is gitignored and would need
> to travel separately regardless.

### Restoring on a fresh machine

1. Install **Python 3.12+**, **Node LTS**, and **git**.
2. Get the code: `git clone <your private remote>`, or unzip the archive.
3. Restore `raw_exports/` from the separate archive (only needed to re-run the
   data pipeline; the loaded data is already in Neon).
4. Rebuild the environment — this is what `requirements.txt` is for:

   ```powershell
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
   ```

5. Copy `.env.example` to `.env` and fill it in.
6. Verify. The test suite runs against the live database, so a green run proves
   the whole chain — credentials, read-only role, schema, and the known-answer
   baselines — end to end:

   ```powershell
   .venv\Scripts\python.exe -m pytest
   ```

   Expect all tests to pass. If the Milestone 3 baselines fail, the data was
   reloaded since — regenerate `reports/baseline_metrics.md` rather than
   assuming the code broke.

7. `analyst.cmd` for the CLI, `serve.cmd` for the API.

### Note on the profile path

This project is deliberately insensitive to where it lives — the launchers use
`%~dp0`, and nothing hardcodes a user directory. Migrating to a machine with a
clean profile path (no backtick) requires no code changes at all.

---

## Known data characteristics

See [reports/coverage_anomalies.md](reports/coverage_anomalies.md) and
[reports/baseline_metrics.md](reports/baseline_metrics.md).

- Edibles are `category_l2 = 'Edibles'` under `category_l1 = 'Ingestibles'`.
  `category_l1 = 'Edibles'` returns nothing.
- The top-level inhalation category is spelled **`Inhaleables`**.
- `fast_acting IS NOT NULL` **if and only if** `category_l2 = 'Edibles'`. It is
  null on ~96% of the table. Its two values are `Fast Acting` and
  `Not Fast Acting`.
- Dollars are `total_retail_sales`; units are `total_units`. The materialized
  views rename the former to `total_sales`. They are different questions and
  are never substituted for each other.
- BDSA is retail sell-through across covered states only. It is not total
  market. Every figure carries its period and its state set.
- **2026 is a partial year of unknown, state-varying width.** Nothing in the
  data records any state's YTD cutoff. National 2026 totals and cross-state
  2026 comparisons are not meaningful; within-state share and mix questions
  are.
