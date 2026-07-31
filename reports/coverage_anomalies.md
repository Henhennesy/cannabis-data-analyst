# Coverage anomalies in `public.bdsa_sales`

Generated 2026-07-31, against the database **before** the reload.

> **RESOLVED 2026-07-31.** Maine, Arkansas and South Dakota were all reloaded
> from corrected exports. All 37 states now carry both years; no state is
> missing a year. Minnesota was investigated and needed no fix — it is real
> growth. Post-load figures are in [baseline_metrics.md](baseline_metrics.md).
>
> The South Dakota exports turned out to be **month-grain** (12 months for
> 2025, 7 for 2026), which is why its annual figures looked wrong. They were
> aggregated to annual before loading so the table stays uniform; the monthly
> detail is preserved in `data_cleaning_tool/clean/bdsa_clean.parquet`.
>
> **The "Consequence for the agent" section at the bottom still stands.** The
> 2026 window is still partial, still unknown, and still varies by state. SD's
> monthly file showed its own 2026 window runs January–July; no other state
> discloses its window anywhere in the data.

## Method

2026 is a partial year. If every state's 2026 export covered the same YTD
window, each state's `2026 dollars / 2025 dollars` ratio would cluster tightly.
It does not. The modal ratio is **0.42–0.48**, and four states fall outside a
0.30–0.75 band.

Because `period_month` is a year marker (`2025-01-01` / `2026-01-01`) and
`period_grain` is `'year'` on every row, **the actual YTD window of the 2026
data is not recorded anywhere in the database.** It cannot be derived. Only
whoever ran the BDSA export knows it.

## Findings

| State | 2025 | 2026 | ratio | verdict |
| --- | --- | --- | --- | --- |
| Arkansas | *none* | $139,508,621.49 | — | **missing year** |
| Maine | *none* | $386,884,593.10 | — | **missing year + duplicate** |
| Minnesota | $177,434,981.95 | $147,293,453.63 | 0.830 | genuine growth |
| South Dakota | $52,340,820.38 | $9,026,457.05 | 0.172 | **short 2026 window** |

### Arkansas — no 2025 data

Only `raw_exports/Unformatted Data_AR_26.csv` exists: 29,671 rows,
$139,508,621.49, 83 brands, 11 `category_l2` values. There is no `AR_25` file.
Same shape as the Maine gap and almost certainly the same cause — the 2025
export was never downloaded. Fix is identical: pull AR 2025, run it through
`normalize_raw.py` → `clean_bdsa.py` → the transactional loader.

### Minnesota — real, not a defect

Rows rise 4,526 → 11,745 and brands 182 → 245, while dollars-per-unit holds
steady at $35.32 → $36.36. A partial year reaching 83% of the prior full year
on a 2.6x larger SKU base is a market expanding fast, not a load error. Leave
it alone.

### South Dakota — the 2026 window is much shorter than other states

| year | rows | dollars | units | $/unit | brands |
| --- | --- | --- | --- | --- | --- |
| 2025 | 16,227 | $52,340,820.38 | 1,726,345.04 | $30.32 | 207 |
| 2026 | 17,598 | $9,026,457.05 | 283,336.94 | $31.86 | 159 |

Rows went **up** while units fell to 16% of prior year, with price per unit
flat. That is the signature of the same SKU catalog observed over a much
shorter window — not a market collapse and not a duplicate. If the typical
state's 2026 covers ~5 months, South Dakota's covers roughly 2.

## Consequence for the agent

This is stronger than "2026 is partial". **The 2026 bucket does not represent
the same time window across states**, and nothing in the data says what any
state's window is. Therefore:

1. A national 2026 total silently sums states measured over different windows.
   It is not a meaningful market size.
2. Cross-state 2026 comparison is invalid.
3. 2025-vs-2026 comparison is invalid (already agreed: the agent refuses).
4. `describe_coverage` must report 2026 as "partial, window unknown and
   varying by state", not merely "partial".

The defensible 2026 uses are within-state share and mix questions, where the
window cancels out of the numerator and denominator. Those are safe and should
stay available.
