# BDSA schema introspection — schema `public`

- Generated: 2026-07-31T14:09:39
- Database: `neondb`  ·  connected as `neondb_owner`
- Server: `PostgreSQL 18.4 (df16b3c) on aarch64-unknown-linux-gnu`

## Relations

| relation | kind | comment |
| --- | --- | --- |
| `mv_brand_monthly` | materialized view |  |
| `mv_category_monthly` | materialized view |  |
| `bdsa_sales` | table |  |
| `playing_with_neon` | table |  |


---

## `public.mv_brand_monthly` — materialized view

### DDL

```sql
CREATE MATERIALIZED VIEW public.mv_brand_monthly AS
 SELECT state,
    category_l1,
    category_l2,
    category_l3,
    brand,
    fast_acting,
    mood_effect,
    cannabinoid_mix,
    sugar_free,
    period_grain,
    period_month,
    period_year,
    sum(total_retail_sales) AS total_sales,
    sum(total_units) AS total_units,
    count(*) AS sku_rows,
    sum(total_retail_sales) / NULLIF(sum(total_units), 0::numeric) AS dollars_per_unit
   FROM bdsa_sales
  WHERE NOT is_suppressed
  GROUP BY state, category_l1, category_l2, category_l3, brand, fast_acting, mood_effect, cannabinoid_mix, sugar_free, period_grain, period_month, period_year;
```

**Row count:** 182,477 (exact)

### Columns

| # | column | type | null | default | comment |
| --- | --- | --- | --- | --- | --- |
| 1 | `state` | text | yes |  |  |
| 2 | `category_l1` | text | yes |  |  |
| 3 | `category_l2` | text | yes |  |  |
| 4 | `category_l3` | text | yes |  |  |
| 5 | `brand` | text | yes |  |  |
| 6 | `fast_acting` | text | yes |  |  |
| 7 | `mood_effect` | text | yes |  |  |
| 8 | `cannabinoid_mix` | text | yes |  |  |
| 9 | `sugar_free` | text | yes |  |  |
| 10 | `period_grain` | text | yes |  |  |
| 11 | `period_month` | date | yes |  |  |
| 12 | `period_year` | integer | yes |  |  |
| 13 | `total_sales` | numeric | yes |  |  |
| 14 | `total_units` | numeric | yes |  |  |
| 15 | `sku_rows` | bigint | yes |  |  |
| 16 | `dollars_per_unit` | numeric | yes |  |  |

### Temporal / period columns — min & max

| column | type | min | max | non-null | null |
| --- | --- | --- | --- | --- | --- |
| `period_grain` | text | year | year | 182,477 | 0 |
| `period_month` | date | 2025-01-01 | 2026-01-01 | 182,477 | 0 |
| `period_year` | integer | 2,025 | 2,026 | 182,477 | 0 |
| `total_units` | numeric | 0.0000 | 21,614,426.8111 | 182,477 | 0 |

### Numeric columns — min, max, sum

| column | type | min | max | sum | non-null | null |
| --- | --- | --- | --- | --- | --- | --- |
| `total_sales` | numeric | 0.0000 | 341,360,016.7555 | 41,170,446,010.4128 | 182,477 | 0 |
| `sku_rows` | bigint | 1 | 69,167 | 7,317,030 | 182,477 | 0 |
| `dollars_per_unit` | numeric | 0.25500242585596077774 | 686.3382053025152957 | 4,476,932.55933043747062420233 | 182,458 | 19 |

### Dimension columns — distinct values (full list when < 200)

#### `state` — 37 distinct value(s), complete list

| value | rows |
| --- | --- |
| `California` | 26,287 |
| `Michigan` | 17,407 |
| `Washington` | 16,505 |
| `Oklahoma` | 14,622 |
| `Oregon` | 12,380 |
| `New York` | 9,784 |
| `Massachusetts` | 9,647 |
| `Colorado` | 9,239 |
| `New Mexico` | 7,854 |
| `New Jersey` | 5,850 |
| `Montana` | 5,010 |
| `Vermont` | 4,979 |
| `Illinois` | 4,886 |
| `Arizona` | 4,660 |
| `Nevada` | 3,334 |
| `Ohio` | 3,208 |
| `Mississippi` | 3,169 |
| `Maine` | 3,118 |
| `Maryland` | 2,984 |
| `Florida` | 2,210 |
| `Rhode Island` | 1,975 |
| `Pennsylvania` | 1,866 |
| `Minnesota` | 1,658 |
| `South Dakota` | 1,610 |
| `Connecticut` | 1,300 |
| `Utah` | 998 |
| `District of Columbia` | 951 |
| `West Virginia` | 833 |
| `Virginia` | 730 |
| `Arkansas` | 685 |
| `Hawaii` | 533 |
| `Louisiana` | 528 |
| `Delaware` | 468 |
| `Georgia` | 387 |
| `North Dakota` | 359 |
| `New Hampshire` | 273 |
| `Iowa` | 190 |

#### `category_l1` — 5 distinct value(s), complete list

| value | rows |
| --- | --- |
| `Inhaleables` | 111,418 |
| `Ingestibles` | 47,275 |
| `All Accessories` | 15,400 |
| `Topicals` | 7,703 |
| `Other Cannabis` | 681 |

#### `category_l2` — 13 distinct value(s), complete list

| value | rows |
| --- | --- |
| `Edibles` | 41,514 |
| `Flower` | 40,069 |
| `Pre-Rolled` | 27,663 |
| `Vape` | 25,592 |
| `Extracts` | 18,094 |
| `Devices` | 9,865 |
| `Topicals` | 7,703 |
| `Sublinguals` | 5,761 |
| `Accessories` | 3,460 |
| `Apparel` | 2,021 |
| `Other Cannabis` | 681 |
| `Non Infused Food` | 53 |
| `Grow Supplies` | 1 |

#### `category_l3` — 55 distinct value(s), complete list

| value | rows |
| --- | --- |
| `Candy` | 27,679 |
| `Whole Buds` | 20,557 |
| `Pre-Rolled` | 15,092 |
| `Vape Cartridge` | 14,416 |
| `Infused Pre-Rolled` | 12,571 |
| `Vape Disposable` | 11,176 |
| `Resin` | 9,065 |
| `Small Buds` | 8,076 |
| `Solventless` | 6,126 |
| `Shake` | 6,093 |
| `Tinctures` | 5,565 |
| `Beverages` | 4,886 |
| `Chocolates` | 3,404 |
| `Balms/Salves` | 3,162 |
| `Pills` | 3,038 |
| `Infused Flower` | 2,984 |
| `Other` | 2,820 |
| `Oil` | 2,750 |
| `Vaporizers` | 2,666 |
| `Pre-Ground` | 2,359 |
| `Infused Foods` | 2,297 |
| `Water Pipe` | 2,093 |
| `Pipe` | 1,618 |
| `Rolling Papers` | 1,539 |
| `Clothing` | 1,351 |
| `Grinder` | 1,237 |
| `Other Topicals` | 1,219 |
| `Creams` | 1,150 |
| `Lotions` | 929 |
| `Lighter` | 841 |
| `Accessories` | 670 |
| `Patches` | 470 |
| `Plants` | 309 |
| `Lip Balm` | 294 |
| `Massage Oil` | 257 |
| `Pet Products` | 229 |
| `Unspecified/Other` | 161 |
| `Lubricants` | 143 |
| `Sticker` | 140 |
| `Other Edibles` | 131 |
| `Dissolvable` | 126 |
| `Storage Device` | 125 |
| `Bundles/Collections` | 121 |
| `Rolling Machine` | 121 |
| `Bowl` | 97 |
| `Cleaner` | 81 |
| `Culinary` | 71 |
| `Suppositories` | 71 |
| `NULL` | 54 |
| `Pre-Loaded` | 22 |
| `Candles` | 12 |
| `Spray` | 7 |
| `Gum` | 4 |
| `Magnet` | 1 |
| `Soap` | 1 |

