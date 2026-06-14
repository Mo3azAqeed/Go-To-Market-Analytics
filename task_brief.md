# Olist GTM Analytics — Build Plan

**ENGINEERING BRIEF**
Phase 0 through Phase 4. Acceptance test at the end.

| | |
|---|---|
| **To** | Analytics Engineer (you) |
| **From** | Tech Lead, Data & Analytics |
| **Project** | Olist GTM Analytics (two-sided marketplace) |
| **Stack** | Airbyte (custom connectors), BigQuery, dbt-core, Cube, Nao, Kimi via OpenRouter, GitHub Actions + Copilot |
| **Repo context** | See `PROJECT.md` at repo root. Source of truth for this brief. |
| **Estimated effort** | 5–7 weeks, part time. Phases are sequential. |

---

## Context

We are building the analytics infrastructure for a two-sided marketplace GTM motion. The data lives in two source systems: **Attio** (CRM — leads, closed deals, sales activity) and our **production operational database** (orders, items, sellers). Both are being migrated into BigQuery via Airbyte. From there, dbt transforms, Cube defines, and Nao answers.

The GTM team needs three questions answered repeatedly and reliably: how the funnel converts, how long it takes a seller to become profitable, and which sellers qualify for the partner program. Read `PROJECT.md` §1 before you start. If anything in this brief contradicts `PROJECT.md`, `PROJECT.md` wins and you raise it with me.

## Objective

Deliver a working stack where a GTM operator can ask the agent a question in Slack and get a correct, governed answer to any of the questions in the acceptance test below. Correct means: the number matches the ground-truth SQL we will review together, and the agent can explain which Cube measure and dimensions it used. The pipeline must be **operationally honest** — it ingests from real source systems on a schedule, tests its own freshness, and fails loudly when it shouldn't be trusted.

## Scope

### In scope

- Two Airbyte custom connectors: `source-attio` (CRM) and `source-ops` (production DB).
- Both landing data into BigQuery under `raw_attio` and `raw_ops`.
- dbt models: staging, intermediate where needed, core marts, GTM marts.
- Cube semantic layer covering sellers, funnel, orders, and partner eligibility.
- Nao agent context (config, rules, business definitions, example queries, test suite).
- CI/CD via GitHub Actions: four workflows (Airbyte, dbt, Nao, freshness). Copilot for automated PR review.
- A short written analysis (≤ 5 pages) covering funnel, payback, and partner eligibility findings.

### Out of scope

- Production BI dashboards. The agent is the interface.
- Real-time streaming. Hourly Attio sync, 6-hour ops sync is fine.
- Customer-facing embedded analytics.
- Anything that requires data we do not have (real CAC, real commission rates). Use the seed-based placeholders defined in `PROJECT.md` §6 and §7.

---

## Phases and deliverables

Each phase ends with a concrete deliverable I can review. **Do not start phase N+1 until phase N is merged.**

### Phase 0 — Ingestion (Airbyte custom connectors)

**Target duration:** 1.5 weeks.

Build the data ingestion that everything else depends on. Without this phase, you have no pipeline — only files. The goal is two production-grade Airbyte connectors that sync on a schedule and land typed data into BigQuery.

**Tasks**

