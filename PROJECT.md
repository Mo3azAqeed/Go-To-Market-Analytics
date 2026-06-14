# Olist GTM Analytics

Analytics infrastructure for the go-to-market motion of a two-sided e-commerce marketplace. Source systems are **Attio** (CRM — leads, closed deals, sales activity) and a **production operational database** (orders, items, sellers, payments, reviews). Both are ingested into BigQuery via Airbyte custom connectors and modeled with dbt, Cube, and Nao.

This file is the canonical context for any human or AI agent working in this repo. If something in code disagrees with this file, this file wins until updated.

---

## 1. Business problem

The GTM team needs to answer three questions, repeatedly and reliably:

1. **Funnel performance.** How does a marketing-qualified lead (MQL) convert to a closed deal, to a first order, to repeat orders, broken down by lead source, segment, and behaviour profile?
2. **Time to seller profitability.** From the day a deal is closed, how many days until cumulative commission revenue from that seller covers the estimated cost to acquire them (CAC)?
3. **Partner program eligibility.** Which active sellers qualify for the partner program, based on quality gates (review score, cancellation rate, delivery performance) and a weighted tier score (GMV velocity, growth, category fit)?

Every model, metric, ingestion stream, and agent rule in this repo exists to serve one of those three questions.

---

## 2. Stack

| Layer            | Tool                                        | Role                                                                            |
|------------------|---------------------------------------------|---------------------------------------------------------------------------------|
| Source systems   | Attio, production ops DB                    | Systems of record. Attio = CRM/funnel. Ops DB = orders, items, sellers.         |
| Ingestion        | Airbyte (self-hosted) + custom connectors   | `source-attio` and `source-ops` land raw data into BigQuery.                    |
| Storage / compute| BigQuery                                    | Raw, staging, and modeled tables. Project: `<gcp-project-id>`.                  |
| Transformation   | dbt-core (BigQuery adapter)                 | All SQL that produces tables/views. Lineage, tests, docs.                       |
| Semantic layer   | Cube (self-hosted Core)                     | Single definition of every business metric. Compiles to SQL against BigQuery.   |
| Agent runtime    | Nao (self-hosted)                           | Reads warehouse schema + dbt repo + Cube model as context. Answers questions.   |
| LLM              | Kimi (via OpenRouter)                       | Reasoning engine for Nao. BYO key.                                              |
| CI/CD            | GitHub Actions + Copilot                    | Four workflows: Airbyte CI, dbt CI, Nao CI, nightly freshness check.            |

**Layer rule.** Airbyte ingests, dbt transforms, Cube defines, Nao answers. Each layer owns exactly one job. No business logic in Airbyte. No metric definitions in dbt models. No transformations in Cube. No domain facts hardcoded in agent prompts.

---

## 3. Repository layout

```
.
├── PROJECT.md
├── airbyte/
│   ├── connectors/
│   │   ├── source-attio/
│   │   │   ├── source_attio/        ← Python CDK package
│   │   │   ├── unit_tests/
│   │   │   ├── integration_tests/
│   │   │   ├── acceptance-test-config.yml
│   │   │   ├── metadata.yaml
│   │   │   ├── Dockerfile
│   │   │   ├── requirements.txt
│   │   │   └── README.md
│   │   └── source-ops/
│   │       └── ... (same structure)
│   ├── connections/
│   │   ├── attio_to_bigquery.yaml   ← connection config (streams, schedule, normalization)
│   │   └── ops_to_bigquery.yaml
│   └── README.md
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles/
│   ├── models/
│   │   ├── staging/
│   │   │   ├── attio/               ← stg_attio__*.sql
│   │   │   └── ops/                 ← stg_ops__*.sql
│   │   ├── intermediate/
│   │   └── marts/
│   │       ├── core/                ← dim_*, fct_*
│   │       └── gtm/                 ← seller_lifecycle, cohort_payback, partner_scorecard
│   ├── sources.yml                  ← declares raw_attio.* and raw_ops.* with freshness SLAs
│   ├── tests/
│   ├── macros/
│   └── seeds/
├── cube/
│   ├── model/
│   │   ├── cubes/
│   │   └── views/
│   └── cube.py
├── nao/
│   ├── nao_config.yaml
│   ├── RULES.md
│   ├── docs/
│   │   ├── business_defs.md
│   │   └── glossary.md
│   ├── queries/
│   │   └── example_queries.md
│   └── tests/
│       └── question_set.yaml
├── .github/
│   └── workflows/
│       ├── airbyte_ci.yml           ← connector tests + build + publish image
│       ├── dbt_ci.yml               ← compile, parse, build, test on PR
│       ├── nao_ci.yml               ← runs nao test on changes to /nao or /cube
│       ├── freshness.yml            ← nightly source freshness check
│       └── copilot_review.yml       ← Copilot PR review hook
└── README.md
```

