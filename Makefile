.PHONY: install lint format types test check run clean

install:
	uv sync --dev
	uv run pre-commit install

lint:
	uv run ruff check .

format:
	uv run ruff format .

types:
	uv run mypy

test:
	uv run pytest

redline:
	uv run python scripts/redline_scan.py

# Everything CI runs, in the same order.
check: lint types test redline
	uv run ruff format --check .

# End to end on the synthetic examples, no key required.
run:
	uv run ttr extract --provider fake

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache runs
