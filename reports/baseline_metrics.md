# Baseline metrics — fixed-answer regression targets

Computed 2026-07-31, immediately after the Maine / Arkansas / South Dakota
reload. These are the known answers the Milestone 2–3 tests assert against.

**Recompute these whenever a data load changes the underlying rows.** They are
not constants; they are the current truth of the database, and a test that
fails after a legitimate load means the numbers here are stale, not that the
code broke.

## Data state

| period_year | states | rows | dollars |
| --- | --- | --- | --- |
| 2025 | 37 | 3,390,855 | $28,519,734,771.25 |
| 2026 | 37 | 4,059,580 | $13,381,902,254.96 |

- `period_grain` is `'year'` on every row.
- No state is missing a year.
- Total table: 7,450,435 rows.
- 2026 is a PARTIAL year of unknown, state-varying width. See
  [coverage_anomalies.md](coverage_anomalies.md).

## Materialized view reconciliation

All three agree exactly, which is the check that proves the views are not
stale after a load:

| relation | dollars | units | rows |
| --- | --- | --- | --- |
| `bdsa_sales` where NOT `is_suppressed` | $41,901,563,154.47 | 2,091,105,951.03 | 7,428,856 |
| `mv_brand_monthly` | $41,901,563,154.47 | 2,091,105,951.03 | 7,428,856 |
| `mv_category_monthly` | $41,901,563,154.47 | 2,091,105,951.03 | — |

## Milestone 3 target: fast-acting share of national edibles, 2025

Filters: `category_l1 = 'Ingestibles'` AND `category_l2 = 'Edibles'`,
`period_year = 2025`, `is_suppressed = false`. 37 states, 214,199 rows.

| metric | Fast Acting | all Edibles | share |
| --- | --- | --- | --- |
| dollars | $266,382,172.26 | $3,867,307,583.83 | **6.8881 %** |
| units | 16,165,105.45 | 291,143,263.84 | **5.5523 %** |

Dollars and units differ by 1.34 points. `get_segment_penetration` must never
substitute one for the other.

Superseded: before the reload this read 6.9650 % / 5.5586 % across 35 states.
That figure was computed on data missing Maine and Arkansas entirely and with
South Dakota wrong in both years. Do not use it.

## Gotcha assertions — all currently pass

| assertion | result |
| --- | --- |
| `category_l1 = 'Edibles'` returns nothing | 0 rows |
| `category_l1 = 'Inhalables'` (wrong spelling) returns nothing | 0 rows |
| `category_l1 = 'Inhaleables'` (correct) is populated | 7,013,137 rows |
| `fast_acting IS NOT NULL` **iff** `category_l2 = 'Edibles'` | 0 violations |
| non-null `fast_acting` values | exactly `Fast Acting`, `Not Fast Acting` |

The fourth is stronger than the original brief, which said `fast_acting` holds
two literals and "not nulls". It is null on the ~96% of the table that is not
Edibles. Stated as a biconditional it catches both the unexpected-null bug and
a value leaking onto a non-Edibles row.