---

## 4. Data sources and ingestion

### 4.1 Attio (`source-attio` → `raw_attio`)

Built with the Airbyte Python CDK. Authenticates via Attio API token (stored as a GitHub Actions secret and Airbyte connector secret; never committed).

Streams pulled from Attio:

| Stream             | Attio object        | Sync mode                | Cursor field      | Notes                                                                  |
|--------------------|---------------------|--------------------------|-------------------|------------------------------------------------------------------------|
| `mqls`             | Lists/People        | Incremental + dedup      | `last_modified`   | MQLs. Includes `mql_id`, `origin`, `first_contact_date`.               |
| `closed_deals`     | Records/Deals       | Incremental + dedup      | `last_modified`   | Won deals. Includes `mql_id`, `seller_id`, `won_date`, `business_segment`, `lead_type`. |
| `sdrs`             | Workspace members   | Full refresh + overwrite | —                 | Reps. Low cardinality.                                                  |
| `sales_activities` | Notes/Tasks         | Incremental + append     | `created_at`      | Future use — outreach activity per deal.                                |

### 4.2 Production ops DB (`source-ops` → `raw_ops`)

Built with the Airbyte Python CDK. Authenticates via service-account credentials stored in Airbyte's secret store.

| Stream         | Grain                          | Sync mode                | Cursor field   | Notes                                                                  |
|----------------|--------------------------------|--------------------------|----------------|------------------------------------------------------------------------|
| `orders`       | one row per order_id           | Incremental + dedup      | `updated_at`   | `order_status` ∈ {delivered, shipped, invoiced, canceled, ...}.        |
| `order_items`  | one row per (order_id, item)   | Incremental + dedup      | `updated_at`   | Multiple rows per order. See §6 gotcha 1.                              |
| `sellers`      | one row per seller_id          | Incremental + dedup      | `updated_at`   | The seller dimension.                                                  |
| `customers`    | one row per customer_id        | Incremental + dedup      | `updated_at`   | `customer_id` ≠ `customer_unique_id`. See §6 gotcha 6.                 |
| `products`     | one row per product_id         | Incremental + dedup      | `updated_at`   | Category in Portuguese. Translation seed in dbt.                       |
| `payments`     | one row per payment            | Incremental + append     | `created_at`   | One order can have multiple payments.                                  |
| `reviews`      | one row per review_id          | Incremental + dedup      | `updated_at`   | Sparse. Some orders have no review.                                    |
| `geolocation`  | many rows per zip prefix       | Full refresh + overwrite | —              | Static. Aggregate in staging.                                          |

### 4.3 Sync schedule and freshness SLA

- Default schedule: **every 6 hours** for `raw_ops`, **every 1 hour** for `raw_attio` (CRM moves faster).
- `dbt/sources.yml` declares freshness SLAs: `warn_after: 8 hours, error_after: 24 hours` on every raw table.
- The nightly `freshness.yml` workflow runs `dbt source freshness` and fails the build if any source breaches.

### 4.4 The cross-system bridge

`raw_attio.closed_deals.seller_id` → `raw_ops.sellers.seller_id`. This is the only join that links a lead's origin to its long-term GMV. **Treat it as a data contract.**

A dbt singular test in `dbt/tests/seller_id_bridge_integrity.sql` must fail the build if more than X% of closed deals have a `seller_id` not present in `ops.sellers`. Initial threshold: 2%. Track drift over time. When the test fails, do not silently drop orphan rows — investigate first.

---

## 5. Naming conventions