#### `brand` — high cardinality (> 200 distinct); top 15 by row count

| value | rows |
| --- | --- |
| `Generic` | 4,697 |
| `Cookies` | 659 |
| `Wyld` | 579 |
| `Select` | 483 |
| `Camino` | 453 |
| `Wana Edibles` | 418 |
| `Luv Buds` | 403 |
| `Drops` | 401 |
| `Incredibles` | 382 |
| `Smokiez` | 358 |
| `Raw` | 354 |
| `Vibes` | 353 |
| `Green Revolution` | 342 |
| `Cheeba Chews` | 316 |
| `Rythm` | 304 |

#### `fast_acting` — 3 distinct value(s), complete list

| value | rows |
| --- | --- |
| `NULL` | 140,963 |
| `Not Fast Acting` | 37,965 |
| `Fast Acting` | 3,549 |

#### `mood_effect` — 38 distinct value(s), complete list

| value | rows |
| --- | --- |
| `Not Mood Specific` | 169,145 |
| `Sleep` | 5,070 |
| `Relaxation` | 2,471 |
| `Energy` | 1,901 |
| `Happiness` | 1,233 |
| `Pain Relief` | 738 |
| `Focus` | 557 |
| `Balance` | 508 |
| `Intimacy` | 288 |
| `Creativity` | 164 |
| `Anytime` | 125 |
| `Elevate` | 37 |
| `Fly` | 35 |
| `LOCKED DATA` | 31 |
| `Relief` | 31 |
| `Chill` | 28 |
| `Nighttime` | 11 |
| `Happy` | 8 |
| `Restore` | 8 |
| `Calm` | 7 |
| `Boost` | 6 |
| `Bounce Back` | 6 |
| `Chill Out` | 6 |
| `Genius Mode` | 6 |
| `Recovery` | 6 |
| `Turn Down` | 6 |
| `Turn Up` | 6 |
| `Uplift` | 6 |
| `Flow` | 5 |
| `Glow` | 5 |
| `Thrive` | 5 |
| `Daytime` | 4 |
| `Slow` | 4 |
| `Play` | 3 |
| `Reset` | 3 |
| `Ease` | 2 |
| `Doze` | 1 |
| `Go` | 1 |

#### `cannabinoid_mix` — 32 distinct value(s), complete list

| value | rows |
| --- | --- |
| `THC Only` | 142,397 |
| `NULL` | 15,389 |
| `Contains CBD` | 10,755 |
| `Contains CBN` | 3,508 |
| `Contains CBD, Contains CBN` | 2,970 |
| `Contains CBG` | 2,203 |
| `Contains CBD, Contains CBG` | 1,766 |
| `Contains THCv` | 771 |
| `Contains CBD, Contains CBN, Contains CBG` | 575 |
| `Contains CBC` | 397 |
| `Contains CBD, Contains CBC` | 366 |
| `Contains CBG, Contains CBC` | 309 |
| `Contains CBN, Contains CBG` | 245 |
| `Contains CBG, Contains THCv` | 187 |
| `Contains CBD, Contains CBG, Contains CBC` | 180 |
| `Contains CBD, Contains THCv` | 129 |
| `Contains CBC, Contains THCv` | 68 |
| `Contains CBN, Contains CBC` | 49 |
| `Contains CBD, Contains CBN, Contains CBG, Contains CBC` | 44 |
| `Contains CBD, Contains CBN, Contains CBC` | 38 |
| `Contains CBD, Contains CBG, Contains THCv` | 37 |
| `LOCKED DATA` | 31 |
| `Contains CBN, Contains CBG, Contains CBC` | 24 |
| `Contains CBG, Contains CBC, Contains THCv` | 12 |
| `Contains CBD, Contains CBG, Contains CBC, Contains THCv` | 7 |
| `Contains CBD, Contains CBN, Contains CBC, Contains THCv` | 6 |
| `Contains CBD, Contains CBN, Contains CBG, Contains THCv` | 6 |
| `Contains CBD, Contains CBC, Contains THCv` | 3 |
| `Contains CBN, Contains THCv` | 2 |
| `Contains CBD, Contains CBN, Contains CBG, Contains CBC, Contains THCv` | 1 |
| `Contains CBD, Contains CBN, Contains THCv` | 1 |
| `Contains CBN, Contains CBG, Contains THCv` | 1 |

#### `sugar_free` — 3 distinct value(s), complete list

| value | rows |
| --- | --- |
| `NULL` | 140,963 |
| `Not Sugar Free` | 39,781 |
| `Sugar Free` | 1,733 |


---

## `public.mv_category_monthly` — materialized view

### DDL

```sql
CREATE MATERIALIZED VIEW public.mv_category_monthly AS
 SELECT state,
    category_l1,
    category_l2,
    category_l3,
    fast_acting,
    mood_effect,
    cannabinoid_mix,
    sugar_free,
    period_grain,
    period_month,
    period_year,
    sum(total_retail_sales) AS total_sales,
    sum(total_units) AS total_units,
    sum(total_retail_sales) / NULLIF(sum(total_units), 0::numeric) AS dollars_per_unit
   FROM bdsa_sales
  WHERE NOT is_suppressed
  GROUP BY state, category_l1, category_l2, category_l3, fast_acting, mood_effect, cannabinoid_mix, sugar_free, period_grain, period_month, period_year;
```

**Row count:** 11,817 (exact)

### Columns

| # | column | type | null | default | comment |
| --- | --- | --- | --- | --- | --- |
| 1 | `state` | text | yes |  |  |
| 2 | `category_l1` | text | yes |  |  |
| 3 | `category_l2` | text | yes |  |  |
| 4 | `category_l3` | text | yes |  |  |
| 5 | `fast_acting` | text | yes |  |  |
| 6 | `mood_effect` | text | yes |  |  |
| 7 | `cannabinoid_mix` | text | yes |  |  |
| 8 | `sugar_free` | text | yes |  |  |
| 9 | `period_grain` | text | yes |  |  |
| 10 | `period_month` | date | yes |  |  |
| 11 | `period_year` | integer | yes |  |  |
| 12 | `total_sales` | numeric | yes |  |  |
| 13 | `total_units` | numeric | yes |  |  |
| 14 | `dollars_per_unit` | numeric | yes |  |  |

