.PHONY: run test lint fmt type-check install dev setup check preflight upgrade upgrade-dry doctor status backup

# --- Development targets ---

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

# --- Deployment targets ---

# Full bootstrap (from git clone to ready)
preflight:
	uv run fochs preflight

# Update to latest version
upgrade:
	uv run fochs update

# Show what an update would change (no modifications)
upgrade-dry:
	uv run fochs update --dry-run

# Health check
doctor:
	uv run fochs doctor

# Show service status (platform-aware)
status:
	@if [ "$$(uname -s)" = "Darwin" ]; then \
		launchctl list 2>/dev/null | grep com.fochs.bot || echo "Service not loaded"; \
	elif [ "$$(uname -s)" = "Linux" ]; then \
		systemctl status fochs 2>/dev/null || echo "Service not found"; \
	fi
	@uv run fochs doctor

# Backup data directory and config
backup:
	@BACKUP_DIR="backups/$$(date +%Y%m%d-%H%M%S)"; \
	mkdir -p "$$BACKUP_DIR"; \
	cp -r data/ "$$BACKUP_DIR/data/" 2>/dev/null || true; \
	cp .env "$$BACKUP_DIR/.env" 2>/dev/null || true; \
	echo "Backup created: $$BACKUP_DIR"