- All identifiers `snake_case`.
- Staging: `stg_<source>__<stream>` (e.g., `stg_attio__closed_deals`, `stg_ops__order_items`). One model per raw stream. Light typing, column renaming, no business logic.
- Intermediate: `int_<entity>__<purpose>`. Not exposed to Cube.
- Marts:
  - Dimensions: `dim_<entity>` (singular). `dim_seller`, not `dim_sellers`.
  - Facts: `fct_<event_or_process>`. `fct_orders`, `fct_order_items`, `fct_payments`.
  - GTM marts: business names. `seller_lifecycle`, `cohort_payback`, `partner_scorecard`.
- Surrogate keys: `<entity>_sk` (hashed). Natural keys keep their original name.
- Date columns: `<event>_at` for timestamps, `<event>_date` for dates. Always UTC.
- Boolean columns: `is_<predicate>` or `has_<thing>`.
- Cube measures: lowercase: `gmv`, `mql_conversion_rate`, `avg_time_to_first_order_days`.

---

## 6. Data gotchas (read before writing code)

1. **`order_items` is the fan-out trap.** An order with 3 items appears 3 times. If you `SUM(price)` from a join that fans out, you triple-count. Aggregate `order_items` to order grain *before* joining to `orders`.
2. **Revenue ≠ payment value.** GMV = `SUM(order_items.price)` filtered to realized order statuses. Do not use `payments.payment_value` as revenue.
3. **Commission revenue is modeled, not measured.** Use `dbt/seeds/commission_rates.csv`, default 15% per `business_segment`.
4. **CAC is modeled, not measured.** Estimated per `origin` in `dbt/seeds/cac_estimates.csv`. Sensitivity analysis is mandatory for any payback claim.
5. **Geolocation has duplicates.** Many rows per `zip_code_prefix`. Collapse in staging.
6. **`customer_id` vs `customer_unique_id`.** Repeat-customer analysis must use `customer_unique_id`.
7. **Reviews are sparse and late.** `LEFT JOIN`. Treat missing as missing, not zero.
8. **Product categories are Portuguese.** Translation seed required. Expose both names in `dim_product`.
9. **Order status filter for revenue.** `order_status IN ('delivered', 'shipped', 'invoiced')`. `canceled` is not realized.
10. **Date filters are parameterized.** Never bake in a year.
11. **Cross-system `seller_id` drift.** Attio operators paste `seller_id` manually; typos and stale IDs happen. The bridge integrity test (§4.4) runs on every dbt build.
12. **Attio schema drift.** Attio lets users add custom attributes. The `source-attio` connector pins schemas in `manifest.yaml` or `schemas/*.json`. When the source adds a field, the connector is updated in a PR. **No auto-discovery.**
13. **Airbyte JSON columns.** When Airbyte normalizes Attio nested objects, you get JSON columns in BigQuery. Use `JSON_VALUE()` in staging to flatten the fields you need. Never `SELECT *` from a JSON-heavy raw table.
14. **Airbyte `_airbyte_*` metadata.** Every raw table has `_airbyte_raw_id`, `_airbyte_extracted_at`, `_airbyte_meta`. Use `_airbyte_extracted_at` as the loaded-at timestamp for source freshness, **not** for business event times.

---

## 7. Canonical metric definitions

Implemented in Cube. Plain-English versions in `nao/docs/business_defs.md`.

| Metric                          | Definition                                                                                                          |
|---------------------------------|---------------------------------------------------------------------------------------------------------------------|
| `mql_count`                     | Distinct `mql_id` in `stg_attio__mqls`.                                                                             |
| `closed_deal_count`             | Distinct `mql_id` in `stg_attio__closed_deals`.                                                                     |
| `mql_to_close_rate`             | `closed_deal_count / mql_count`, sliced by `origin`, `lead_behaviour_profile`, `business_segment`, `cohort_month`.  |
| `active_seller`                 | Seller with ≥ 1 order in realized statuses in lookback window (default 90d).                                        |
| `gmv`                           | `SUM(order_items.price)` filtered to realized order statuses.                                                       |
| `commission_revenue`            | `gmv × commission_rate` (rate from seed, per segment).                                                              |
| `estimated_cac`                 | Per-seller CAC from the closed deal's `origin`, taken from `cac_estimates` seed.                                    |
| `days_to_first_order`           | `first_order_at - won_date`, in days. Null if no orders.                                                            |
| `days_to_payback`               | First day cumulative `commission_revenue` ≥ `estimated_cac`. Null if not yet recovered.                             |
| `avg_review_score`              | Mean `review_score` over the seller's orders.                                                                       |
| `cancellation_rate`             | `count(order_status='canceled') / count(*)` for the seller.                                                         |
| `on_time_delivery_rate`         | Share of delivered orders where `order_delivered_customer_date <= order_estimated_delivery_date`.                   |
| `partner_eligibility_score`     | Weighted composite. Weights in `cube/model/cubes/partner_eligibility.yml`. Changes require PR review.               |

