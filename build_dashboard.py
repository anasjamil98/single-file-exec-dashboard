"""Bakes aggregated payment data into one self-contained HTML dashboard.

    python build_dashboard.py            ->  dist/dashboard.html

The output is a single file. No server, no login, no CDN, no fonts, no network
requests of any kind: it opens from a laptop, an email attachment or a shared
drive, and it works offline.

What goes into the file is decided here, not in the browser:

* Only aggregates. The finest grain is month x payment type (x merchant). No
  customer id, no individual transaction.
* Small cells are suppressed. A merchant's month is only listed when at least
  MIN_CUSTOMERS different customers paid there. Smaller cells are folded into
  one combined line, so the totals still add up but nobody can be picked out.
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "data" / "zaffre.db"
TEMPLATE = ROOT / "template.html"
DEFAULT_OUT = ROOT / "dist" / "dashboard.html"

YEAR = 2025
MIN_CUSTOMERS = 5
PLACEHOLDER = "/*__DATA__*/"

# (key, label, involves a merchant). Order is fixed: it decides each type's colour.
PAYMENT_TYPES = [
    ("p2p_transfer", "Transfers to people", False),
    ("merchant_payment", "Merchant payments", True),
    ("card_payment", "Card payments", True),
    ("bill_payment", "Bill payments", True),
]
TYPE_INDEX = {key: i for i, (key, _, _) in enumerate(PAYMENT_TYPES)}

# Local year, bounded on the raw UTC column. Local time is UTC+3.
BOUNDS = (f"{YEAR - 1}-12-31 21:00:00", f"{YEAR}-12-31 21:00:00")
REAL_CUSTOMERS = "customer_id NOT IN (SELECT customer_id FROM customers WHERE is_test_account = 1)"
TYPE_LIST = ",".join(f"'{key}'" for key, _, _ in PAYMENT_TYPES)
IN_SCOPE = f"txn_ts >= ? AND txn_ts < ? AND txn_type IN ({TYPE_LIST}) AND {REAL_CUSTOMERS}"
MONTH = "CAST(strftime('%m', txn_ts, '+3 hours') AS INTEGER) - 1"


def aggregate(db_path=DEFAULT_DB, min_customers=MIN_CUSTOMERS):
    """Everything the dashboard shows, as a JSON-ready dict."""
    con = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        cells = [
            [month, TYPE_INDEX[txn_type], successes, value or 0, attempts, payers]
            for month, txn_type, successes, value, attempts, payers in con.execute(
                f"SELECT {MONTH}, txn_type, SUM(status = 'success'), "
                "SUM(CASE WHEN status = 'success' THEN amount_minor END), COUNT(*), "
                "COUNT(DISTINCT CASE WHEN status = 'success' THEN customer_id END) "
                f"FROM transactions WHERE {IN_SCOPE} GROUP BY 1, 2 ORDER BY 1, 2",
                BOUNDS,
            )
        ]
        # Distinct payers across all types can't be added up from the per-type cells.
        payers = [0] * 12
        for month, count in con.execute(
            f"SELECT {MONTH}, COUNT(DISTINCT customer_id) FROM transactions "
            f"WHERE {IN_SCOPE} AND status = 'success' GROUP BY 1",
            BOUNDS,
        ):
            payers[month] = count

        merchant_rows = con.execute(
            "SELECT merchant_id, merchant_name, category FROM merchants ORDER BY merchant_id"
        ).fetchall()
        merchant_index = {merchant_id: i for i, (merchant_id, _, _) in enumerate(merchant_rows)}

        merchant_cells, suppressed = [], {}
        for month, txn_type, merchant_id, count, value, customers in con.execute(
            f"SELECT {MONTH}, txn_type, merchant_id, COUNT(*), SUM(amount_minor), COUNT(DISTINCT customer_id) "
            f"FROM transactions WHERE {IN_SCOPE} AND status = 'success' AND merchant_id IS NOT NULL "
            "GROUP BY 1, 2, 3 ORDER BY 1, 2, 3",
            BOUNDS,
        ):
            t = TYPE_INDEX[txn_type]
            if customers >= min_customers:
                merchant_cells.append([month, t, merchant_index[merchant_id], count, value])
            else:
                folded = suppressed.setdefault((month, t), [0, 0])
                folded[0] += count
                folded[1] += value
    finally:
        con.close()

    return {
        "meta": {
            "company": "Zaffre Wallet (fictional)",
            "year": YEAR,
            "currency": "MRD",
            "minCustomers": min_customers,
            "note": "Reporting dates are local time. Internal test accounts are excluded.",
        },
        "months": [f"{YEAR}-{m:02d}" for m in range(1, 13)],
        "types": [{"key": key, "label": label, "merchant": merchant} for key, label, merchant in PAYMENT_TYPES],
        "cells": cells,
        "payers": payers,
        "merchants": [{"name": name, "category": category.title()} for _, name, category in merchant_rows],
        "merchantCells": merchant_cells,
        "suppressed": [[month, t, count, value] for (month, t), (count, value) in sorted(suppressed.items())],
    }


def render(payload):
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(PLACEHOLDER) != 1:
        raise ValueError("template.html must contain the data placeholder exactly once")
    # "</" inside a JSON string would end the script element early.
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    return template.replace(PLACEHOLDER, data)


def external_references(html):
    """Every URL in the file other than the SVG namespace, which is a name and not a request."""
    urls = set(re.findall(r"(?:https?:)?//[A-Za-z0-9.-]+\.[A-Za-z]{2,}[^\s\"'<>)]*", html))
    return sorted(urls - {"http://www.w3.org/2000/svg"})


def build(db_path=DEFAULT_DB, out_path=DEFAULT_OUT, min_customers=MIN_CUSTOMERS):
    payload = aggregate(db_path, min_customers)
    html = render(payload)
    leaks = external_references(html)
    if leaks:
        raise ValueError("the dashboard must not reference anything external: " + ", ".join(leaks))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(out_path), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(html)
    return payload, out_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the single-file dashboard.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--min-customers", type=int, default=MIN_CUSTOMERS)
    args = parser.parse_args(argv)
    if not Path(args.db).exists():
        print("No database. Run: python data/generate.py", file=sys.stderr)
        return 2
    payload, out_path = build(args.db, args.out, args.min_customers)
    shown, folded = len(payload["merchantCells"]), sum(row[2] for row in payload["suppressed"])
    try:
        shown_path = out_path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        shown_path = str(out_path)
    print(f"Wrote {shown_path} ({out_path.stat().st_size / 1024:.0f} KB)")
    print(f"{len(payload['cells'])} month x type cells, {shown} merchant cells shown, "
          f"{len(payload['suppressed'])} small-cell groups folded ({folded} payments)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
