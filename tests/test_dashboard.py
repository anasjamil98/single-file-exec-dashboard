import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

import build_dashboard as bd  # noqa: E402
import generate  # noqa: E402


@pytest.fixture(scope="session")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("data") / "zaffre.db"
    generate.build(path, n_customers=900, seed=7)
    return path


@pytest.fixture(scope="session")
def built(db, tmp_path_factory):
    out = tmp_path_factory.mktemp("dist") / "dashboard.html"
    payload, path = bd.build(db, out)
    return payload, path.read_text(encoding="utf-8")


def embedded(html):
    raw = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1)
    return json.loads(raw)


# ---- it really is one self-contained file ----------------------------------

def test_no_external_references(built):
    _, html = built
    assert bd.external_references(html) == []


def test_no_external_tags(built):
    _, html = built
    assert not re.search(r"<(?:link|img|iframe|object|embed)\b", html, re.I)
    assert not re.search(r"<script[^>]+\bsrc=", html, re.I)
    assert "@import" not in html and "url(" not in html
    assert "fetch(" not in html and "XMLHttpRequest" not in html


def test_external_reference_check_catches_a_cdn():
    assert bd.external_references('<script src="https://cdn.example.com/chart.js"></script>') != []
    assert bd.external_references('<link href="//fonts.example.com/css">') != []
    assert bd.external_references('document.createElementNS("http://www.w3.org/2000/svg", "g")') == []


def test_embedded_data_round_trips(built):
    payload, html = built
    assert embedded(html) == json.loads(json.dumps(payload))


def test_script_closing_tag_in_data_cannot_break_out():
    html = bd.render({"meta": {"company": "</script><script>alert(1)</script>"}})
    assert html.count("</script>") == bd.TEMPLATE.read_text(encoding="utf-8").count("</script>")


# ---- only aggregates leave the database -------------------------------------

def test_no_customer_level_fields(built):
    payload, html = built
    text = json.dumps(payload)
    assert "customer_id" not in text and "txn_id" not in text
    assert set(payload) == {"meta", "months", "types", "cells", "payers", "merchants", "merchantCells", "suppressed"}
    assert len(payload["cells"]) <= 12 * len(bd.PAYMENT_TYPES)


def test_small_merchant_cells_are_folded_not_shown(db, built):
    payload, _ = built
    con = sqlite3.connect(str(db))
    ids = [r[0] for r in con.execute("SELECT merchant_id FROM merchants ORDER BY merchant_id")]
    customers = {
        (month, bd.TYPE_INDEX[txn_type], merchant_id): count
        for month, txn_type, merchant_id, count in con.execute(
            f"SELECT {bd.MONTH}, txn_type, merchant_id, COUNT(DISTINCT customer_id) FROM transactions "
            f"WHERE {bd.IN_SCOPE} AND status = 'success' AND merchant_id IS NOT NULL GROUP BY 1, 2, 3",
            bd.BOUNDS,
        )
    }
    con.close()
    shown = {(month, t, ids[merchant]) for month, t, merchant, _, _ in payload["merchantCells"]}
    assert all(customers[key] >= bd.MIN_CUSTOMERS for key in shown)
    assert all(customers[key] < bd.MIN_CUSTOMERS for key in set(customers) - shown)
    assert payload["suppressed"], "the small dataset should have some cells to fold"


def test_raising_the_threshold_hides_more(db):
    loose = bd.aggregate(db, min_customers=1)
    strict = bd.aggregate(db, min_customers=20)
    assert loose["suppressed"] == []
    assert len(strict["merchantCells"]) < len(loose["merchantCells"])


# ---- the numbers reconcile ---------------------------------------------------

def test_payment_value_reconciles_to_the_source(db, built):
    payload, _ = built
    con = sqlite3.connect(str(db))
    count, value = con.execute(
        f"SELECT COUNT(*), SUM(amount_minor) FROM transactions WHERE {bd.IN_SCOPE} AND status = 'success'", bd.BOUNDS
    ).fetchone()
    con.close()
    assert sum(c[2] for c in payload["cells"]) == count
    assert sum(c[3] for c in payload["cells"]) == value


def test_folding_small_cells_loses_no_money(db, built):
    """Shown merchant cells + folded cells = every merchant payment."""
    payload, _ = built
    con = sqlite3.connect(str(db))
    count, value = con.execute(
        f"SELECT COUNT(*), SUM(amount_minor) FROM transactions WHERE {bd.IN_SCOPE} "
        "AND status = 'success' AND merchant_id IS NOT NULL",
        bd.BOUNDS,
    ).fetchone()
    con.close()
    shown = payload["merchantCells"]
    folded = payload["suppressed"]
    assert sum(r[3] for r in shown) + sum(r[2] for r in folded) == count
    assert sum(r[4] for r in shown) + sum(r[3] for r in folded) == value


def test_successes_never_exceed_attempts(built):
    payload, _ = built
    for _, _, successes, _, attempts, payers in payload["cells"]:
        assert 0 < successes <= attempts
        assert payers <= successes


def test_all_type_payers_are_not_a_sum_of_per_type_payers(built):
    payload, _ = built
    for month in range(12):
        per_type = [c[5] for c in payload["cells"] if c[0] == month]
        assert max(per_type) <= payload["payers"][month] <= sum(per_type)


def test_test_accounts_are_excluded(db, built):
    payload, _ = built
    con = sqlite3.connect(str(db))
    with_test_accounts = con.execute(
        "SELECT COUNT(*) FROM transactions WHERE txn_ts >= ? AND txn_ts < ? AND status = 'success' "
        f"AND txn_type IN ({bd.TYPE_LIST})",
        bd.BOUNDS,
    ).fetchone()[0]
    con.close()
    assert sum(c[2] for c in payload["cells"]) < with_test_accounts


def test_committed_dashboard_is_self_contained():
    committed = ROOT / "dist" / "dashboard.html"
    if not committed.exists():
        pytest.skip("dist/dashboard.html hasn't been built")
    assert bd.external_references(committed.read_text(encoding="utf-8")) == []
