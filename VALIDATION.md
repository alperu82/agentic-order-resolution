# Validation record

Validated locally on 6 October 2026, macOS, Python 3.13.

- `pytest -q`: 17 passed.
- `ruff check .`: passed.
- `ruff format --check .`: passed.
- `pip check`: no broken requirements.
- Standard isolated wheel build: succeeded; both synthetic JSON resources included.
- Live localhost Uvicorn/HTTP smoke: tracking completion, refund pending, delivered manual review and authenticated refund approval passed.
- ZIP extracted into a temporary folder and the same tests run against its source: 17 passed.

Provider calls use mocked HTTP responses in tests. External payment, email and carrier integrations are outside the current scope. Smoke-test data and credentials were synthetic and temporary.
