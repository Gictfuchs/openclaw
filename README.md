# OpenClaw / Fochs 🦊

[![CI](https://github.com/Gictfuchs/openclaw/actions/workflows/ci.yml/badge.svg)](https://github.com/Gictfuchs/openclaw/actions/workflows/ci.yml)

> An autonomous AI agent that researches, informs, and evolves.

## What is Fochs?

Fochs is an autonomous AI agent that:
- **Researches** topics across web, social media, and news sources
- **Informs** you proactively via Telegram when relevant things happen
- **Remembers** everything across conversations with long-term memory
- **Evolves** by learning from interactions and improving over time
- **Delegates** complex tasks to specialized sub-agents

## Tech Stack

| Component | Technology |
|---|---|
| Primary LLM | Claude API (Anthropic) |
| Local LLM | Ollama (cost-saving for routine tasks) |
| Search | Brave Search + Gemini (Google Grounding) |
| Social Media | Grok/xAI (X/Twitter) |
| Interface | Telegram Bot + FastAPI Web Dashboard |
| Memory | SQLite + ChromaDB (vector search) |

## Getting Started

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (package manager)
- [Ollama](https://ollama.ai/) (optional, for local LLM)
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- Anthropic API Key

### Setup

```bash
# Clone
git clone https://github.com/Gictfuchs/openclaw.git
cd openclaw

# Install
uv pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env with your API keys

# Run
python -m openclaw
```

### Ollama Setup (optional)

```bash
# Install Ollama
brew install ollama

# Pull recommended models
ollama pull llama3.1:8b
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

## Development

```bash
make test        # Run tests
make lint        # Run linter
make fmt         # Format code
make type-check  # Type checking
make check       # All of the above
```

## Architecture

See [CLAUDE.md](CLAUDE.md) for development instructions and architecture details.

## License

MIT
