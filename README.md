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