### Temporal / period columns — min & max

| column | type | min | max | non-null | null |
| --- | --- | --- | --- | --- | --- |
| `period_grain` | text | year | year | 11,817 | 0 |
| `period_month` | date | 2025-01-01 | 2026-01-01 | 11,817 | 0 |
| `period_year` | integer | 2,025 | 2,026 | 11,817 | 0 |
| `total_units` | numeric | 0.0000 | 64,629,347.8884 | 11,817 | 0 |

### Numeric columns — min, max, sum

| column | type | min | max | sum | non-null | null |
| --- | --- | --- | --- | --- | --- | --- |
| `total_sales` | numeric | 0.0000 | 1,354,373,199.9638 | 41,170,446,010.4128 | 11,817 | 0 |
| `dollars_per_unit` | numeric | 0.25500242585596077774 | 264.6482384375946891 | 290,121.10932436237847468370 | 11,816 | 1 |

### Dimension columns — distinct values (full list when < 200)

#### `state` — 37 distinct value(s), complete list

| value | rows |
| --- | --- |
| `California` | 800 |
| `New York` | 757 |
| `Massachusetts` | 727 |
| `Washington` | 725 |
| `Michigan` | 576 |
| `New Jersey` | 546 |
| `Colorado` | 498 |
| `Illinois` | 493 |
| `Oregon` | 487 |
| `Oklahoma` | 450 |
| `Arizona` | 431 |
| `New Mexico` | 392 |
| `Ohio` | 384 |
| `Maryland` | 359 |
| `Mississippi` | 347 |
| `Vermont` | 323 |
| `Nevada` | 322 |
| `Montana` | 321 |
| `Pennsylvania` | 254 |
| `Minnesota` | 248 |
| `Rhode Island` | 233 |
| `Florida` | 232 |
| `Connecticut` | 211 |
| `Utah` | 206 |
| `Maine` | 163 |
| `District of Columbia` | 151 |
| `South Dakota` | 147 |
| `Virginia` | 129 |
| `Georgia` | 127 |
| `Arkansas` | 126 |
| `Louisiana` | 123 |
| `Delaware` | 115 |
| `West Virginia` | 101 |
| `Hawaii` | 88 |
| `New Hampshire` | 79 |
| `Iowa` | 75 |
| `North Dakota` | 71 |

#### `category_l1` — 5 distinct value(s), complete list

| value | rows |
| --- | --- |
| `Ingestibles` | 7,857 |
| `Inhaleables` | 1,859 |
| `Topicals` | 1,439 |
| `All Accessories` | 572 |
| `Other Cannabis` | 90 |

#### `category_l2` — 13 distinct value(s), complete list

| value | rows |
| --- | --- |
| `Edibles` | 6,626 |
| `Topicals` | 1,439 |
| `Sublinguals` | 1,231 |
| `Vape` | 913 |
| `Flower` | 425 |
| `Devices` | 346 |
| `Extracts` | 331 |
| `Pre-Rolled` | 190 |
| `Accessories` | 141 |
| `Other Cannabis` | 90 |
| `Apparel` | 69 |
| `Non Infused Food` | 15 |
| `Grow Supplies` | 1 |

#### `category_l3` — 55 distinct value(s), complete list

| value | rows |
| --- | --- |
| `Candy` | 3,571 |
| `Tinctures` | 1,093 |
| `Pills` | 901 |
| `Beverages` | 895 |
| `Chocolates` | 666 |
| `Infused Foods` | 473 |
| `Vape Cartridge` | 466 |
| `Vape Disposable` | 447 |
| `Balms/Salves` | 312 |
| `Other Topicals` | 223 |
| `Creams` | 219 |
| `Lotions` | 199 |
| `Patches` | 174 |
| `Oil` | 134 |
| `Other` | 129 |
| `Whole Buds` | 111 |
| `Massage Oil` | 108 |
| `Pre-Rolled` | 106 |
| `Small Buds` | 91 |
| `Dissolvable` | 90 |
| `Lip Balm` | 89 |
| `Resin` | 88 |
| `Shake` | 86 |
| `Infused Pre-Rolled` | 84 |
| `Other Edibles` | 74 |
| `Solventless` | 73 |
| `Pre-Ground` | 70 |
| `Infused Flower` | 67 |
| `Lubricants` | 54 |
| `Suppositories` | 53 |
| `Pet Products` | 50 |
| `Unspecified/Other` | 43 |
| `Vaporizers` | 43 |
| `Water Pipe` | 43 |
| `Pipe` | 42 |
| `Rolling Papers` | 42 |
| `Culinary` | 39 |
| `Grinder` | 39 |
| `Clothing` | 37 |
| `Bowl` | 35 |
| `Lighter` | 34 |
| `Storage Device` | 33 |
| `Accessories` | 32 |
| `Cleaner` | 30 |
| `Rolling Machine` | 27 |
| `Sticker` | 21 |
| `Plants` | 17 |
| `NULL` | 16 |
| `Bundles/Collections` | 13 |
| `Candles` | 12 |
| `Pre-Loaded` | 10 |
| `Spray` | 7 |
| `Gum` | 4 |
| `Magnet` | 1 |
| `Soap` | 1 |

#### `fast_acting` — 3 distinct value(s), complete list

| value | rows |
| --- | --- |
| `Not Fast Acting` | 5,449 |
| `NULL` | 5,191 |
| `Fast Acting` | 1,177 |

#### `mood_effect` — 38 distinct value(s), complete list

| value | rows |
| --- | --- |
| `Not Mood Specific` | 7,120 |
| `Sleep` | 1,150 |
| `Relaxation` | 860 |
| `Energy` | 665 |
| `Happiness` | 448 |
| `Pain Relief` | 428 |
| `Focus` | 293 |
| `Balance` | 241 |
| `Intimacy` | 165 |
| `Creativity` | 95 |
| `Anytime` | 75 |
| `Elevate` | 37 |
| `Fly` | 35 |
| `LOCKED DATA` | 31 |
| `Relief` | 31 |
| `Chill` | 28 |
| `Nighttime` | 11 |
| `Happy` | 8 |
| `Restore` | 8 |
| `Calm` | 7 |
| `Boost` | 6 |
| `Bounce Back` | 6 |
| `Chill Out` | 6 |
| `Genius Mode` | 6 |
| `Recovery` | 6 |
| `Turn Down` | 6 |
| `Turn Up` | 6 |
| `Uplift` | 6 |
| `Flow` | 5 |
| `Glow` | 5 |
| `Thrive` | 5 |
| `Daytime` | 4 |
| `Slow` | 4 |
| `Play` | 3 |
| `Reset` | 3 |
| `Ease` | 2 |
| `Doze` | 1 |
| `Go` | 1 |

#### `cannabinoid_mix` — 32 distinct value(s), complete list

