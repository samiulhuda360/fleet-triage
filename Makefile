setup:
	pip install -e ".[dev]"
	npm --prefix web ci
	npm --prefix web run build

demo:
	fleet-triage serve

test:
	ruff check fleet_triage tests
	ruff format --check fleet_triage tests
	pytest
	npm --prefix web run typecheck

eval:
	python -m fleet_triage.evaluation.detection
	python -m fleet_triage.evaluation.triage --modes bm25 rules

.PHONY: setup demo test eval
