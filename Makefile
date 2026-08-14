.PHONY: install lint format types test check run demo publish-check clean

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

# The first two steps of docs/demo.md, back to back. No key, no network: a demo
# that can hit a rate limit is a demo that will.
demo:
	uv run ttr extract --provider fake
	uv run ttr evaluate --provider fake

# The gate before this repository becomes public. `redline` checks the working
# tree; this checks every blob in every ref, because publishing a repository
# publishes its history and a visibility switch does not un-clone anything.
publish-check: check
	uv run python scripts/redline_history.py

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache runs