| value | rows |
| --- | --- |
| `THC Only` | 4,483 |
| `Contains CBD` | 1,903 |
| `Contains CBD, Contains CBN` | 848 |
| `Contains CBN` | 825 |
| `Contains CBG` | 748 |
| `Contains CBD, Contains CBG` | 684 |
| `NULL` | 561 |
| `Contains CBD, Contains CBN, Contains CBG` | 291 |
| `Contains THCv` | 267 |
| `Contains CBD, Contains CBC` | 179 |
| `Contains CBC` | 178 |
| `Contains CBG, Contains CBC` | 165 |
| `Contains CBN, Contains CBG` | 141 |
| `Contains CBG, Contains THCv` | 112 |
| `Contains CBD, Contains CBG, Contains CBC` | 95 |
| `Contains CBD, Contains THCv` | 79 |
| `Contains CBN, Contains CBC` | 42 |
| `Contains CBC, Contains THCv` | 39 |
| `Contains CBD, Contains CBG, Contains THCv` | 32 |
| `Contains CBD, Contains CBN, Contains CBC` | 32 |
| `LOCKED DATA` | 31 |
| `Contains CBD, Contains CBN, Contains CBG, Contains CBC` | 30 |
| `Contains CBN, Contains CBG, Contains CBC` | 17 |
| `Contains CBG, Contains CBC, Contains THCv` | 11 |
| `Contains CBD, Contains CBN, Contains CBC, Contains THCv` | 6 |
| `Contains CBD, Contains CBN, Contains CBG, Contains THCv` | 6 |
| `Contains CBD, Contains CBG, Contains CBC, Contains THCv` | 5 |
| `Contains CBD, Contains CBC, Contains THCv` | 2 |
| `Contains CBN, Contains THCv` | 2 |
| `Contains CBD, Contains CBN, Contains CBG, Contains CBC, Contains THCv` | 1 |
| `Contains CBD, Contains CBN, Contains THCv` | 1 |
| `Contains CBN, Contains CBG, Contains THCv` | 1 |

#### `sugar_free` — 3 distinct value(s), complete list

| value | rows |
| --- | --- |
| `Not Sugar Free` | 5,885 |
| `NULL` | 5,191 |
| `Sugar Free` | 741 |


---

## `public.bdsa_sales` — table

### DDL

```sql
CREATE TABLE public.bdsa_sales (
    period_month date,
    state text,
    category_l1 text,
    category_l2 text,
    category_l3 text,
    category_l4 text,
    category_l5 text,
    brand text,
    product text,
    pack_size text,
    infusion_type text,
    phenotype text,
    strain text,
    is_live_extract text,
    mood_effect text,
    cannabinoid_mix text,
    sugar_free text,
    fast_acting text,
    flavor text,
    total_item_weight text,
    items_per_pack numeric(12,2),
    pct_thc_potency numeric(8,4),
    total_thc_mg numeric(12,2),
    total_cbd_mg numeric(12,2),
    total_retail_sales numeric(16,4),
    total_units numeric(16,4),
    original_list_price numeric(12,4),
    source_file text,
    period_year integer,
    is_suppressed boolean DEFAULT false,
    period_grain text
);
CREATE INDEX idx_sales_brand ON public.bdsa_sales USING btree (brand);
CREATE INDEX idx_sales_category ON public.bdsa_sales USING btree (category_l1, category_l2, category_l3);
CREATE INDEX idx_sales_state_month ON public.bdsa_sales USING btree (state, period_month);
CREATE INDEX idx_sales_year ON public.bdsa_sales USING btree (period_year);
```

**Row count:** 7,338,581 (exact)

### Columns

| # | column | type | null | default | comment |
| --- | --- | --- | --- | --- | --- |
| 1 | `period_month` | date | yes |  |  |
| 2 | `state` | text | yes |  |  |
| 3 | `category_l1` | text | yes |  |  |
| 4 | `category_l2` | text | yes |  |  |
| 5 | `category_l3` | text | yes |  |  |
| 6 | `category_l4` | text | yes |  |  |
| 7 | `category_l5` | text | yes |  |  |
| 8 | `brand` | text | yes |  |  |
| 9 | `product` | text | yes |  |  |
| 10 | `pack_size` | text | yes |  |  |
| 11 | `infusion_type` | text | yes |  |  |
| 12 | `phenotype` | text | yes |  |  |
| 13 | `strain` | text | yes |  |  |
| 14 | `is_live_extract` | text | yes |  |  |
| 15 | `mood_effect` | text | yes |  |  |
| 16 | `cannabinoid_mix` | text | yes |  |  |
| 17 | `sugar_free` | text | yes |  |  |
| 18 | `fast_acting` | text | yes |  |  |
| 19 | `flavor` | text | yes |  |  |
| 20 | `total_item_weight` | text | yes |  |  |
| 21 | `items_per_pack` | numeric(12,2) | yes |  |  |
| 22 | `pct_thc_potency` | numeric(8,4) | yes |  |  |
| 23 | `total_thc_mg` | numeric(12,2) | yes |  |  |
| 24 | `total_cbd_mg` | numeric(12,2) | yes |  |  |
| 25 | `total_retail_sales` | numeric(16,4) | yes |  |  |
| 26 | `total_units` | numeric(16,4) | yes |  |  |
| 27 | `original_list_price` | numeric(12,4) | yes |  |  |
| 28 | `source_file` | text | yes |  |  |
| 29 | `period_year` | integer | yes |  |  |
| 30 | `is_suppressed` | boolean | yes | false |  |
| 31 | `period_grain` | text | yes |  |  |

### Temporal / period columns — min & max

| column | type | min | max | non-null | null |
| --- | --- | --- | --- | --- | --- |
| `period_month` | date | 2025-01-01 | 2026-01-01 | 7,338,581 | 0 |
| `total_units` | numeric(16,4) | 0.0000 | 7,158,937.2064 | 7,338,581 | 0 |
| `period_year` | integer | 2,025 | 2,026 | 7,338,581 | 0 |
| `period_grain` | text | year | year | 7,338,581 | 0 |

### Numeric columns — min, max, sum

| column | type | min | max | sum | non-null | null |
| --- | --- | --- | --- | --- | --- | --- |
| `items_per_pack` | numeric(12,2) | 0.00 | 250.00 | 13,108,065.00 | 7,338,581 | 0 |
| `pct_thc_potency` | numeric(8,4) | 0.0000 | 1.0000 | 939,267.0500 | 2,233,986 | 5,104,595 |
| `total_thc_mg` | numeric(12,2) | 0.00 | 10,000.00 | 86,623,148.00 | 7,330,627 | 7,954 |
| `total_cbd_mg` | numeric(12,2) | 0.00 | 6,000.00 | 19,302,982.00 | 7,058,747 | 279,834 |
| `total_retail_sales` | numeric(16,4) | 0.0000 | 134,536,334.8693 | 41,170,519,879.5651 | 7,338,581 | 0 |
| `original_list_price` | numeric(12,4) | 0.0000 | 9,999.0000 | 292,508,260.8183 | 7,195,772 | 142,809 |

### Dimension columns — distinct values (full list when < 200)

#### `state` — 37 distinct value(s), complete list

