# Cube Core Semantic Layer

Cube Core serves as the semantic layer for the Olist GTM Analytics pipeline. It defines all business metrics and dimensions as a single source of truth.

## Setup

1. Copy `.env.example` to `.env` and fill in your BigQuery credentials.
2. Install dependencies: `pip install -r requirements.txt`
3. Start the Cube server: `cube-server`

## Project Structure

- `cube.py` — Main configuration file pointing to BigQuery datasource
- `model/cubes/` — Cube definitions (sellers, funnel, orders, partner_eligibility)
- `model/views/` — Business views (gtm_funnel_view, seller_economics_view, partner_program_view)

## Cubes

| Cube | Table | Purpose |
|------|-------|---------|
| `sellers` | `marts_core.dim_seller` | Seller dimension |
| `funnel` | `staging.stg_attio__mqls` | GTM funnel (MQL → close → first order) |
| `orders` | `marts_core.fct_orders` | Order facts and GMV |
| `partner_eligibility` | `marts_gtm.partner_scorecard` | Partner program eligibility |

## Views

- `gtm_funnel_view` — MQL conversion and funnel performance by origin/segment
- `seller_economics_view` — GMV, commission, CAC, days to payback
- `partner_program_view` — Partner eligibility scores and quality gates

## Validation

Run `cube validate` before committing changes.