1. Stand up Airbyte self-hosted (Docker Compose locally for dev; we can decide on production deployment later). Document the setup in `airbyte/README.md`.
2. Scaffold `airbyte/connectors/source-attio/` using the Airbyte Python CDK (`airbyte-ci connectors generate`). Implement the four streams listed in `PROJECT.md` §4.1: `mqls`, `closed_deals`, `sdrs`, `sales_activities`. Use incremental + dedup mode for the first two; full refresh for `sdrs`; incremental + append for `sales_activities`.
3. Pin Attio schemas explicitly in `source_attio/schemas/*.json`. No auto-discovery (see `PROJECT.md` §6 gotcha 12).
4. Write `unit_tests/` covering: stream listing, schema validation, incremental cursor logic, pagination, and one auth failure case.
5. Write `acceptance-test-config.yml` and run `airbyte-ci connectors --name=source-attio test`. Make it pass.
6. Repeat steps 2–5 for `source-ops` with the eight streams in `PROJECT.md` §4.2. The ops connector is mostly database-driven; if the source is Postgres, you may extend Airbyte's existing Postgres source rather than write from scratch — call this out in the PR.
7. Configure two Airbyte connections in `airbyte/connections/`: `attio_to_bigquery.yaml` (hourly) and `ops_to_bigquery.yaml` (every 6 hours). Destinations land in `raw_attio` and `raw_ops` datasets in BigQuery.
8. Trigger one full sync of each connector. Confirm row counts match expectations and `_airbyte_extracted_at` populates correctly.
9. Build `.github/workflows/airbyte_ci.yml` per `PROJECT.md` §9.1. The workflow must: install deps, run unit tests, run the Airbyte connector acceptance test suite (CAT), build the Docker image, and on merge to `main` push to GHCR tagged with the commit SHA.
10. Store all secrets (Attio API token, ops DB credentials, GHCR token) as GitHub Actions secrets and as Airbyte connector secrets. Nothing committed.

**Phase 0 deliverable**

- A merged PR titled `feat(airbyte): source-attio and source-ops connectors` containing both connectors, all tests passing, CI green, and one successful sync of each visible in the Airbyte UI.
- `airbyte/README.md` explaining how to run the connectors locally and how to bump versions in production.

### Phase 1 — dbt foundation

**Target duration:** 1.5 weeks.

**Tasks**

1. Initialize the dbt project per `PROJECT.md` §3. Configure profiles for local and CI.
2. Write `dbt/sources.yml` declaring `raw_attio.*` and `raw_ops.*` as sources, with `freshness: warn_after: 8 hours, error_after: 24 hours` on each table.
3. Build staging models, one per raw stream (`stg_attio__*` and `stg_ops__*`). Light typing, column renaming to `snake_case`, no business logic. Use `JSON_VALUE()` to flatten any Attio JSON columns (see `PROJECT.md` §6 gotcha 13). Apply the geolocation collapse from gotcha 5.
4. Build core marts: `dim_seller`, `dim_customer`, `dim_product`, `dim_date`, `fct_orders` (order grain), `fct_order_items` (item grain), `fct_payments`, `fct_reviews`.
5. Build the GTM marts: `seller_lifecycle` (one row per seller, with stamped dates for `closed_deal`, `first_order`, `payback_reached`, `last_order`) and `cohort_payback` (one row per seller-day, with cumulative commission and cumulative CAC).
6. Write the bridge integrity test in `dbt/tests/seller_id_bridge_integrity.sql` (see `PROJECT.md` §4.4). Threshold: 2%.
7. Add the standard test suite from `PROJECT.md` §9.2: `unique` + `not_null` on every mart's primary key, `relationships` tests on every FK, and one bounds test per fact.
8. Build `.github/workflows/dbt_ci.yml`: `deps`, `parse`, `build --select state:modified+`, `test`. Wire Copilot for PR review comments.
9. Build `.github/workflows/freshness.yml`: nightly cron, `dbt source freshness`, Slack alert on failure.

**Phase 1 deliverable**

- A merged PR titled `feat(dbt): foundation` with the dbt project, all staging and mart models, tests passing, CI green.
- A short `README` in `/dbt` explaining how to run it locally and how to interpret `dbt source freshness` output.

### Phase 2 — Cube semantic layer

**Target duration:** 1 week.

**Tasks**