| value | rows |
| --- | --- |
| `California` | 1,255,917 |
| `Michigan` | 1,157,789 |
| `Washington` | 696,427 |
| `Oregon` | 564,301 |
| `Colorado` | 553,087 |
| `Oklahoma` | 494,670 |
| `Massachusetts` | 357,063 |
| `New Mexico` | 292,873 |
| `New York` | 230,344 |
| `Maine` | 190,587 |
| `Illinois` | 185,715 |
| `New Jersey` | 182,731 |
| `Arizona` | 167,388 |
| `Montana` | 135,398 |
| `Maryland` | 124,888 |
| `Nevada` | 118,243 |
| `Ohio` | 103,559 |
| `Vermont` | 98,134 |
| `Pennsylvania` | 79,787 |
| `Mississippi` | 59,207 |
| `Florida` | 58,563 |
| `South Dakota` | 33,825 |
| `Connecticut` | 32,144 |
| `Arkansas` | 29,671 |
| `District of Columbia` | 26,418 |
| `Rhode Island` | 22,532 |
| `Minnesota` | 16,271 |
| `Utah` | 14,547 |
| `West Virginia` | 14,407 |
| `Hawaii` | 8,477 |
| `Delaware` | 8,187 |
| `Louisiana` | 8,132 |
| `Virginia` | 7,743 |
| `North Dakota` | 4,915 |
| `New Hampshire` | 3,157 |
| `Georgia` | 799 |
| `Iowa` | 685 |

#### `category_l1` — 5 distinct value(s), complete list

| value | rows |
| --- | --- |
| `Inhaleables` | 6,923,793 |
| `Ingestibles` | 355,745 |
| `Topicals` | 28,551 |
| `All Accessories` | 28,337 |
| `Other Cannabis` | 2,155 |

#### `category_l2` — 13 distinct value(s), complete list

| value | rows |
| --- | --- |
| `Flower` | 3,261,596 |
| `Pre-Rolled` | 1,596,685 |
| `Vape` | 1,113,102 |
| `Extracts` | 952,410 |
| `Edibles` | 326,554 |
| `Sublinguals` | 29,191 |
| `Topicals` | 28,551 |
| `Devices` | 19,161 |
| `Accessories` | 5,214 |
| `Apparel` | 3,893 |
| `Other Cannabis` | 2,155 |
| `Non Infused Food` | 68 |
| `Grow Supplies` | 1 |

#### `category_l3` — 55 distinct value(s), complete list

| value | rows |
| --- | --- |
| `Whole Buds` | 2,574,490 |
| `Pre-Rolled` | 862,274 |
| `Infused Pre-Rolled` | 734,411 |
| `Resin` | 667,613 |
| `Vape Cartridge` | 626,875 |
| `Vape Disposable` | 486,227 |
| `Small Buds` | 378,903 |
| `Solventless` | 237,865 |
| `Candy` | 215,554 |
| `Shake` | 170,856 |
| `Infused Flower` | 86,280 |
| `Pre-Ground` | 51,067 |
| `Oil` | 45,354 |
| `Beverages` | 40,216 |
| `Tinctures` | 28,632 |
| `Chocolates` | 27,397 |
| `Pills` | 22,497 |
| `Infused Foods` | 19,811 |
| `Balms/Salves` | 12,899 |
| `Water Pipe` | 5,791 |
| `Vaporizers` | 4,998 |
| `Other Topicals` | 4,439 |
| `Other` | 4,138 |
| `Creams` | 3,936 |
| `Pipe` | 3,227 |
| `Lotions` | 3,075 |
| `Clothing` | 2,877 |
| `Patches` | 2,597 |
| `Rolling Papers` | 2,432 |
| `Grinder` | 1,738 |
| `Unspecified/Other` | 1,588 |
| `Lighter` | 1,349 |
| `Plants` | 1,322 |
| `Accessories` | 1,016 |
| `Other Edibles` | 910 |
| `Massage Oil` | 602 |
| `Lip Balm` | 579 |
| `Pet Products` | 501 |
| `Dissolvable` | 399 |
| `Lubricants` | 302 |
| `Bundles/Collections` | 283 |
| `Storage Device` | 244 |
| `Sticker` | 195 |
| `Culinary` | 159 |
| `Rolling Machine` | 146 |
| `Bowl` | 139 |
| `Cleaner` | 115 |
| `Suppositories` | 111 |
| `NULL` | 69 |
| `Pre-Loaded` | 49 |
| `Candles` | 15 |
| `Spray` | 10 |
| `Gum` | 6 |
| `Magnet` | 2 |
| `Soap` | 1 |

#### `category_l4` — 84 distinct value(s), complete list

| value | rows |
| --- | --- |
| `NULL` | 4,897,277 |
| `Distillate Cartridge` | 287,827 |
| `Distillate Disposable` | 210,575 |
| `Gummie Candy` | 204,268 |
| `Rosin` | 197,730 |
| `Live Resin Cartridge` | 187,428 |
| `Badder` | 165,961 |
| `Live Resin Disposable` | 165,575 |
| `Resin` | 157,116 |
| `Sugar` | 94,819 |
| `Oil Cartridge` | 90,939 |
| `Wax` | 80,197 |
| `Shatter` | 78,281 |
| `Rosin Disposable` | 64,705 |
| `Rosin Cartridge` | 54,761 |
| `Oil Disposable` | 45,341 |
| `Diamonds` | 29,350 |
| `Sauce` | 28,457 |
| `Drinks` | 28,038 |
| `Chocolates` | 27,397 |
| `Dropper` | 27,078 |
| `Crumble` | 26,875 |
| `RSO` | 23,023 |
| `Hash` | 18,351 |
| `Oil` | 15,071 |
| `Bubble Hash` | 13,128 |
| `Tablet` | 11,865 |
| `Baked Goods` | 10,631 |
| `Capsule` | 8,705 |
| `Kief` | 8,656 |
| `Distillate` | 7,378 |
| `Syrup` | 7,160 |
| `Crystalline` | 6,557 |
| `Shots` | 6,227 |
| `Kit` | 5,943 |
| `Mints` | 5,172 |
| `Pen/ Hand Held` | 4,814 |
| `Oil/ Hash Dab Rig` | 3,553 |
| `Taffy` | 2,814 |
| `Powdered Mix` | 2,705 |
| `Hard Candy` | 2,158 |
| `Spoon` | 2,002 |
| `Tshirts` | 1,968 |
| `Softgel` | 1,927 |
| `Other Beverages` | 1,869 |
| `Unspecified/Other` | 1,587 |
| `Bubbler` | 1,488 |
| `Tea` | 1,281 |
| `Other Infused Foods` | 1,274 |
| `Disposable` | 1,242 |
| `Chillum` | 1,101 |
| `Hat` | 1,015 |
| `Other Tinctures` | 852 |
| `Hoodie` | 835 |
| `Caramel Candy` | 746 |
| `Oral Spray` | 702 |
| `Accessory` | 677 |
| `Seeds` | 667 |
| `Clones` | 655 |
| `Honey` | 576 |
| `Other` | 437 |
| `Other Candy` | 396 |
| `Tablets` | 235 |
| `Orally Disolvable Strips` | 164 |
| `Spreads` | 151 |
| `Table Top` | 117 |
| `Dab Rig` | 107 |
| `Torch` | 103 |
| `Lockable` | 101 |
| `Coffee Products` | 96 |
| `Unspecified Cartridge` | 74 |
| `Bong` | 73 |
| `Soft` | 47 |
| `Flower` | 32 |
| `Butter` | 26 |
| `Ice Cream` | 19 |
| `Other Culinary` | 15 |
| `Humidor` | 6 |
| `Butane` | 4 |
| `Jar` | 4 |
| `Bandana` | 1 |
| `Inhaler` | 1 |
| `Pants` | 1 |
| `Unspecified Disposable` | 1 |

