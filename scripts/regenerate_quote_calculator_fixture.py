#!/usr/bin/env python3
"""Regenerate tests/fixtures/quote_calculator.json from this site's pricing code.

The fixture is the shared golden-vector set: the site's own tests and the customer
app's ``core/src/test/resources/quote_calculator.json`` both read it. Case ids,
inputs and ``raw_asset_toman`` are the independent part and are preserved; every
``expected`` block, ``expected_error.minimum_total_toman`` and
``next_principal_total_toman`` is recomputed from ``pricing.py`` so nobody types
numbers by hand.

The independent Fraction oracles in ``tests/test_pricing.py`` still recompute the
same values from scratch, so this tool cannot turn the tests into a tautology.

Usage:
    python3 scripts/regenerate_quote_calculator_fixture.py
    python3 scripts/regenerate_quote_calculator_fixture.py --check
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from decimal import Context, Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "bitcoin4funsite/tests/fixtures/quote_calculator.json"
SUPPLY = 2100000000000000


def load_pricing():
    path = ROOT / "bitcoin4funsite/pricing.py"
    spec = importlib.util.spec_from_file_location("site_pricing", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load site pricing module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["site_pricing"] = module
    spec.loader.exec_module(module)
    return module


def as_text(value):
    """Serialize integers as base-10 strings; keep booleans, nulls and text as-is."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    return str(value)


def raw_asset(btc_text, principal):
    """Exact principal * raw btc / 100000000 as decimal text, no markup or fees."""
    with localcontext(Context(prec=128)):
        value = Decimal(btc_text) * principal / 100000000
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def quote(pricing, case):
    inputs = case["inputs"]
    include_tag = bool(inputs.get("include_tag", False))
    in_person = bool(inputs.get("in_person", False))
    has_wallet = bool(inputs.get("has_wallet", False))
    if case["mode"] == "principal":
        return pricing.quote_for_principal(
            inputs["btc_toman"], inputs["usdt_toman"], inputs["fee_rate"],
            inputs["principal_sats"], include_tag=include_tag, in_person=in_person,
            has_wallet=has_wallet)
    return pricing.quote_for_budget(
        inputs["btc_toman"], inputs["usdt_toman"], inputs["fee_rate"],
        inputs["budget_toman"], include_tag=include_tag, in_person=in_person,
        has_wallet=has_wallet)


def refresh(pricing, fixture):
    cases = []
    for case in fixture["cases"]:
        if "expected_error" in case:
            minimum = pricing.quote_for_principal(
                case["inputs"]["btc_toman"], case["inputs"]["usdt_toman"],
                case["inputs"]["fee_rate"], 501)["total_toman"]
            cases.append({**case, "expected_error": {
                **case["expected_error"], "minimum_total_toman": str(minimum)}})
            continue
        row = quote(pricing, case)
        expected = {}
        for key, value in row.items():
            if key in ("rates", "assumptions", "costs"):
                expected[key] = {name: as_text(item) for name, item in value.items()}
            else:
                expected[key] = as_text(value)
        updated = {**case, "expected": expected,
                   "raw_asset_toman": raw_asset(case["inputs"]["btc_toman"], row["principal_sats"])}
        if case["mode"] == "budget" and row["principal_sats"] < SUPPLY:
            updated["next_principal_total_toman"] = str(
                pricing.quote_for_principal(
                    case["inputs"]["btc_toman"], case["inputs"]["usdt_toman"],
                    case["inputs"]["fee_rate"], row["principal_sats"] + 1,
                    include_tag=bool(case["inputs"].get("include_tag", False)),
                    in_person=bool(case["inputs"].get("in_person", False)),
                    has_wallet=bool(case["inputs"].get("has_wallet", False)))["total_toman"])
        cases.append(updated)
    return {**fixture, "cases": cases}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero when the committed fixture differs")
    args = parser.parse_args()
    pricing = load_pricing()
    current = json.loads(FIXTURE.read_text(encoding="utf-8"))
    text = json.dumps(refresh(pricing, current), indent=1, ensure_ascii=False) + "\n"
    if args.check:
        if FIXTURE.read_text(encoding="utf-8") != text:
            print(f"{FIXTURE} is stale; run scripts/regenerate_quote_calculator_fixture.py",
                  file=sys.stderr)
            return 1
        print("quote_calculator fixture matches the site's pricing code")
        return 0
    FIXTURE.write_text(text, encoding="utf-8")
    print(f"wrote {FIXTURE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
