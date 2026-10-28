# Stockroom Inventory API

Independent portfolio project by Umer Khalid, 2026. All example data is fictional.

## Run

```text
python -m pip install -r requirements.txt
# Set INVENTORY_API_KEY in your environment
python -m pytest -q
python -m uvicorn app:app --reload
```

Requires Python 3.12+. Create and activate a virtual environment before installing requirements.

## Features

Validated product endpoints, API-key-protected writes, pagination, literal search, summary, atomic stock movements and audit history. Swagger at /docs. SQLite database path configurable via DATABASE_PATH.

## Limitations

Single tenant demo, no production auth, migration framework, managed TLS, rate limiting or backups. Use persistent disk on a Python host. Do not deploy the SQLite file to ephemeral hosting.

## Tests

Ten API tests cover authentication, product creation, duplicate SKUs, validation, search, pagination, missing records, stock movements and fail-closed writes. Run the test command above to verify your environment.

## Design notes

Each database operation uses a short-lived SQLite connection. Stock adjustments use BEGIN IMMEDIATE so the availability check and update run in one transaction. A rejected adjustment leaves both stock and movement history unchanged.

MIT licensed. See LICENSE.