#### `category_l5` — 31 distinct value(s), complete list

| value | rows |
| --- | --- |
| `NULL` | 7,244,416 |
| `Carbonated Drinks` | 20,283 |
| `Chocolate Bars` | 18,766 |
| `Chocolate Pieces` | 8,237 |
| `Noncarbonated Drinks` | 7,755 |
| `Shots` | 6,227 |
| `Other Baked Goods` | 6,063 |
| `Hard Mints` | 4,910 |
| `Rechargeable Battery` | 4,445 |
| `Cookies` | 3,817 |
| `Powdered Mix` | 2,705 |
| `Accessory` | 2,397 |
| `Other Beverages` | 1,869 |
| `Lozenges` | 1,682 |
| `Hash Dab Rig` | 1,188 |
| `Dry Tea` | 1,104 |
| `Brownies` | 751 |
| `Lollipop` | 476 |
| `Other Chocolates` | 394 |
| `Replacement Parts and Accessories` | 346 |
| `Chewable Mints` | 262 |
| `Tea Drink` | 177 |
| `Concentrate` | 114 |
| `Coffee Drink` | 78 |
| `Tools` | 45 |
| `Dab Rig` | 30 |
| `Disposable Battery` | 24 |
| `Coffee` | 14 |
| `Creamer` | 4 |
| `Flower` | 1 |
| `Flower and Concentrate` | 1 |

#### `brand` — high cardinality (> 200 distinct); top 15 by row count

| value | rows |
| --- | --- |
| `Generic` | 1,260,364 |
| `Cookies` | 32,628 |
| `Stiiizy` | 30,605 |
| `Select` | 25,997 |
| `Rythm` | 24,751 |
| `Jeeter` | 23,899 |
| `High Supply` | 23,422 |
| `710 Labs` | 18,867 |
| `Phat Panda` | 18,196 |
| `ROVE Brands` | 17,002 |
| `Grassroots Cannabis` | 16,690 |
| `Find.` | 16,653 |
| `Savvy` | 16,602 |
| `Raw Garden` | 15,869 |
| `Punch` | 13,456 |

#### `product` — high cardinality (> 200 distinct); top 15 by row count

| value | rows |
| --- | --- |
| `Generic - Hybrid Strain Blends - Pre-Rolled, 1g, 1 Count` | 776 |
| `Generic - Hybrid Strain Blends - Infused Pre-Rolled, 1g, 1 Count` | 704 |
| `Generic - Hybrid Strain Blends - Flower - Whole Buds (3.5g)` | 632 |
| `Generic - Hybrid Strain Blends - Distillate Cartridge, 1000mg, 1 Count` | 615 |
| `Generic - Indica Strain Blends - Flower - Whole Buds (3.5g)` | 612 |
| `Generic - Hybrid Strain Blends - Live Resin Disposable, 1000mg, 1 Count` | 555 |
| `Generic - Hybrid Strain Blends - Distillate Disposable, 1000mg, 1 Count` | 454 |
| `Generic - Hybrid Strain Blends - Live Resin Cartridge, 1000mg, 1 Count` | 454 |
| `Generic - Hybrid Strain Blends - Oil Cartridge, 1000mg, 1 Count` | 453 |
| `Generic - Hybrid Strain Blends - Badder - (1g)` | 441 |
| `Generic - Indica Strain Blends - Flower - Whole Buds (14g)` | 437 |
| `Generic - Hybrid Strain Blends - Rosin - (1g)` | 416 |
| `Generic - Indica Strain Blends - Flower - Whole Buds (7g)` | 409 |
| `Generic - Indica Strain Blends - Flower - Whole Buds (28g)` | 395 |
| `Generic - Hybrid Strain Blends - Shatter - (1g)` | 393 |

#### `pack_size` — high cardinality (> 200 distinct); top 15 by row count

| value | rows |
| --- | --- |
| `1g` | 1,481,049 |
| `3.5g` | 911,944 |
| `1000mg` | 744,816 |
| `14g` | 630,955 |
| `28g` | 542,747 |
| `7g` | 536,530 |
| `2g` | 279,191 |
| `100mg THC` | 165,991 |
| `500mg` | 161,345 |
| `2x1g` | 131,068 |
| `2000mg` | 119,603 |
| `5x0.5g` | 108,372 |
| `2x0.5g` | 69,061 |
| `4g` | 68,402 |
| `5x1g` | 59,794 |

#### `infusion_type` — 34 distinct value(s), complete list

| value | rows |
| --- | --- |
| `NULL` | 6,666,212 |
| `Distillate` | 277,732 |
| `Diamonds` | 92,982 |
| `Rosin` | 57,714 |
| `Live Resin` | 38,400 |
| `Hash` | 34,831 |
| `Moonrocks` | 29,701 |
| `Bubble Hash` | 24,264 |
| `Resin` | 23,493 |
| `Live Rosin` | 21,520 |
| `Kief` | 15,501 |
| `Oil` | 15,029 |
| `RSO` | 10,464 |
| `Live Diamonds` | 4,945 |
| `Shatter` | 4,566 |
| `Sugar` | 4,344 |
| `Crumble` | 2,678 |
| `Crystalline` | 2,386 |
| `Badder` | 2,203 |
| `Sauce` | 2,131 |
| `Live Hash` | 1,866 |
| `Wax` | 1,574 |
| `Live Bubble Hash` | 1,074 |
| `Live Moonrocks` | 831 |
| `Live Badder` | 579 |
| `Live Crystalline` | 452 |
| `Live Sauce` | 388 |
| `Live Sugar` | 254 |
| `Live RSO` | 155 |
| `Live Kief` | 152 |
| `Live Oil` | 87 |
| `Live Crumble` | 30 |
| `Live Shatter` | 29 |
| `Live Wax` | 14 |

#### `phenotype` — 5 distinct value(s), complete list

| value | rows |
| --- | --- |
| `NULL` | 2,867,087 |
| `Indica` | 2,365,407 |
| `Hybrid` | 1,462,593 |
| `Sativa` | 503,649 |
| `CBD` | 139,845 |

#### `strain` — high cardinality (> 200 distinct); top 15 by row count