1. Initialize the Cube project at `/cube`. Point it at the marts datasets, not raw.
2. Define four cubes: `sellers` (on `dim_seller` + `seller_lifecycle`), `funnel` (on `stg_attio__mqls` + `stg_attio__closed_deals`), `orders` (on `fct_orders` joined to `fct_order_items` aggregated to order grain — respect `PROJECT.md` §6 gotcha 1), `partner_eligibility` (on a `partner_scorecard` mart you will build in this phase).
3. Implement every measure in `PROJECT.md` §7 as a Cube measure. Implement the corresponding dimensions.
4. Define joins between cubes explicitly: `sellers` ↔ `orders`, `sellers` ↔ `funnel` via `closed_deals.seller_id`.
5. Create one view per business question: `gtm_funnel_view`, `seller_economics_view`, `partner_program_view`. The agent primarily queries views, not cubes.
6. Add `cube validate` to `dbt_ci.yml`.

**Phase 2 deliverable**

- A merged PR titled `feat(cube): semantic layer`.
- A markdown file `/cube/README.md` listing every measure and view with a one-line definition matching `PROJECT.md` §7 exactly.
- Screenshots or recordings of the Cube Playground answering five sample questions correctly.

### Phase 3 — Nao agent and test suite

**Target duration:** 1 week.

**Tasks**

1. Initialize Nao at `/nao`. Configure `nao_config.yaml` to sync context from: BigQuery (marts only, never raw), the dbt repo, the Cube model, and the docs folder.
2. Write `RULES.md`. At minimum: always prefer a Cube measure over raw SQL; never query `raw_attio` or `raw_ops` directly; for GMV always use the `gmv` measure; for repeat-customer analysis always use `customer_unique_id`; when in doubt, ask a clarifying question rather than guess.
3. Write `business_defs.md`. Paraphrase every definition from `PROJECT.md` §7 in plain English with one worked example per metric.
4. Write `glossary.md` with Portuguese ↔ English category names and any Olist-specific jargon.
5. Write `example_queries.md` with at least 15 golden examples covering all three business questions. Each entry: the natural-language question, the Cube query JSON, the expected shape of the answer.
6. Write `tests/question_set.yaml` with at least 30 unit tests. Each test has: a question, expected measure(s) and dimension(s), and (where deterministic) an expected scalar answer.
7. Wire Kimi via OpenRouter as the LLM. BYO key via env var. Smoke test passes.
8. Enable the Slack integration.
9. Build `.github/workflows/nao_ci.yml`: runs `nao test` with the 90% / 95% threshold from `PROJECT.md` §9.3.

**Phase 3 deliverable**

- A merged PR titled `feat(nao): agent context and tests`.
- CI showing `nao test` at or above threshold.
- A 5-minute screen recording of the agent answering three questions in Slack, including one where it correctly asks for clarification.

### Phase 4 — Analysis writeup

**Target duration:** 1 week.

You stop being a pipeline builder here and start being an analyst. Use the stack you built to answer the three business questions and write up your findings.

**Tasks**

1. **Funnel analysis:** MQL → closed deal → first order, by `origin`, `business_segment`, and `lead_behaviour_profile`. Identify the two best- and two worst-performing channels and explain why.
2. **Payback analysis:** median `days_to_payback` by `business_segment` and `origin`. Include sensitivity showing how payback shifts if commission rate moves ±5% and CAC moves ±25%.
3. **Partner eligibility:** rank active sellers by `partner_eligibility_score`. Top 50 candidates with four pillar scores broken out. Flag any seller failing a hard quality gate.
4. Write the memo at `/analysis/findings.md`, max 5 pages. Lead with the recommendation; back it with numbers; show the SQL or Cube query for every claim in a footnote.

**Phase 4 deliverable**

- A merged PR titled `docs(analysis): GTM findings memo` containing `findings.md` and any supporting notebooks.

---

## Acceptance test (submit at end of Phase 4)

This is the test. Submit your answers as `/analysis/acceptance_test.md`. For each question: the answer, the Cube query the agent used to produce it, and the ground-truth dbt-or-SQL query you used to verify it. They must agree. If they disagree, the test fails for that question and we debug together.

