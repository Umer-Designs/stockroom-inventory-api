# Stockroom Inventory API

Independent portfolio project by Umer Khalid, 2026. All example data is fictional.

## Run

```text
python -m pip install -r requirements.txt
# Set INVENTORY_API_KEY in your environment
python -m pytest -q
python -m uvicorn app:app --reload
```

Use Python 3.12+ or Node 22+ with pnpm, as applicable. Create and activate a virtual environment for Python dependencies.

## Features

Validated product endpoints, API-key-protected writes, pagination, literal search, summary, atomic stock movements and audit history. Swagger at /docs. SQLite database path configurable via DATABASE_PATH.

## Limitations

Single tenant demo, no production auth, migration framework, managed TLS, rate limiting or backups. Use persistent disk on a Python host. Do not deploy the SQLite file to ephemeral hosting.

## Tests

Tests live alongside the source and cover business rules and error cases. See the portfolio delivery report for the actual validation results.

## Explain this project

Trace one input through validation, state change, and output. Explain the data representation and one failure path. Modify a validation rule and update its test before discussing the project in an interview.

MIT licensed. No employment, client work or production outcomes are claimed.
