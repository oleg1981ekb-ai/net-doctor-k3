.PHONY: ai-smoke lint test

ai-smoke:
	bash scripts/ai-smoke.sh

lint:
	ruff check .

test:
	pytest
