# CLAUDE.md - Fochs (OpenClaw) Development Instructions

## Project Overview

Fochs is an autonomous AI agent that researches, informs, and evolves. Built with Python 3.12+.

## Tech Stack

- **Language**: Python 3.12+
- **LLMs**: Claude API (primary), Ollama (local/routine), Gemini (search/fallback), Grok (X/social)
- **Telegram**: python-telegram-bot for user interaction
- **Database**: SQLite + SQLAlchemy (async) + ChromaDB (vector memory)
- **Web**: FastAPI + HTMX (dashboard, later phases)

## Commands

```bash
# Install
uv pip install -e ".[dev]"

# Run
python -m openclaw

# Test
make test

# Lint
make lint

# Format
make fmt

# Type check
make type-check

# All checks
make check
```

## Project Structure

```
src/openclaw/
  config.py         - Pydantic Settings (.env)
  app.py            - Application lifecycle
  __main__.py       - Entry point
  core/             - Agent loop, events, autonomy
  llm/              - LLM providers (claude, ollama, gemini, grok) + router
  tools/            - Agent tools (search, scrape, github, email, etc.)
  telegram/         - Telegram bot interface
  memory/           - Short-term + long-term memory (ChromaDB)
  integrations/     - External service clients
  research/         - Multi-source research engine
  scheduler/        - APScheduler + task queue
  sub_agents/       - Sub-agent orchestration
  web/              - FastAPI dashboard
```

## Code Conventions

- Follow conventional commits: `type(scope): description`
- Python 3.12+ features (type hints, match statements, etc.)
- All async where possible (asyncio)
- Type hints everywhere, checked with mypy (strict mode)
- Ruff for linting and formatting (120 char line length)
- structlog for structured logging

## Architecture

The LLM Router automatically selects the best provider:
- **Ollama** (local): classification, summarization, embeddings, simple Q&A
- **Claude** (API): complex reasoning, tool use, multi-step planning
- **Gemini** (API): Google grounded search, Claude fallback
- **Grok** (API): X/Twitter-specific tasks

See `docs/ADR/` for architecture decisions.

## Important Notes

- Never commit `.env` files (API keys!)
- The `data/` directory is gitignored (SQLite, ChromaDB, logs)
- Telegram bot token must be set in `.env` to run
- Ollama must be running locally for local LLM features