| value | rows |
| --- | --- |
| `NULL` | 1,595,950 |
| `Indica Strain Blends` | 92,397 |
| `Hybrid Strain Blends` | 80,198 |
| `Blue Dream` | 47,746 |
| `Lemon Cherry Gelato` | 32,501 |
| `Super Boof` | 26,367 |
| `Wedding Cake` | 24,260 |
| `Ice Cream Cake` | 23,679 |
| `Runtz` | 22,979 |
| `GMO` | 22,780 |
| `Permanent Marker` | 21,532 |
| `Sour Diesel` | 21,080 |
| `Sativa Strain Blends` | 19,697 |
| `Gelato` | 19,590 |
| `Pineapple Express` | 19,502 |

#### `is_live_extract` — 4 distinct value(s), complete list

| value | rows |
| --- | --- |
| `NULL` | 6,924,970 |
| `Live` | 312,491 |
| `Not Live` | 101,049 |
| `LOCKED DATA` | 71 |

#### `mood_effect` — 38 distinct value(s), complete list

| value | rows |
| --- | --- |
| `Not Mood Specific` | 7,298,890 |
| `Sleep` | 14,459 |
| `Relaxation` | 7,746 |
| `Energy` | 5,797 |
| `Happiness` | 4,177 |
| `Focus` | 1,861 |
| `Pain Relief` | 1,637 |
| `Balance` | 1,525 |
| `Intimacy` | 663 |
| `Creativity` | 568 |
| `Anytime` | 270 |
| `Slow` | 120 |
| `Flow` | 115 |
| `Glow` | 104 |
| `Relief` | 74 |
| `LOCKED DATA` | 71 |
| `Elevate` | 57 |
| `Fly` | 56 |
| `Nighttime` | 56 |
| `Chill` | 55 |
| `Recovery` | 41 |
| `Turn Down` | 40 |
| `Turn Up` | 32 |
| `Chill Out` | 29 |
| `Daytime` | 27 |
| `Genius Mode` | 26 |
| `Bounce Back` | 24 |
| `Happy` | 15 |
| `Restore` | 8 |
| `Calm` | 7 |
| `Uplift` | 7 |
| `Boost` | 6 |
| `Thrive` | 6 |
| `Ease` | 3 |
| `Play` | 3 |
| `Reset` | 3 |
| `Doze` | 2 |
| `Go` | 1 |

#### `cannabinoid_mix` — 32 distinct value(s), complete list

| value | rows |
| --- | --- |
| `THC Only` | 7,216,500 |
| `Contains CBD` | 53,445 |
| `NULL` | 28,315 |
| `Contains CBN` | 11,019 |
| `Contains CBD, Contains CBN` | 9,771 |
| `Contains CBG` | 6,396 |
| `Contains CBD, Contains CBG` | 4,563 |
| `Contains THCv` | 2,483 |
| `Contains CBD, Contains CBN, Contains CBG` | 1,605 |
| `Contains CBC` | 916 |
| `Contains CBD, Contains CBC` | 759 |
| `Contains CBG, Contains CBC` | 648 |
| `Contains CBN, Contains CBG` | 485 |
| `Contains CBD, Contains CBG, Contains CBC` | 381 |
| `Contains CBG, Contains THCv` | 379 |
| `Contains CBD, Contains THCv` | 308 |
| `Contains CBC, Contains THCv` | 155 |
| `Contains CBN, Contains CBC` | 119 |
| `Contains CBD, Contains CBN, Contains CBG, Contains CBC` | 75 |
| `LOCKED DATA` | 71 |
| `Contains CBD, Contains CBG, Contains THCv` | 51 |
| `Contains CBD, Contains CBN, Contains CBC` | 48 |
| `Contains CBN, Contains CBG, Contains CBC` | 27 |
| `Contains CBG, Contains CBC, Contains THCv` | 23 |
| `Contains CBD, Contains CBN, Contains CBG, Contains THCv` | 14 |
| `Contains CBD, Contains CBG, Contains CBC, Contains THCv` | 7 |
| `Contains CBD, Contains CBC, Contains THCv` | 6 |
| `Contains CBD, Contains CBN, Contains CBC, Contains THCv` | 6 |
| `Contains CBN, Contains THCv` | 3 |
| `Contains CBD, Contains CBN, Contains CBG, Contains CBC, Contains THCv` | 1 |
| `Contains CBD, Contains CBN, Contains THCv` | 1 |
| `Contains CBN, Contains CBG, Contains THCv` | 1 |

#### `sugar_free` — 3 distinct value(s), complete list

| value | rows |
| --- | --- |
| `NULL` | 7,012,027 |
| `Not Sugar Free` | 319,811 |
| `Sugar Free` | 6,743 |

#### `fast_acting` — 3 distinct value(s), complete list

| value | rows |
| --- | --- |
| `NULL` | 7,012,027 |
| `Not Fast Acting` | 311,648 |
| `Fast Acting` | 14,906 |

#### `flavor` — high cardinality (> 200 distinct); top 15 by row count

| value | rows |
| --- | --- |
| `NULL` | 7,012,027 |
| `Generic` | 41,837 |
| `Watermelon` | 7,259 |
| `N/A` | 6,229 |
| `Strawberry` | 5,919 |
| `Blue Raspberry` | 4,168 |
| `Grape` | 3,911 |
| `Blueberry` | 3,591 |
| `Mango` | 3,591 |
| `Peach` | 3,200 |
| `Cherry` | 3,062 |
| `Green Apple` | 3,026 |
| `Milk Chocolate` | 3,010 |
| `Pineapple` | 2,951 |
| `Raspberry` | 2,852 |

#### `total_item_weight` — high cardinality (> 200 distinct); top 15 by row count

| value | rows |
| --- | --- |
| `1g` | 1,058,324 |
| `3.5g` | 904,638 |
| `1000mg` | 745,766 |
| `14g` | 630,954 |
| `28g` | 542,746 |
| `7g` | 536,518 |
| `1.00` | 492,005 |
| `NULL` | 414,788 |
| `2g` | 243,966 |
| `2.00` | 179,255 |
| `500mg` | 161,348 |
| `2000mg` | 123,640 |
| `2.50` | 118,802 |
| `5.00` | 99,904 |
| `3.50` | 86,518 |

#### `source_file` — 77 distinct value(s), complete list

