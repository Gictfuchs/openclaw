.PHONY: run test lint fmt type-check install dev setup

# Run the application
run:
	python -m openclaw

# Install dependencies
install:
	uv pip install -e .

# Install dev dependencies
dev:
	uv pip install -e ".[dev]"

# Full setup (install + pre-commit)
setup: dev
	pre-commit install --hook-type commit-msg --hook-type pre-commit

# Run tests
test:
	pytest tests/ -v --asyncio-mode=auto

# Run tests with coverage
test-cov:
	pytest tests/ -v --asyncio-mode=auto --cov=src/openclaw --cov-report=term-missing

# Lint
lint:
	ruff check src/ tests/

# Format
fmt:
	ruff format src/ tests/

# Type check
type-check:
	mypy src/openclaw/

# All checks
check: lint type-check test