---

## 8. Layer ownership rules

- **Add a new source field** (from Attio or ops DB): Airbyte connector schema first, then dbt staging, then propagate. One PR per layer, or one PR touching all layers explicitly labeled.
- **Add a new transformation**: dbt only. Update tests.
- **Add a new metric**: Cube only. Backing SQL must reference a dbt mart, never raw tables.
- **Add a new business term**: `nao/docs/business_defs.md` and `nao/docs/glossary.md`. If it implies a metric, define it in Cube first.
- **Teach the agent a new question pattern**: `nao/queries/example_queries.md` and `nao/tests/question_set.yaml`.

Violations are PR blockers.

---

## 9. CI/CD

Four GitHub Actions workflows, all required to pass before merge to `main`.

### 9.1 `airbyte_ci.yml`

Triggers on changes under `airbyte/connectors/**`.

1. `pip install -r requirements.txt` for the changed connector.
2. `pytest unit_tests/` — fast unit tests.
3. `airbyte-ci connectors --name=source-<x> test` — runs the standard Airbyte connector acceptance test suite (CAT) against fixtures.
4. `docker build` the connector image.
5. On merge to `main`: tag the image with the commit SHA and `latest`, push to GitHub Container Registry (GHCR).
6. Post a PR comment with the new image tag so Airbyte can be updated to point at it.

### 9.2 `dbt_ci.yml`

Triggers on changes under `dbt/**` or `cube/**`.

1. `dbt deps` and `dbt parse` — fail fast on syntax / ref errors.
2. `dbt build --select state:modified+ --defer --state ./prod-manifest` — only changed models and downstream.
3. `dbt test` on the same selection.
4. `cube validate` if any file under `cube/` changed.
5. Copilot posts an automated review comment summarizing model changes, new tests, and test deltas.

Required dbt tests on every mart: `unique` and `not_null` on the primary key. `relationships` on every FK. At least one custom test per fact asserting row count bounds. Plus the bridge integrity test (§4.4).

### 9.3 `nao_ci.yml`

Triggers on changes under `nao/**` or `cube/**`.

1. `nao test --suite nao/tests/question_set.yaml`.
2. Pass threshold: **≥ 90% question→answer correctness, ≥ 95% answer rate.**

### 9.4 `freshness.yml`

Nightly cron (`0 6 * * *` UTC).

1. `dbt source freshness` against all sources in `dbt/sources.yml`.
2. Fails the workflow if any source is past its `error_after` threshold.
3. Posts a Slack alert on failure.

---

## 10. What not to do

- Do not write SQL against `raw_attio.*` or `raw_ops.*` outside the staging layer.
- Do not put business logic in an Airbyte connector. Connectors *extract*. Period.
- Do not define a metric in two places.
- Do not let the agent write freeform SQL when a Cube measure exists.
- Do not hardcode dates, commission rates, CAC values, or partner weights in models.
- Do not assume the agent's training data knows this schema. Every domain term lives in `business_defs.md` or `glossary.md` or it does not exist.
- Do not merge a PR that drops `nao test` below threshold without a written justification.
- Do not enable Airbyte's "auto schema propagation" without a PR. Schema changes are reviewed.

---

## 11. Open questions and assumptions

- Commission rate 15% flat — placeholder.
- CAC estimates per origin — rough; need finance sign-off.
- Partner eligibility weights — uniform 0.25; learn from labeled historical data when available.
- Lookback for "active seller" — 90 days; product may want 30 or 180.
- Attio sync cadence of 1 hour — based on assumed pace; tighten or loosen after observing real traffic.

Each becomes a GitHub issue tagged `definition`, resolved before the metric ships to a dashboard.
