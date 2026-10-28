# Stockroom and Ledger Python API

FastAPI service for inventory transactions, a session-isolated invoice demo, and CSV reconciliation. Supports local SQLite or hosted PostgreSQL through SQLAlchemy.

## Local setup

Requires Python 3.12+.

```sh
python -m venv .venv
# Activate the virtual environment for your shell.
python -m pip install -r requirements.txt
python -m pytest -q
python -m uvicorn app:app --reload
```

Set `INVENTORY_API_KEY` to a random local secret to enable inventory writes. PowerShell uses `$env:INVENTORY_API_KEY = 'your-local-secret'`; macOS/Linux uses `export INVENTORY_API_KEY='your-local-secret'`. Environment examples are in `.env.example`; the service reads process variables, not that file automatically. Interactive API documentation is at `/docs`.

## Database

By default, `DATABASE_PATH` is `inventory.db`. For PostgreSQL set `DATABASE_URL` to the provider's connection string with TLS enabled. Never commit that string or place it in frontend configuration. Initial tables are created from `database.py`. This release adds a separate invoice table without rewriting existing inventory records; later schema changes need an explicit migration.

## Endpoints

| Route | Purpose | Access |
| --- | --- | --- |
| GET /health | Database health check | Public |
| GET /products, /products/{id}, /movements, /summary | Read sample inventory | Public |
| POST /products, /products/{id}/movements | Create products and adjust stock | X-API-Key |
| GET /invoices | Read the current demo workspace | X-Demo-Session |
| POST /invoices | Add an invoice | X-Demo-Session |
| PATCH /invoices/{id}/paid | Set an owned invoice to fully paid | X-Demo-Session |
| POST /invoices/reset | Replace owned invoices with sample records | X-Demo-Session |
| POST /reconcile | Run the shared Python CSV processor | Public, bounded input |

Stock updates use a conditional UPDATE and a transaction: an insufficient balance cannot create a movement record. Invoice writes validate dates and integer-cent amounts. Each demo workspace is identified by a random 256-bit token; the database stores the token's SHA256 hash. Creation is limited to 100 invoices per workspace, and old invoices are cleared lazily during writes. This is possession-based demo access, not account authentication. Use fictional data only.

The reconciliation endpoint accepts JSON `{"csv": "invoice_id,customer,amount,paid\n..."}`. CSV content is limited to 100 KB and is not persisted by the HTTP endpoint. The CLI version also supports cached reports and atomic file output. `reconciliation.py` is shared verbatim with the automation repository.

## Free hosting

`render.yaml` declares a free Python web service. Build: `pip install -r requirements.txt`. Start: `uvicorn app:app --host 0.0.0.0 --port $PORT`. Health path: `/health`.

Use a persistent PostgreSQL service for `DATABASE_URL`; do not store a live SQLite database on Render's ephemeral filesystem. Set `ALLOWED_ORIGINS=https://umer-designs.github.io`. The write API key stays in service environment variables and is never shipped to the browser. The dashboard uses demo-session endpoints instead.

Render free services can sleep; the frontend waits and displays errors. This repository being deployable does not imply that a hosted service has been configured. The portfolio's runtime configuration determines whether its demo is connected.

## Verification and limits

26 API tests cover inventory validation and transactions, session isolation, invoice lifecycle, input bounds, CSV processing and CORS. An additional PostgreSQL integration test runs in GitHub Actions against a disposable PostgreSQL 18 service. Locally, set `TEST_POSTGRES_URL` to a disposable database to run it; otherwise it is skipped.

The demo does not include account recovery, production rate limiting, financial compliance, managed backups or a schema migration framework. CORS restricts browser origins but is not authentication. Free service quotas still apply. MIT licensed.
