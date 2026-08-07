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

### Verify it is actually read-only, by hand

```sql
-- Connected as bdsa_readonly, all of these must FAIL:
INSERT INTO bdsa_sales (state) VALUES ('test');
UPDATE bdsa_sales SET state = 'x' WHERE false;
DELETE FROM bdsa_sales WHERE false;
CREATE TABLE nope (i int);

-- and this must SUCCEED:
SELECT count(*) FROM bdsa_sales;
```

### Verify it is actually read-only, in CI

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

## Deployment

The whole stack is three containers: the API, Caddy serving the built UI, and
the Cloudflare Tunnel that publishes it. It is reachable at
`analyst.hennesystrategy.com`, behind Google SSO.

```bash
docker compose up -d --build
```

### The shape of it

```
browser ──TLS──► Cloudflare edge ──► Access policy ──► Tunnel
                                        │                │
                                   allow: one email      │  outbound only
                                        │                ▼
                                        └──────► cloudflared ──► web (Caddy :80)
                                                                  │        │
                                                        /api/* ───┘    static
                                                                  ▼
                                                           backend :8000 ──► Neon
```

Nothing listens on a public interface. The tunnel is an **outbound** connection
from this machine, so there is no forwarded port, no inbound firewall rule, and
no address to scan. `web` is published on `127.0.0.1:8080` for local checks
only — binding that to `0.0.0.0` would put an unauthenticated copy on the LAN,
and the loopback prefix is the entire difference.

### How hidden it is

Four things are true, and one is not.

- Nothing links to it, so nothing crawls it.
- The DNS record points at `<uuid>.cfargotunnel.com`, never at this machine.
- Cloudflare does not allow zone transfers, so subdomains cannot be enumerated.
- **It stays out of Certificate Transparency logs — but only because the name is
  one label deep.** Cloudflare's Universal SSL covers `hennesystrategy.com` and
  `*.hennesystrategy.com` with a single wildcard certificate, so `analyst`
  hides inside it and never appears in a public CT log. A deeper name such as
  `analyst.tools.hennesystrategy.com` is *not* covered by that wildcard, would
  be issued its own certificate, and would be published under its own name
  within minutes. Scanners watch those logs specifically to find hosts like
  this one. **Keep the hostname one label deep.**

What is *not* true: it is not invisible. Someone guessing hostnames could learn
that something responds. What they get is a Cloudflare login screen. The
obscurity is a bonus; **Access is the control**, and it is the part to rely on.

### Cloudflare setup

One-time, in the Zero Trust dashboard.

1. **Identity provider** — Settings → Authentication → Login methods → add
   Google. It needs an OAuth client ID and secret from Google Cloud Console
   (APIs & Services → Credentials → OAuth client ID → Web application), with
   Cloudflare's callback URL as the authorised redirect URI. Cloudflare shows
   you that URL on the same screen.

   The built-in **one-time PIN** method needs none of this and emails a code
   instead. Identical security posture for one user; less pleasant to use often.

2. **Tunnel** — Networks → Tunnels → Create. Tunnel type **Cloudflared**, not
   Mesh (Mesh is WARP site-to-site networking). Name it, save, and the next
   screen offers per-platform install commands: pick the **Docker** tab and
   copy the long `eyJ...` token out of the command into `TUNNEL_TOKEN` in
   `.env`. Do not run the command it shows — compose already runs cloudflared.

   Then open the tunnel and add the route. As of this writing the dashboard
   calls this **Published application routes**, not "Public Hostname":

   | field | value |
   | --- | --- |
   | Subdomain | `analyst` |
   | Domain | `hennesystrategy.com` |
   | Path | *(empty)* |
   | Type | `HTTP` |
   | URL | `web:80` |

   `web:80` is the service name on the compose network, which is why
   `cloudflared` runs in this stack rather than as a standalone service. Type
   is HTTP, not HTTPS: Caddy has `auto_https off` and is not listening for TLS,
   so HTTPS here yields a 502.

   Two traps, both of which cost real time the first time through:

   - **Do not confuse this with Networks → Routes → "Hostname routes".** That
     page is private-network DNS for WARP clients. The giveaway is that it
     never asks for a service URL, because it is not routing to an origin.
   - **Do not hand-delete the DNS record.** Adding the route creates a proxied
     `analyst` record automatically. Deleting it by hand severs the link, and
     re-adding the route then does *not* recreate it -- leaving a route with no
     DNS, which looks identical to DNS that has not propagated. If you end up
     there, recreate it manually as a **CNAME** to
     `<tunnel-id>.cfargotunnel.com`, **Proxied**. Proxying is mandatory:
     `cfargotunnel.com` resolves only through Cloudflare, so a grey-cloud
     record exists and never answers.

