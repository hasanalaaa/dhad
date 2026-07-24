.PHONY: audit check test test-python test-rust test-web clean

audit:
	python tools/audit_repository.py --write-reports

check: audit
	python -m compileall -q src tests tools benchmarks
	cargo fmt --all -- --check
	cargo clippy --workspace --all-targets --locked -- -D warnings
	cd web_demo && npm run check

test: test-python test-rust test-web

test-python:
	pytest -q

test-rust:
	cargo test --workspace --all-targets --locked

test-web:
	cd web_demo && npm test

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache .audit-venv
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf web_demo/node_modules rust/dhad-core-rs/target target