### Ingestion (new — Phase 0 must hold up under the test)

1. As of the time of submission, how many distinct `mql_id` are in `raw_attio.mqls`? How many distinct `seller_id` are in `raw_ops.sellers`? Both must match a manual count taken from the source systems on the same day.
2. What is the current `dbt source freshness` status for each declared source? Paste the output. All sources must be `pass`.
3. What is the current rate of `seller_id` drift between `raw_attio.closed_deals` and `raw_ops.sellers`? It must be under the 2% threshold.

### Funnel

4. What is the overall MQL → closed deal conversion rate across the full dataset?
5. Which `origin` has the highest MQL → closed deal conversion rate among origins with ≥ 200 MQLs?
6. What is the median number of days from `won_date` to `first_order_at`, broken down by `business_segment`?
7. Of sellers acquired in Q1 of the dataset's first full year, what share placed at least one order within 90 days?

### Payback

8. Using the seed commission rate and CAC estimates, what is the median `days_to_payback` for sellers in the `home_decor` segment? In the `watches_gifts` segment?
9. What share of sellers in the dataset never reach payback within their observed lifetime?
10. If we cut estimated CAC by 25%, how does the median `days_to_payback` change for the worst-performing segment from question 8?

### Partner eligibility

11. How many sellers currently pass all four quality gates (review score ≥ 4.0, cancellation rate ≤ 5%, on-time delivery ≥ 90%, ≥ 6 months active)?
12. List the top 10 partner-eligible sellers by `partner_eligibility_score` with their four pillar scores.
13. For the seller ranked #1, write one paragraph explaining why they are a strong partner candidate, citing the four pillar scores. The agent must produce this paragraph from its context.

### Pass conditions

- All 13 answers match ground truth within rounding.
- Every Cube query referenced is a real query against the deployed model.
- `nao test` on the `question_set.yaml` suite is ≥ 90% correct, ≥ 95% answered.
- All five phase PRs are merged to `main`. CI green on the merge commit for all four workflows.

---

## Submission

When ready:

1. Open a final PR titled `submission: phase 4 acceptance test` containing `/analysis/acceptance_test.md` and supporting files.
2. Tag me as reviewer.
3. In the PR body, link the five merged phase PRs and paste the latest output from each CI workflow.
4. We review together in a 60-minute session. Come ready to walk through one funnel question, one payback question, and one partner question end to end — from the natural-language input, to the Cube query, to the dbt model, to the source table in `raw_attio` or `raw_ops`, to the row in Attio or the ops DB.

---

## Notes and gotchas

- Do not skip `PROJECT.md` §6. Every gotcha there is something I have watched someone get wrong. Read it twice. Pay special attention to #11 (seller_id drift), #12 (Attio schema drift), and #13 (JSON columns) — these are new to this project.
- Airbyte connectors do *extract*. No filtering for business logic, no renaming to nice names, no derived columns. That's dbt's job. If you find yourself writing a SQL transform inside a connector, stop.
- If a closed deal in Attio has no matching seller in ops, do not silently drop it. Surface it in a `dbt/models/intermediate/int_attio__orphan_deals.sql` model and let the bridge integrity test flag the rate.
- If you find yourself writing complex SQL inside Cube, stop. The transformation belongs in dbt. Add a model, expose it as a clean table, write the Cube measure on top.
- Business definitions never live in `RULES.md` or the agent prompt. They live in `business_defs.md` or as Cube measures.
- Copilot will write decent PR review comments on dbt and connector changes, but it does not understand the business. Treat its review as a lint pass, not a design review.
- Commission and CAC numbers are placeholders. Every conclusion is conditional on them. State that explicitly in the findings memo.
- If the team asks a question the current Cube model can't answer, do not write ad-hoc SQL. Add the measure to Cube, ship it, then answer.
- If anything in this brief is unclear, ask before you build. An hour of clarification beats a week of rework.
