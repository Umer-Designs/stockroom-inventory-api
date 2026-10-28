"""Pure invoice reconciliation shared by the CLI and HTTP service."""

import csv
import hashlib
import io
from decimal import Decimal, InvalidOperation

MAX_BYTES = 100_000
MAX_CENTS = 1_000_000_000


def money(value):
    amount = Decimal(str(value))
    if (
        not amount.is_finite()
        or amount < 0
        or amount.as_tuple().exponent < -2
        or amount > MAX_CENTS / 100
    ):
        raise ValueError(
            "Amount must be between 0 and 10000000 with at most 2 decimal places"
        )
    return int(amount * 100)


def reconcile_csv(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("CSV exceeds 100 KB limit")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
    if reader.fieldnames != ["invoice_id", "customer", "amount", "paid"]:
        raise ValueError("Expected invoice_id,customer,amount,paid header")
    accepted, rejected, seen = [], [], set()
    while True:
        line = reader.line_num + 1
        try:
            row = next(reader)
        except StopIteration:
            break
        try:
            if None in row or any(v is None for v in row.values()):
                raise ValueError("Expected four columns")
            key, customer = row["invoice_id"].strip(), row["customer"].strip()
            if not key or not customer:
                raise ValueError("Missing invoice_id or customer")
            if len(key) > 100 or len(customer) > 100:
                raise ValueError(
                    "Identifier and customer are limited to 100 characters"
                )
            if key in seen:
                raise ValueError("Duplicate invoice_id in this file")
            amount, paid = money(row["amount"]), money(row["paid"])
            if paid > amount:
                raise ValueError("Paid exceeds invoice amount")
            seen.add(key)
            accepted.append(
                {
                    "invoice_id": key,
                    "customer": customer,
                    "amount_cents": amount,
                    "paid_cents": paid,
                    "due_cents": amount - paid,
                }
            )
        except (ValueError, InvalidOperation) as error:
            rejected.append({"line": line, "error": str(error)})
    due = sum(row["due_cents"] for row in accepted)
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "cached": False,
        "accepted": accepted,
        "rejected": rejected,
        "totals": {"invoices": len(accepted), "due_cents": due},
        "summary": f"{len(accepted)} valid invoices; {len(rejected)} rejected rows; outstanding USD {due / 100:.2f}.",
        "summary_mode": "deterministic",
    }
