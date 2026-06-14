# Nao Agent Context

Configuration and context for the Nao agent that answers GTM questions.

## Setup

See `task_brief.md` Phase 3 for full implementation instructions.

## Files

- `nao_config.yaml` — Agent configuration (datasources, Kimi LLM)
- `RULES.md` — Hard rules the agent must follow
- `docs/business_defs.md` — Canonical metric definitions in English
- `docs/glossary.md` — Portuguese–English terminology
- `queries/example_queries.md` — Golden question examples
- `tests/question_set.yaml` — Unit test suite for agent answers

## Integration

- Slack integration for natural-language questions
- Kimi via OpenRouter as reasoning engine (BYO key via env var)