| value | rows |
| --- | --- |
| `raw_exports/Unformatted Data_MI_26.csv` | 665,245 |
| `raw_exports/Unformatted Data_MI_25.csv` | 492,544 |
| `raw_exports/Unformatted Data_CA_26Q2.csv` | 436,508 |
| `raw_exports/Unformatted Data_WA_26.csv` | 420,614 |
| `raw_exports/Unformatted Data_CO_26.csv` | 306,949 |
| `raw_exports/Unformatted Data_OR_26.csv` | 299,915 |
| `raw_exports/Unformatted Data_OK_25.csv` | 289,121 |
| `raw_exports/Unformatted Data_WA_25.csv` | 275,813 |
| `raw_exports/Unformatted Data_OR_25.csv` | 264,386 |
| `raw_exports/Unformatted Data_CO_25.csv` | 246,138 |
| `raw_exports/Unformatted Data_MA_26.csv` | 214,311 |
| `raw_exports/Unformatted Data_OK_26.csv` | 205,549 |
| `raw_exports/Unformatted Data_CA_25Q1.csv` | 180,916 |
| `raw_exports/Unformatted Data_CA_25Q2.csv` | 176,198 |
| `raw_exports/Unformatted Data_NM_26.csv` | 158,017 |
| `raw_exports/Unformatted Data_CA_25Q4.csv` | 154,404 |
| `raw_exports/Unformatted Data_CA_25Q3.csv` | 154,068 |
| `raw_exports/Unformatted Data_CA_26Q1.csv` | 153,823 |
| `raw_exports/Unformatted Data_NY_26.csv` | 144,391 |
| `raw_exports/Unformatted Data_MA_25.csv` | 142,752 |
| `raw_exports/Unformatted Data_NM_25.csv` | 134,856 |
| `raw_exports/Unformatted Data_IL_26.csv` | 128,085 |
| `raw_exports/Unformatted Data_NJ_26.csv` | 114,952 |
| `raw_exports/Unformatted Data_ME_26.csv` | 112,582 |
| `raw_exports/Unformatted Data_AZ_26.csv` | 90,649 |
| `raw_exports/Unformatted Data_NY_25.csv` | 85,953 |
| `raw_exports/Unformatted Data_MD_26.csv` | 81,238 |
| `raw_exports/Unformatted Data_ME_25.csv` | 78,005 |
| `raw_exports/Unformatted Data_AZ_25.csv` | 76,739 |
| `raw_exports/Unformatted Data_MT_26.csv` | 76,697 |
| `raw_exports/Unformatted Data_NV_26.csv` | 68,446 |
| `raw_exports/Unformatted Data_NJ_25.csv` | 67,779 |
| `raw_exports/Unformatted Data_OH_26.csv` | 62,084 |
| `raw_exports/Unformatted Data_MT_25.csv` | 58,701 |
| `raw_exports/Unformatted Data_IL_25.csv` | 57,630 |
| `raw_exports/Unformatted Data_VT_26.csv` | 53,303 |
| `raw_exports/Unformatted Data_PA_26.csv` | 50,865 |
| `raw_exports/Unformatted Data_NV_25.csv` | 49,797 |
| `raw_exports/Unformatted Data_VT_25.csv` | 44,831 |
| `raw_exports/Unformatted Data_MD_25.csv` | 43,650 |
| `raw_exports/Unformatted Data_OH_25.csv` | 41,475 |
| `raw_exports/Unformatted Data_FL_26.csv` | 37,787 |
| `raw_exports/Unformatted Data_MS_26.csv` | 31,548 |
| `raw_exports/Unformatted Data_AR_26.csv` | 29,671 |
| `raw_exports/Unformatted Data_PA_25.csv` | 28,922 |
| `raw_exports/Unformatted Data_MS_25.csv` | 27,659 |
| `raw_exports/Unformatted Data_FL_25.csv` | 20,776 |
| `raw_exports/Unformatted Data_CT_26.csv` | 18,078 |
| `raw_exports/Unformatted Data_SD_26.csv` | 17,598 |
| `raw_exports/Unformatted Data_DC_26.csv` | 17,569 |
| `raw_exports/Unformatted Data_SD_25.csv` | 16,227 |
| `raw_exports/Unformatted Data_CT_25.csv` | 14,066 |
| `raw_exports/Unformatted Data_RI_25.csv` | 12,220 |
| `raw_exports/Unformatted Data_MN_26.csv` | 11,745 |
| `raw_exports/Unformatted Data_RI_26.csv` | 10,312 |
| `raw_exports/Unformatted Data_DC_25.csv` | 8,849 |
| `raw_exports/Unformatted Data_WV_26.csv` | 8,096 |
| `raw_exports/Unformatted Data_UT_26.csv` | 7,994 |
| `raw_exports/Unformatted Data_UT_25.csv` | 6,553 |
| `raw_exports/Unformatted Data_WV_25.csv` | 6,311 |
| `raw_exports/Unformatted Data_LA_26.csv` | 5,733 |
| `raw_exports/Unformatted Data_HI_26.csv` | 5,493 |
| `raw_exports/Unformatted Data_DE_26.csv` | 5,090 |
| `raw_exports/Unformatted Data_VA_26.csv` | 4,538 |
| `raw_exports/Unformatted Data_MN_25.csv` | 4,526 |
| `raw_exports/Unformatted Data_VA_25.csv` | 3,205 |
| `raw_exports/Unformatted Data_DE_25.csv` | 3,097 |
| `raw_exports/Unformatted Data_HI_25.csv` | 2,984 |
| `raw_exports/Unformatted Data_ND_26.csv` | 2,892 |
| `raw_exports/Unformatted Data_LA_25.csv` | 2,399 |
| `raw_exports/Unformatted Data_ND_25.csv` | 2,023 |
| `raw_exports/Unformatted Data_NH_26.csv` | 1,792 |
| `raw_exports/Unformatted Data_NH_25.csv` | 1,365 |
| `raw_exports/Unformatted Data_GA_26.csv` | 441 |
| `raw_exports/Unformatted Data_GA_25.csv` | 358 |
| `raw_exports/Unformatted Data_IA_26.csv` | 356 |
| `raw_exports/Unformatted Data_IA_25.csv` | 329 |

#### `is_suppressed` — 2 distinct value(s), complete list

| value | rows |
| --- | --- |
| `False` | 7,317,030 |
| `True` | 21,551 |


---

## `public.playing_with_neon` — table

### DDL

```sql
CREATE TABLE public.playing_with_neon (
    id integer DEFAULT nextval('playing_with_neon_id_seq'::regclass) NOT NULL,
    name text NOT NULL,
    value real,
    CONSTRAINT playing_with_neon_id_not_null NOT NULL id,
    CONSTRAINT playing_with_neon_name_not_null NOT NULL name,
    CONSTRAINT playing_with_neon_pkey PRIMARY KEY (id)
);
CREATE UNIQUE INDEX playing_with_neon_pkey ON public.playing_with_neon USING btree (id);
```

**Row count:** 20 (exact)

### Columns

| # | column | type | null | default | comment |
| --- | --- | --- | --- | --- | --- |
| 1 | `id` | integer | NO | nextval('playing_with_neon_id_seq'::regclass) |  |
| 2 | `name` | text | NO |  |  |
| 3 | `value` | real | yes |  |  |

### Numeric columns — min, max, sum

| column | type | min | max | sum | non-null | null |
| --- | --- | --- | --- | --- | --- | --- |
| `id` | integer | 1 | 20 | 210 | 20 | 0 |
| `value` | real | 0.0639 | 0.9585 | 12.3822 | 20 | 0 |

### Dimension columns — distinct values (full list when < 200)

#### `name` — 10 distinct value(s), complete list

| value | rows |
| --- | --- |
| `1679091c5a` | 2 |
| `45c48cce2e` | 2 |
| `8f14e45fce` | 2 |
| `a87ff679a2` | 2 |
| `c4ca4238a0` | 2 |
| `c81e728d9d` | 2 |
| `c9f0f895fb` | 2 |
| `d3d9446802` | 2 |
| `e4da3b7fbb` | 2 |
| `eccbc87e4b` | 2 |