3. **Access application** — Access → Applications → Add → Self-hosted, on
   `analyst.hennesystrategy.com`. One policy: action **Allow**, include
   **Emails** → your address. Session duration 24h so it is not asking hourly.

   Passing Google only proves who someone is. The policy decides whether that
   person is you — so the include rule must be the specific email, never
   "any Google account".

**`TUNNEL_TOKEN` is a credential.** Anyone holding it can register as your
tunnel and receive traffic for the hostname. Access guards the front door; this
token is the back door, and it is not behind Access.

### Verifying a deployment

In order, because each step only makes sense if the one before it worked.

```bash
docker compose config                      # compose file parses, vars resolve
docker compose up -d --build
docker compose ps                          # backend healthy before web starts
curl -s localhost:8080/api/health          # the stack, without the tunnel
curl -sI localhost:8080/                   # index.html, CSP header present
docker compose logs -f cloudflared         # look for "Registered tunnel connection"
```

Then open `https://analyst.hennesystrategy.com` in a private window and confirm
you are challenged *before* seeing anything, and that answers still stream token
by token rather than arriving in one block. Streaming is the thing most likely
to break behind a proxy — see below.

To prove the edge is really blocking, rather than trusting that it is, check
both ends of the same request. From outside:

```bash
curl -sI https://analyst.hennesystrategy.com/
```

Expect `302` with a `Www-Authenticate: Cloudflare-Access` header and a
`Location:` pointing at `<team>.cloudflareaccess.com/cdn-cgi/access/login/...`.
Then immediately:

```bash
docker compose logs web --since 2m
```

The blocked request must **not** appear. Everything in that log should be
`127.0.0.1` with `User-Agent: Wget` — those are the container healthchecks. An
external client IP showing up there would mean requests are reaching the origin
before the policy is evaluated, which is the failure worth actually testing for.

> **Resolver caveat.** This workstation cannot resolve the name locally (a VPN
> DNS quirk) and `nslookup` against 1.1.1.1 times out, because outbound port 53
> is filtered. PowerShell reports both as "not found", which is indistinguishable
> from a genuinely missing record and will send you chasing a DNS problem that
> does not exist. Verify over DoH instead, which uses 443:
>
> ```bash
> curl -s "https://dns.google/resolve?name=analyst.hennesystrategy.com&type=A"
> ```
>
> A correct answer is two Cloudflare proxy IPs.

### Two deployment-specific hazards

**Buffering kills the stream.** `/api/chat` is a `text/event-stream`. Caddy
proxies it with `flush_interval -1`, and the API is deliberately outside the
`encode` directive, because a compressor holds bytes back until it has enough
of them to be worth compressing. If answers ever arrive all at once instead of
token by token, this is the first place to look.

**The CSP allows `data:` and `blob:` on `img-src`, and must.** The PNG export
serialises the chart's SVG into a `data:` URI, draws it to a canvas, and returns
a blob. Tightening either one breaks chart export silently — the button works,
nothing downloads.

### What this deliberately does not do

No rate limiting and no spend cap. Once this is reachable from a phone, a
runaway tool loop burns Anthropic credits with nobody watching a terminal.
`MAX_TOOL_CALLS_PER_TURN` bounds a single turn; nothing bounds a day.

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
| `backend/data/analyses.sqlite` | gitignored | small | **yes** — saved analyses are the one piece of state that exists nowhere else |
| The BDSA data itself | Neon (cloud) | — | already safe |

Saved analyses are bind-mounted from `backend/data/`, not held in a Docker
volume, precisely so backing them up is copying a file. SQLite runs in WAL
mode, so **take `analyses.sqlite-wal` with it** or copy while the stack is
down — the sidecar holds committed rows the main file does not yet contain.

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

**The short path, if you only need it serving:** install Docker Desktop, clone
the repo, fill in `.env`, and run `docker compose up -d --build`. Nothing else
— no Python, no Node, no venv, no toolchain versions to match. That is the main
thing containerising bought, and it is why this section is much shorter than it
used to be.

Reconnect the tunnel by pasting the existing `TUNNEL_TOKEN`; the hostname and
Access policy live in Cloudflare and survive the wipe untouched.

**The long path, for development** — needed only to run tests, the CLI, or the
data pipeline, since none of those live in the image:

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

### Autostart on boot

`restart: unless-stopped` brings the containers back whenever the Docker daemon
starts, so the only thing needed is for the daemon itself to start at boot:
Docker Desktop → Settings → General → **Start Docker Desktop when you sign in**.

The catch on Windows is *sign in*, not *boot* — after a power cut the machine
reaches the login screen and stops, and the analyst is down until someone logs
in. If that matters, enable automatic sign-in for this account, and understand
the trade: an unattended machine that unlocks itself. With this box in a place
only you have access to, that is usually the right call for a server.

`unless-stopped` also means a container you stop by hand stays stopped across
reboots, which is the behaviour you want while debugging.

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
