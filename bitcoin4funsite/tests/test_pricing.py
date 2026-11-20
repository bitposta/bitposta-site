"""Offline unit tests for exact Bitcoin conversion and envelope pricing."""

import importlib
import importlib.util
from pathlib import Path
import sys
import unittest

# Keep discovery and direct execution independent of the caller's directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class BitcoinConversionTests(unittest.TestCase):
    def test_btc_to_sats_preserves_smallest_unit_and_supply_limit(self):
        self.assertIsNotNone(importlib.util.find_spec("pricing"), "pricing must exist")
        pricing = importlib.import_module("pricing")
        convert = getattr(pricing, "btc_to_sats", None)
        self.assertTrue(callable(convert), "btc_to_sats must be implemented")
        for text, expected in (
            ("0", 0),
            ("0.00000001", 1),
            ("0.00000500", 500),
            ("1.12345678", 112345678),
            ("21000000.00000000", 2100000000000000),
        ):
            with self.subTest(text=text):
                self.assertEqual(convert(text), expected)

    def test_btc_to_sats_rejects_noncanonical_or_out_of_range_input(self):
        from pricing import btc_to_sats

        invalid = (
            "", " ", " 1", "1 ", "1\n", "+1", "-1", "-0", "1e-8",
            "NaN", "Infinity", "inf", ".1", "1.", "1_000", "1,000",
            "0.000000001", "1.000000000", "21000000.00000001",
            "21000001", "١", "１", "1.١", None, True, 1, 0.1,
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    btc_to_sats(value)

    def test_sats_to_btc_formats_fixed_eight_decimals_and_round_trips(self):
        pricing = importlib.import_module("pricing")
        convert = getattr(pricing, "sats_to_btc", None)
        self.assertTrue(callable(convert), "sats_to_btc must be implemented")
        for value, expected in (
            (0, "0.00000000"),
            (1, "0.00000001"),
            ("000500", "0.00000500"),
            (112345678, "1.12345678"),
            (2100000000000000, "21000000.00000000"),
        ):
            with self.subTest(value=value):
                self.assertEqual(convert(value), expected)
                self.assertEqual(pricing.btc_to_sats(expected), int(value))

    def test_sats_to_btc_rejects_fractional_signed_unicode_or_excess_amounts(self):
        from decimal import Decimal
        from pricing import sats_to_btc

        invalid = (
            -1, True, False, None, 1.0, Decimal("1"), "", " 1", "1 ",
            "1\n", "+1", "-0", "-1", "1.0", "1e3", "NaN", "Infinity",
            "1_000", "١", "１", 2100000000000001, "2100000000000001",
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    sats_to_btc(value)


class QuoteTableTests(unittest.TestCase):
    def test_minimum_principal_is_501_with_exact_inverse_boundary(self):
        from pricing import quote_for_principal, quote_for_budget, quote_table
        for tag in (False, True):
            for wallet in (False, True):
                args = ("10000000000", "100000", "1.1")
                with self.assertRaises(ValueError):
                    quote_for_principal(*args, 500, include_tag=tag, has_wallet=wallet)
                row = quote_for_principal(*args, 501, include_tag=tag, has_wallet=wallet)
                self.assertEqual(row['principal_sats'], 501)
                first = quote_table(*args, include_tag=tag, has_wallet=wallet)['rows'][0]
                self.assertEqual(first, {key: row[key] for key in first})
                budget = row['total_toman']
                self.assertEqual(quote_for_budget(*args, budget, include_tag=tag,
                                                  has_wallet=wallet)['principal_sats'], 501)
                with self.assertRaises(ValueError):
                    quote_for_budget(*args, budget - 1, include_tag=tag, has_wallet=wallet)

    def test_print_and_postal_groups_split_materials_envelope_and_postage(self):
        from pricing import quote_for_budget, quote_for_principal, quote_table

        inputs = ("10000000000", "100000", "1.1")
        # 3.5% markup -> satoshi price 103.5 toman. 5 cents materials -> 49 sats;
        # 6 cents envelope -> 58 sats; 75 cents postage -> 725 sats.
        # ceil(5% * (501 + 156 + 49 + 58 + 725)) = ceil(5% * 1489) = 75.
        # ceil((1489 + 75) * 103.5) = ceil(1564 * 103.5) = 161874 toman.
        for include_tag in (False, True):
            row = quote_for_principal(*inputs, 501, include_tag=include_tag)
            self.assertEqual(row["network_sats"], 156)
            self.assertEqual(row["materials_sats"], 49)
            self.assertEqual(row["envelope_sats"], 58)
            self.assertEqual(row["post_sats"], 725)
            # Group 2 is print + seal + the optional label; group 3 is envelope + postage.
            self.assertEqual(row["print_materials_sats"], row["materials_sats"] + row["tag_sats"])
            self.assertEqual(row["post_total_sats"], row["envelope_sats"] + row["post_sats"])
            self.assertEqual(row["post_total_sats"], 783)
            self.assertEqual(row["costs"]["materials_sats"], 49)
            self.assertEqual(row["costs"]["envelope_sats"], 58)
            self.assertEqual(row["costs"]["post_sats"], 725)
            self.assertEqual(row["costs"]["print_materials_sats"], row["print_materials_sats"])
            self.assertEqual(row["costs"]["post_total_sats"], 783)
            self.assertEqual(row["assumptions"]["materials_usd"], "0.05")
            self.assertEqual(row["assumptions"]["post_usd"], "0.75")
            self.assertEqual(
                (row["assumptions"]["seal_usd"], row["assumptions"]["paper_usd"],
                 row["assumptions"]["print_usd"], row["assumptions"]["envelope_usd"]),
                ("0.03", "0.01", "0.01", "0.06"))
            table = quote_table(*inputs, include_tag=include_tag)["rows"][0]
            self.assertEqual((table["materials_sats"], table["envelope_sats"], table["post_sats"]),
                             (49, 58, 725))
        row = quote_for_principal(*inputs, 501)
        self.assertEqual((row["operator_sats"], row["total_sats"], row["total_toman"]),
                         (75, 1564, 161874))
        with self.assertRaisesRegex(ValueError, "insufficient"):
            quote_for_budget(*inputs, 161873)
        self.assertEqual(quote_for_budget(*inputs, 161874)["principal_sats"], 501)

    def test_the_two_fixed_acquisition_fees_are_gone_from_every_payload(self):
        """The 2-cent conversion fee and the 423-satoshi transfer must not return."""
        from pricing import quote_for_budget, quote_for_principal, quote_table

        inputs = ("10000000000", "100000", "1.1")
        for payload in (quote_table(*inputs),
                        quote_for_principal(*inputs, 501),
                        quote_for_budget(*inputs, 500000)):
            for key in ("convert_sats", "transfer_sats"):
                self.assertNotIn(key, payload["costs"], key)
                self.assertNotIn(key, payload["assumptions"], key)
                self.assertNotIn(key, payload, key)
            for key in ("convert_usd", "transfer_sats"):
                self.assertNotIn(key, payload["assumptions"], key)
            self.assertIn("print_materials_sats", payload["costs"])
            self.assertIn("post_total_sats", payload["costs"])
            self.assertIs(payload["assumptions"]["has_wallet"], False)
        for row in quote_table(*inputs)["rows"]:
            for key in ("convert_sats", "transfer_sats"):
                self.assertNotIn(key, row, key)
            self.assertEqual(row["post_total_sats"], row["envelope_sats"] + row["post_sats"])

    def test_optional_tag_is_separate_and_included_in_operator_subtotal(self):
        from fractions import Fraction
        from pricing import quote_table, quote_for_principal, quote_for_budget

        ceiling = lambda x: -(-x.numerator // x.denominator)
        for fee in ("1.1", "2.3456789", "8.7654321"):
            for include_tag in (False, True):
                inputs = ("12345678901.12345678", "98765.4321", fee)
                sat = Fraction(inputs[0]) * Fraction(207, 200) / 100000000
                usdt = Fraction(inputs[1])
                tag = ceiling(Fraction(12, 100) * usdt / sat) if include_tag else 0
                table = quote_table(*inputs, include_tag=include_tag)
                self.assertEqual(table["costs"]["tag_sats"], tag)
                self.assertEqual(table["costs"]["print_materials_sats"],
                                 table["costs"]["materials_sats"] + tag)
                self.assertEqual(table["assumptions"]["tag_usd"], "0.12")
                self.assertIs(table["assumptions"]["include_tag"], include_tag)
                for row in table["rows"]:
                    self.assertEqual(row["tag_sats"], tag)
                    subtotal = (row["principal_sats"] + row["network_sats"]
                                + row["materials_sats"] + row["envelope_sats"]
                                + row["post_sats"] + tag)
                    self.assertEqual(row["operator_sats"], ceiling(Fraction(1, 20) * subtotal))
                    self.assertEqual(row["total_toman"],
                                     ceiling(ceiling(Fraction(21, 20) * subtotal) * sat))
                    custom = (quote_for_principal(*inputs, 501, include_tag=include_tag)
                              if row["budget_toman"] is None else
                              quote_for_budget(*inputs, row["budget_toman"], include_tag=include_tag))
                    self.assertEqual({key: custom[key] for key in row}, row)
                    if row["budget_toman"] is not None:
                        # Independent inverse: binary search on this oracle's own cost
                        # function, so no closed-form approximation can drift.
                        def cost(principal):
                            sub = (principal + row["network_sats"] + row["materials_sats"]
                                   + row["envelope_sats"] + row["post_sats"] + tag)
                            return ceiling(ceiling(Fraction(21, 20) * sub) * sat)
                        low, high = 501, 2100000000000000
                        while low < high:
                            middle = (low + high + 1) // 2
                            if cost(middle) <= row["budget_toman"]:
                                low = middle
                            else:
                                high = middle - 1
                        self.assertEqual(row["principal_sats"], low)
        self.assertEqual(quote_table(*inputs), quote_table(*inputs, include_tag=False))

    def test_has_wallet_drops_print_and_postal_groups_but_keeps_network(self):
        from fractions import Fraction
        from pricing import quote_for_budget, quote_for_principal, quote_table

        ceiling = lambda x: -(-x.numerator // x.denominator)
        inputs = ("10000000000", "100000", "1.1")
        cash = quote_for_principal(*inputs, 501)
        wallet = quote_for_principal(*inputs, 501, has_wallet=True)
        # No card is printed, sealed, labelled or mailed, so groups 2 and 3 vanish.
        for key in ("materials_sats", "tag_sats", "envelope_sats", "post_sats",
                    "print_materials_sats", "post_total_sats", "shared_sats"):
            self.assertEqual(wallet[key], 0, key)
        # The bitcoin still travels to the buyer's own address, so the network fee
        # and the principal are untouched, and the operator fee still applies.
        self.assertEqual(wallet["network_sats"], cash["network_sats"])
        self.assertEqual(wallet["principal_sats"], 501)
        self.assertEqual(wallet["card_sats"], 501 + cash["network_sats"])
        self.assertEqual(wallet["operator_sats"], ceiling(Fraction(1, 20) * wallet["card_sats"]))
        self.assertLess(wallet["total_sats"], cash["total_sats"])
        self.assertLess(wallet["total_toman"], cash["total_toman"])
        # The tag cannot survive a wallet-only order: there is no card to label.
        self.assertEqual(quote_for_principal(*inputs, 501, include_tag=True,
                                             has_wallet=True)["tag_sats"], 0)
        # The choice reaches the table, the single quote and the budget inverse.
        table = quote_table(*inputs, has_wallet=True)
        self.assertIs(table["assumptions"]["has_wallet"], True)
        self.assertEqual(table["costs"]["post_total_sats"], 0)
        self.assertEqual(table["rows"][0]["total_sats"], wallet["total_sats"])
        self.assertEqual(quote_for_budget(*inputs, wallet["total_toman"],
                                          has_wallet=True)["principal_sats"], 501)
        with self.assertRaisesRegex(ValueError, "insufficient"):
            quote_for_budget(*inputs, wallet["total_toman"] - 1, has_wallet=True)
        # Both choices together stay consistent: nothing physical is left to pay for.
        both = quote_for_principal(*inputs, 501, in_person=True, has_wallet=True)
        self.assertEqual(both["total_sats"], wallet["total_sats"])

    def test_three_cost_groups_plus_operator_fee_are_the_published_total(self):
        from fractions import Fraction
        from pricing import quote_for_principal, quote_table

        ceiling = lambda x: -(-x.numerator // x.denominator)
        inputs = ("12345678901.12345678", "98765.4321", "2.125")
        sat = Fraction(inputs[0]) * Fraction(207, 200) / 100000000
        # Group 1 — the buyer's own all-in purchase cost: the 3.5% markup lives in
        # the rate, so the group has no separate satoshi row and is proved by the
        # rate itself. Groups 2 and 3 are named sats amounts.
        self.assertEqual(Fraction(quote_table(*inputs)["rates"]["btc_toman"]),
                         Fraction(inputs[0]) * Fraction(207, 200))
        self.assertEqual(quote_table(*inputs)["assumptions"]["exchange_fee_percent"], "3.5")
        for tag in (False, True):
            for hand in (False, True):
                for wallet in (False, True):
                    row = quote_for_principal(*inputs, 5000, include_tag=tag,
                                              in_person=hand, has_wallet=wallet)
                    print_group = row["print_materials_sats"]
                    post_group = row["post_total_sats"]
                    self.assertEqual(print_group, row["materials_sats"] + row["tag_sats"])
                    self.assertEqual(post_group, row["envelope_sats"] + row["post_sats"])
                    self.assertEqual(
                        row["principal_sats"] + row["network_sats"] + print_group + post_group
                        + row["operator_sats"], row["total_sats"])
                    self.assertEqual(row["operator_sats"],
                                     ceiling(Fraction(1, 20) * (row["total_sats"] - row["operator_sats"])))
                    self.assertEqual(row["total_toman"], ceiling(row["total_sats"] * sat))

    def test_exchange_markup_is_charged_once_and_never_as_a_principal_fee(self):
        """The 3.5% acquisition markup lives in the rate only; no per-row percentage fee."""
        from fractions import Fraction
        from pricing import quote_for_principal, quote_table

        inputs = ("10000000000", "100000", "1.1")
        table = quote_table(*inputs)
        raw_btc, raw_usdt = Fraction(inputs[0]), Fraction(inputs[1])
        # The bitcoin rate carries exactly one 3.5% markup, the tether rate none.
        self.assertEqual(Fraction(table["rates"]["btc_toman"]), raw_btc * Fraction(207, 200))
        self.assertEqual(Fraction(table["rates"]["usdt_toman"]), raw_usdt)
        self.assertEqual(Fraction(table["rates"]["satoshi_toman"]),
                         raw_btc * Fraction(207, 200) / 100000000)
        self.assertEqual(table["assumptions"]["exchange_fee_percent"], "3.5")
        for row in table["rows"]:
            # No second percentage charge on the principal: the old
            # acquisition_sats key must not come back.
            self.assertNotIn("acquisition_sats", row)
            self.assertEqual(row["total_sats"],
                             row["principal_sats"] + row["network_sats"]
                             + row["materials_sats"] + row["envelope_sats"]
                             + row["post_sats"] + row["tag_sats"] + row["operator_sats"])
        self.assertNotIn("acquisition_sats", table["costs"])
        # Doubling the principal adds only the extra principal plus the 5% operator
        # fee on it. A second 3.5% charge would add another 3500 satoshis here.
        small = quote_for_principal(*inputs, 100000)
        large = quote_for_principal(*inputs, 200000)
        self.assertEqual(large["operator_sats"] - small["operator_sats"], 5000)
        self.assertEqual(large["total_sats"] - small["total_sats"], 105000)
        self.assertEqual(large["total_sats"] - small["total_sats"],
                         100000 + (large["operator_sats"] - small["operator_sats"]))

    def test_option_flags_require_booleans_and_ignore_hostile_decimal_context(self):
        from decimal import Decimal, localcontext
        from pricing import quote_table, quote_for_principal, quote_for_budget
        for function, extra in ((quote_table, ()), (quote_for_principal, (501,)), (quote_for_budget, (500000,))):
            inputs = ('12345678901.12345678', '98765.4321', '1.23456789', *extra)
            for flag in ('include_tag', 'in_person', 'has_wallet'):
                for invalid in ('false', 'true', 0, 1, None, [], {}):
                    with self.subTest(function=function.__name__, flag=flag, invalid=invalid):
                        with self.assertRaises(ValueError):
                            function(*inputs, **{flag: invalid})
            expected = function(*inputs, include_tag=True, in_person=True, has_wallet=True)
            with localcontext() as context:
                context.prec = 1
                context.Emax, context.Emin = 1, -1
                for signal in context.traps:
                    context.traps[signal] = True
                self.assertEqual(function(*(Decimal(x) for x in inputs[:3]), *extra,
                                          include_tag=True, in_person=True, has_wallet=True), expected)

    def test_first_quote_exposes_adjusted_rates_and_each_rounded_cost(self):
        pricing = importlib.import_module("pricing")
        quote_table = getattr(pricing, "quote_table", None)
        self.assertTrue(callable(quote_table), "quote_table must be implemented")
        quote = quote_table("10000000000", "100000", "1.1")
        self.assertEqual(quote["rates"], {
            "btc_toman": "10350000000", "usdt_toman": "100000",
            "satoshi_toman": "103.5",
        })
        self.assertEqual(quote["assumptions"], {
            "exchange_fee_percent": "3.5", "operator_fee_percent": "5",
            "materials_usd": "0.05", "post_usd": "0.75",
            "tag_usd": "0.12", "include_tag": False, "in_person": False,
            "has_wallet": False, "transaction_vbytes": 141,
            "network_fee_rate": "1.1",
            "seal_usd": "0.03", "paper_usd": "0.01", "print_usd": "0.01", "envelope_usd": "0.06",
        })
        self.assertEqual(quote["costs"], {"network_sats": 156, "materials_sats": 49,
                                          "envelope_sats": 58, "post_sats": 725, "tag_sats": 0,
                                          "print_materials_sats": 49, "post_total_sats": 783})
        # subtotal 501+156+49+58+725 = 1489; ceil(0.05 * 1489) = 75;
        # total 1564; ceil(1564 * 103.5) = 161874 toman.
        self.assertEqual(quote["rows"][0], {
            "principal_sats": 501, "btc": "0.00000501", "quantity": 1,
            "network_sats": 156, "materials_sats": 49,
            "envelope_sats": 58, "post_sats": 725, "tag_sats": 0,
            "print_materials_sats": 49, "post_total_sats": 783,
            # Card-bound costs (principal + network + materials + tag) and the
            # shared block paid once per order (envelope + postage).
            "card_sats": 706, "shared_sats": 783, "shared_share_sats": 783,
            "operator_sats": 75, "operator_toman": 7763, "total_sats": 1564,
            "total_toman": 161874, "total_rial": 1618740,
            "budget_toman": None, "remainder_toman": 0,
        })

    def test_budget_rows_maximize_principal_without_claiming_exact_utilization(self):
        from decimal import Decimal, ROUND_CEILING
        from pricing import quote_table

        quote = quote_table("10000000000", "100000", "1.1")
        rows = quote["rows"]
        # The minimum package now costs more than 100,000 toman, so the first
        # budget row starts at the next 100,000-toman multiple above it.
        first_budget = (rows[0]["total_toman"] // 100_000 + 1) * 100_000
        budgets = list(range(first_budget, 3000001, 100000))
        self.assertEqual([row["budget_toman"] for row in rows[1:]], budgets)
        self.assertEqual(len(rows), len(budgets) + 1)
        self.assertTrue(any(row["remainder_toman"] > 0 for row in rows[1:]))
        previous = rows[0]
        for row in rows[1:]:
            with self.subTest(budget=row["budget_toman"]):
                self.assertGreaterEqual(row["principal_sats"], 501)
                self.assertGreaterEqual(row["principal_sats"], previous["principal_sats"])
                self.assertGreaterEqual(row["total_toman"], previous["total_toman"])
                self.assertLessEqual(row["total_toman"], row["budget_toman"])
                self.assertEqual(row["remainder_toman"], row["budget_toman"] - row["total_toman"])
                next_principal = row["principal_sats"] + 1
                next_subtotal = next_principal + 156 + 49 + 58 + 725
                next_operator = int((Decimal(next_subtotal) * Decimal("0.05")).to_integral_value(rounding=ROUND_CEILING))
                next_total = int((Decimal(next_subtotal + next_operator) * Decimal("103.5")).to_integral_value(rounding=ROUND_CEILING))
                self.assertGreater(next_total, row["budget_toman"])
                previous = row

    def test_quote_rejects_nonpositive_nonfinite_and_out_of_bound_rates(self):
        from decimal import Decimal
        from pricing import quote_table

        shared_invalid = (0, -1, True, False, None, 1.0, "", "bad", " 1",
                          "1 ", "١", "NaN", "sNaN", "Infinity", "-Infinity",
                          Decimal("NaN"), Decimal("Infinity"), "1e-10000000",
                          Decimal("1e-10000000"), "1.0000000000000000001")
        for index in range(3):
            maximum = "10000.0001" if index == 2 else "1000000000000000.01"
            for value in (*shared_invalid, maximum):
                values = ["10000000000", "100000", "1"]
                values[index] = value
                with self.subTest(index=index, value=value):
                    with self.assertRaises(ValueError):
                        quote_table(*values)

    def test_quote_ignores_callers_decimal_precision_rounding_and_traps(self):
        from decimal import Decimal, Inexact, ROUND_DOWN, Rounded, localcontext
        from pricing import btc_to_sats, quote_table, sats_to_btc

        expected = quote_table("12345678901.12345678", "98765.4321", "1.23456789")
        with localcontext() as context:
            context.prec = 3
            context.rounding = ROUND_DOWN
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            self.assertEqual(btc_to_sats("1.12345678"), 112345678)
            self.assertEqual(sats_to_btc(112345678), "1.12345678")
            actual = quote_table(Decimal("12345678901.12345678"), Decimal("98765.4321"), Decimal("1.23456789"))
        self.assertEqual(actual, expected)

    def test_budgets_start_strictly_above_initial_total_including_exact_multiple(self):
        from pricing import quote_table

        # Chosen so the 501-satoshi row costs exactly 100,000 toman with the
        # 5-cent materials, 6-cent envelope, 75-cent postage and 3.5% markup model.
        quote = quote_table("18195366000", "1", "0.001")
        self.assertEqual(quote["rows"][0]["total_toman"], 100000)
        self.assertEqual(quote["rows"][1]["budget_toman"], 200000)
        self.assertEqual(quote["rows"][-1]["budget_toman"], 3000000)

    def test_first_quote_survives_when_no_budget_row_is_affordable(self):
        from pricing import quote_table

        quote = quote_table(1000000000000000, 1000000000000000, 10000)
        self.assertEqual(len(quote["rows"]), 1)
        self.assertEqual(quote["rows"][0]["principal_sats"], 501)
        self.assertGreater(quote["rows"][0]["total_toman"], 3000000)

    def test_fractional_rates_match_exact_rational_ceiling_oracle_and_json(self):
        from decimal import Decimal
        from fractions import Fraction
        import json
        from pricing import btc_to_sats, quote_table

        def ceiling(value):
            return -(-value.numerator // value.denominator)

        for btc, usdt, fee in (
            ("12345678901.12345678", "98765.4321", "1.23456789"),
            ("999999999999999.999999999999999999", "0.000000000000000001", "9999.999999999999999999"),
            ("0.00000001", "0.00000001", "0.000000000000000001"),
        ):
            with self.subTest(btc=btc, usdt=usdt, fee=fee):
                quote = quote_table(Decimal(btc), Decimal(usdt), Decimal(fee))
                self.assertEqual(json.loads(json.dumps(quote, allow_nan=False)), quote)
                adjusted_btc = Fraction(btc) * Fraction(207, 200)
                adjusted_usdt = Fraction(usdt)
                sat_price = adjusted_btc / 100000000
                network = ceiling(Fraction(fee) * 141)
                materials = ceiling(Fraction(5, 100) * adjusted_usdt / sat_price)
                envelope = ceiling(Fraction(6, 100) * adjusted_usdt / sat_price)
                post = ceiling(Fraction(75, 100) * adjusted_usdt / sat_price)
                self.assertEqual(quote["costs"], {"network_sats": network,
                                                  "materials_sats": materials,
                                                  "envelope_sats": envelope,
                                                  "post_sats": post, "tag_sats": 0,
                                                  "print_materials_sats": materials,
                                                  "post_total_sats": envelope + post})
                self.assertEqual(Fraction(quote["rates"]["btc_toman"]), adjusted_btc)
                self.assertEqual(Fraction(quote["rates"]["usdt_toman"]), adjusted_usdt)
                for row in quote["rows"]:
                    principal = row["principal_sats"]
                    self.assertEqual(btc_to_sats(row["btc"]), principal)
                    subtotal = principal + network + materials + envelope + post
                    operator = ceiling(Fraction(1, 20) * subtotal)
                    self.assertEqual(row["operator_sats"], operator)
                    self.assertEqual(row["total_sats"], subtotal + operator)
                    self.assertEqual(row["total_toman"], ceiling((subtotal + operator) * sat_price))
                    self.assertEqual(row["total_rial"], row["total_toman"] * 10)


class CustomQuoteTests(unittest.TestCase):
    def test_seeded_budget_quotes_match_closed_form_fraction_inverse(self):
        from fractions import Fraction
        import random
        from pricing import MAX_SATOSHIS, quote_for_budget

        rng = random.Random(48023)
        ceiling = lambda x: -(-x.numerator // x.denominator)
        for case in range(160):
            def decimal_rate(maximum, places):
                scale = 10**places
                numerator = rng.randint(1, maximum * scale)
                whole, remainder = divmod(numerator, scale)
                return f"{whole}.{remainder:0{places}d}" if places else str(whole)

            btc = decimal_rate(10**15, rng.choice((0, 8, 18)))
            usdt = decimal_rate(10**8, rng.choice((0, 8, 18)))
            fee = decimal_rate(10000, rng.choice((0, 8, 18)))
            sat_price = Fraction(btc) * Fraction(207, 200) / 100000000
            network = ceiling(Fraction(fee) * 141)
            materials = ceiling(Fraction(5, 100) * Fraction(usdt) / sat_price)
            envelope = ceiling(Fraction(6, 100) * Fraction(usdt) / sat_price)
            post = ceiling(Fraction(75, 100) * Fraction(usdt) / sat_price)
            fixed = network + materials + envelope + post
            principal = rng.choice((501, rng.randint(501, MAX_SATOSHIS), MAX_SATOSHIS))
            subtotal = principal + fixed
            budget = ceiling(ceiling(Fraction(21, 20) * subtotal) * sat_price) + rng.choice((-1, 0, 1))
            # Algebraically invert the two integer ceilings, independently of
            # production's binary search: total_sats <= floor(budget/sat_price).
            total_sats_limit = Fraction(budget) // sat_price
            subtotal_limit = 20 * total_sats_limit // 21
            expected_principal = min(MAX_SATOSHIS, subtotal_limit - fixed)
            with self.subTest(case=case, budget=budget):
                if expected_principal < 501:
                    with self.assertRaisesRegex(ValueError, "insufficient"):
                        quote_for_budget(btc, usdt, fee, budget)
                    continue
                row = quote_for_budget(btc, usdt, fee, budget)
                self.assertEqual(row["principal_sats"], expected_principal)
                actual_subtotal = expected_principal + fixed
                expected_total = ceiling(ceiling(Fraction(21, 20) * actual_subtotal) * sat_price)
                self.assertEqual(row["total_toman"], expected_total)
                self.assertEqual(row["remainder_toman"], budget - expected_total)

    def test_custom_rows_preserve_the_entire_existing_table_row_contract(self):
        from pricing import quote_for_budget, quote_for_principal, quote_table

        for inputs in (("10000000000", "100000", "1.1"),
                       ("12345678901.12345678", "98765.4321", "1.23456789"),
                       ("0.00000001", "0.00000001", "0.000000000000000001")):
            table = quote_table(*inputs)
            for row in table["rows"]:
                custom = (quote_for_principal(*inputs, row["principal_sats"])
                          if row["budget_toman"] is None
                          else quote_for_budget(*inputs, row["budget_toman"]))
                self.assertEqual({key: custom[key] for key in row}, row)
                for key in ("rates", "assumptions", "costs"):
                    self.assertEqual(custom[key], table[key])

    def test_all_conversion_text_is_bounded_before_decimal_parsing(self):
        from pricing import btc_to_sats, sats_to_btc

        self.assertEqual(btc_to_sats("0" * 63 + "1"), 100000000)
        self.assertEqual(sats_to_btc("0" * 63 + "1"), "0.00000001")
        for convert in (btc_to_sats, sats_to_btc):
            for invalid in ("0" * 64 + "1", "0" * 10000):
                with self.subTest(convert=convert.__name__, length=len(invalid)):
                    with self.assertRaisesRegex(ValueError, "64"):
                        convert(invalid)

    def test_raw_asset_value_uses_unadjusted_btc_without_any_package_fee(self):
        from decimal import Decimal, localcontext
        import pricing

        value = getattr(pricing, "raw_asset_toman", None)
        self.assertTrue(callable(value), "raw_asset_toman must be implemented")
        for raw_btc, principal, expected in (
            ("10000000000", 3000, "300000"),
            ("12345678901.12345678", "3000", "370370.3670337037034"),
            ("10000000000", 0, "0"),
            ("0.000000000000000001", 1, "0.00000000000000000000000001"),
            ("1000000000000000", pricing.MAX_SATOSHIS, "21000000000000000000000"),
        ):
            with self.subTest(raw_btc=raw_btc, principal=principal):
                with localcontext() as context:
                    context.prec = 1
                    context.Emax, context.Emin = 1, -1
                    for signal in context.traps:
                        context.traps[signal] = True
                    self.assertEqual(value(Decimal(raw_btc), principal), expected)
        for principal in (-1, True, False, 1.0, Decimal("1"), "1e3", "0" * 65, pricing.MAX_SATOSHIS + 1):
            with self.subTest(invalid=principal):
                with self.assertRaises(ValueError):
                    value("10000000000", principal)

    def test_budget_rejects_noninteger_or_overlong_input(self):
        from decimal import Decimal
        from pricing import quote_for_budget

        for invalid in (
            -1, True, False, 100000.0, Decimal("100000"), None, "", " 100000",
            "100000 ", "100000\n", "+100000", "-0", "100000.0", "1e5",
            "١٠٠٠٠٠", "１00000", "1_00000", "0" * 59 + "100000", "9" * 10000,
            10**64,
        ):
            with self.subTest(invalid=repr(invalid)[:80]):
                with self.assertRaises(ValueError):
                    quote_for_budget("10000000000", "100000", "1.1", invalid)
        self.assertEqual(
            quote_for_budget("10000000000", "100000", "1.1", "0" * 58 + "300000"),
            quote_for_budget("10000000000", "100000", "1.1", 300000),
        )

    def test_decimal_rates_do_not_normalize_positive_exponents_or_signed_zero(self):
        from decimal import Decimal, localcontext
        from pricing import quote_for_principal

        for index in range(3):
            for invalid in (Decimal("1E+3"), Decimal("-0"), Decimal("sNaN"),
                            "0" * 64 + "1", "1E+3", "1e3", 1.0, True):
                values = ["10000000000", "100000", "1.1"]
                values[index] = invalid
                with self.subTest(index=index, invalid=invalid):
                    with localcontext() as context:
                        for signal in context.traps:
                            context.traps[signal] = True
                        with self.assertRaises(ValueError):
                            quote_for_principal(*values, 3000)

    def test_custom_quotes_ignore_every_caller_decimal_trap_and_exponent_range(self):
        from decimal import Decimal, ROUND_FLOOR, localcontext
        from pricing import quote_for_budget, quote_for_principal

        inputs = ("12345678901.12345678", "98765.4321", "1.23456789")
        principal = quote_for_principal(*inputs, 3000)
        budget = quote_for_budget(*inputs, 50000001)
        with localcontext() as context:
            context.prec = 1
            context.rounding = ROUND_FLOOR
            context.Emax, context.Emin = 1, -1
            context.clamp = 1
            for signal in context.traps:
                context.traps[signal] = True
            self.assertEqual(quote_for_principal(*(Decimal(value) for value in inputs), "3000"), principal)
            self.assertEqual(quote_for_budget(*(Decimal(value) for value in inputs), "50000001"), budget)

    def test_golden_vectors_have_independent_rational_forward_and_inverse_proofs(self):
        from fractions import Fraction
        import json

        fixture = json.loads((Path(__file__).parent / "fixtures" / "quote_calculator.json").read_text())
        ceiling = lambda x: -(-x.numerator // x.denominator)
        supply = 2100000000000000
        self.assertEqual(len(fixture["cases"]), 17)
        for case in fixture["cases"]:
            with self.subTest(case=case["id"]):
                inputs = case["inputs"]
                btc, usdt = Fraction(inputs["btc_toman"]), Fraction(inputs["usdt_toman"])
                sat_price = btc * Fraction(207, 200) / 100000000
                network = ceiling(Fraction(inputs["fee_rate"]) * 141)
                materials = ceiling(Fraction(5, 100) * usdt / sat_price)
                hand = inputs.get("in_person", False)
                wallet = inputs.get("has_wallet", False)
                mailed = not (hand or wallet)
                envelope = ceiling(Fraction(6, 100) * usdt / sat_price) if mailed else 0
                post = ceiling(Fraction(75, 100) * usdt / sat_price) if mailed else 0
                tag = (ceiling(Fraction(12, 100) * usdt / sat_price)
                       if inputs.get("include_tag", False) and not wallet else 0)
                materials = 0 if wallet else materials
                fixed = network + materials + envelope + post + tag

                def cost(principal):
                    return ceiling(ceiling(Fraction(21, 20) * (principal + fixed)) * sat_price)

                budget = int(inputs["budget_toman"]) if case["mode"] == "budget" else None
                if "expected_error" in case:
                    self.assertLess(budget, cost(501))
                    self.assertEqual(int(case["expected_error"]["minimum_total_toman"]), cost(501))
                    continue
                expected = case["expected"]
                if budget is None:
                    principal = int(inputs["principal_sats"])
                else:
                    # Independent exact inverse: binary search on this oracle's own cost
                    # function, so no closed-form approximation can drift from the model.
                    low, high = 501, supply
                    while low < high:
                        middle = (low + high + 1) // 2
                        if cost(middle) <= budget:
                            low = middle
                        else:
                            high = middle - 1
                    principal = low
                self.assertGreaterEqual(principal, 501)
                self.assertEqual(int(expected["principal_sats"]), principal)
                self.assertEqual(expected["btc"], f"{principal // 100000000}.{principal % 100000000:08d}")
                subtotal = principal + fixed
                operator = ceiling(Fraction(1, 20) * subtotal)
                values = {"network_sats": network, "materials_sats": materials,
                          "envelope_sats": envelope, "post_sats": post,
                          "tag_sats": tag,
                          "print_materials_sats": materials + tag,
                          "post_total_sats": envelope + post,
                          "operator_sats": operator, "total_sats": subtotal + operator,
                          "total_toman": cost(principal), "total_rial": cost(principal) * 10,
                          "remainder_toman": 0 if budget is None else budget - cost(principal)}
                for key, value in values.items():
                    self.assertEqual(expected[key], str(value), key)
                self.assertEqual(expected["budget_toman"], None if budget is None else str(budget))
                self.assertEqual(expected["costs"], {key: str(value) for key, value in
                                                  (("network_sats", network),
                                                   ("materials_sats", materials),
                                                   ("envelope_sats", envelope),
                                                   ("post_sats", post), ("tag_sats", tag),
                                                   ("print_materials_sats", materials + tag),
                                                   ("post_total_sats", envelope + post))})
                self.assertEqual(expected["assumptions"]["materials_usd"], "0.05")
                self.assertEqual(expected["assumptions"]["post_usd"], "0.75")
                self.assertEqual(expected["assumptions"]["exchange_fee_percent"], "3.5")
                self.assertEqual(expected["assumptions"]["operator_fee_percent"], "5")
                self.assertNotIn("convert_usd", expected["assumptions"])
                self.assertNotIn("transfer_sats", expected["assumptions"])
                self.assertEqual(expected["assumptions"]["seal_usd"], "0.03")
                self.assertEqual(expected["assumptions"]["paper_usd"], "0.01")
                self.assertEqual(expected["assumptions"]["print_usd"], "0.01")
                self.assertEqual(expected["assumptions"]["envelope_usd"], "0.06")
                self.assertEqual(Fraction(expected["rates"]["btc_toman"]), btc * Fraction(207, 200))
                self.assertEqual(Fraction(expected["rates"]["usdt_toman"]), usdt)
                self.assertEqual(Fraction(expected["rates"]["satoshi_toman"]), sat_price)
                self.assertEqual(Fraction(case["raw_asset_toman"]), btc * principal / 100000000)
                if budget is not None:
                    self.assertLessEqual(cost(principal), budget)
                    if principal < supply:
                        self.assertGreater(cost(principal + 1), budget)
                        self.assertEqual(int(case["next_principal_total_toman"]), cost(principal + 1))
                if case["id"] in ("budget_exact_minimum", "budget_exact_3000", "budget_exact_supply_bound"):
                    self.assertEqual(budget, cost(principal))
                if case["id"] == "budget_exact_minimum":
                    self.assertEqual(principal, 501)
                if case["id"] == "budget_exact_3000":
                    self.assertEqual(principal, 3000)
                if case["id"] == "budget_below_3000_boundary":
                    self.assertEqual((principal, budget), (2999, cost(3000) - 1))
                if case["id"] == "budget_below_supply_boundary":
                    self.assertEqual((principal, budget), (supply - 1, cost(supply) - 1))

    def test_public_synthetic_golden_vectors_match_exact_core(self):
        import json
        import pricing

        fixture_path = Path(__file__).parent / "fixtures" / "quote_calculator.json"
        fixture = json.loads(fixture_path.read_text())
        self.assertEqual(fixture["schema_version"], 1)

        def stringify_integers(value):
            if type(value) is int:
                return str(value)
            if isinstance(value, dict):
                return {key: stringify_integers(item) for key, item in value.items()}
            return value

        for case in fixture["cases"]:
            with self.subTest(case=case["id"]):
                inputs = case["inputs"]
                function = pricing.quote_for_principal if case["mode"] == "principal" else pricing.quote_for_budget
                if "expected_error" in case:
                    with self.assertRaisesRegex(ValueError, "insufficient.*501"):
                        function(**inputs)
                else:
                    actual = function(**inputs)
                    self.assertEqual(stringify_integers(actual), case["expected"])
                    self.assertEqual(pricing.raw_asset_toman(inputs["btc_toman"], actual["principal_sats"]),
                                     case["raw_asset_toman"])
                    if "next_principal_total_toman" in case:
                        self.assertGreater(int(case["next_principal_total_toman"]), int(inputs["budget_toman"]))

    def test_insufficient_budget_raises_without_a_fictitious_principal(self):
        from pricing import quote_for_budget, quote_for_principal

        for rates in (
            ("10000000000", "100000", "1.1"),
            ("12345678901.12345678", "98765.4321", "1.23456789"),
            ("1000000000000000", "1000000000000000", "10000"),
        ):
            minimum = quote_for_principal(*rates, 501)["total_toman"]
            for budget in (0, minimum - 1):
                with self.subTest(rates=rates, budget=budget):
                    with self.assertRaisesRegex(ValueError, "insufficient.*501"):
                        quote_for_budget(*rates, budget)
            boundary = quote_for_budget(*rates, minimum)
            self.assertEqual(boundary["total_toman"], minimum)
            self.assertEqual(boundary["remainder_toman"], 0)

    def test_budget_inverse_has_no_table_cap_and_proves_maximality(self):
        from fractions import Fraction
        import pricing

        inverse = getattr(pricing, "quote_for_budget", None)
        self.assertTrue(callable(inverse), "quote_for_budget must be implemented")
        for btc, usdt, fee, budget in (
            ("10000000000", "100000", "1.1", 161874),
            ("10000000000", "100000", "1.1", 300000),
            ("10000000000", "100000", "1.1", 50000000),
            ("12345678901.12345678", "98765.4321", "1.23456789", 50000001),
            ("0.000000000000000001", "0.000000000000000001", "0.000000000000000001", 1),
            ("1000000000000000", "1000000000000000", "10000", 10**63),
        ):
            with self.subTest(btc=btc, budget=budget):
                row = inverse(btc, usdt, fee, budget)
                ceiling = lambda x: -(-x.numerator // x.denominator)
                sat_price = Fraction(btc) * Fraction(207, 200) / 100000000
                network = ceiling(Fraction(fee) * 141)
                materials = ceiling(Fraction(5, 100) * Fraction(usdt) / sat_price)
                envelope = ceiling(Fraction(6, 100) * Fraction(usdt) / sat_price)
                post = ceiling(Fraction(75, 100) * Fraction(usdt) / sat_price)
                fixed = network + materials + envelope + post

                def cost(principal):
                    subtotal = principal + fixed
                    return ceiling((subtotal + ceiling(Fraction(1, 20) * subtotal)) * sat_price)

                self.assertGreaterEqual(row["principal_sats"], 501)
                self.assertLessEqual(row["principal_sats"], pricing.MAX_SATOSHIS)
                self.assertEqual(row["total_toman"], cost(row["principal_sats"]))
                self.assertLessEqual(row["total_toman"], budget)
                self.assertEqual(row["budget_toman"], budget)
                self.assertEqual(row["remainder_toman"], budget - row["total_toman"])
                if row["principal_sats"] < pricing.MAX_SATOSHIS:
                    self.assertGreater(cost(row["principal_sats"] + 1), budget)
                principal_row = pricing.quote_for_principal(btc, usdt, fee, row["principal_sats"])
                self.assertEqual({**principal_row, "budget_toman": budget,
                                  "remainder_toman": budget - row["total_toman"]}, row)
        self.assertEqual(inverse("10000000000", "100000", "1.1", 161874)["principal_sats"], 501)
        self.assertEqual(inverse("10000000000", "100000", "1.1", 161874)["remainder_toman"], 0)
        self.assertGreater(inverse("10000000000", "100000", "1.1", 300000)["remainder_toman"], 0)

    def test_custom_principal_requires_bounded_unsigned_integer(self):
        from decimal import Decimal
        from pricing import MAX_SATOSHIS, quote_for_principal

        for invalid in (
            0, 499, -1, MAX_SATOSHIS + 1, True, False, 3000.0,
            Decimal("3000"), None, "", " 3000", "3000 ", "3000\n", "+3000",
            "-3000", "3000.0", "3e3", "٣٠٠٠", "３０００", "3_000",
            "0" * 61 + "3000", "9" * 10000,
        ):
            with self.subTest(invalid=repr(invalid)[:80]):
                with self.assertRaises(ValueError):
                    quote_for_principal("10000000000", "100000", "1.1", invalid)
        expected = quote_for_principal("10000000000", "100000", "1.1", 3000)
        self.assertEqual(
            quote_for_principal("10000000000", "100000", "1.1", "0" * 60 + "3000"),
            expected,
        )

    def test_custom_principal_matches_independent_fraction_oracle(self):
        from fractions import Fraction
        import json
        import pricing

        quote_for_principal = getattr(pricing, "quote_for_principal", None)
        self.assertTrue(callable(quote_for_principal), "quote_for_principal must be implemented")
        for btc, usdt, fee, principal in (
            ("10000000000", "100000", "1.1", 3000),
            ("12345678901.12345678", "98765.4321", "1.23456789", 3000),
            ("999999999999999.999999999999999999", "0.000000000000000001", "9999.999999999999999999", 501),
            ("0.000000000000000001", "1000000000000000", "0.000000000000000001", pricing.MAX_SATOSHIS),
        ):
            with self.subTest(btc=btc, principal=principal):
                row = quote_for_principal(btc, usdt, fee, principal)
                ceiling = lambda x: -(-x.numerator // x.denominator)
                sat_price = Fraction(btc) * Fraction(207, 200) / 100000000
                network = ceiling(Fraction(fee) * 141)
                materials = ceiling(Fraction(5, 100) * Fraction(usdt) / sat_price)
                envelope = ceiling(Fraction(6, 100) * Fraction(usdt) / sat_price)
                post = ceiling(Fraction(75, 100) * Fraction(usdt) / sat_price)
                operator = ceiling(Fraction(1, 20) * (principal + network + materials
                                                     + envelope + post))
                total = principal + network + materials + envelope + post + operator
                self.assertEqual({key: row[key] for key in (
                    "principal_sats", "network_sats", "materials_sats",
                    "envelope_sats", "post_sats", "print_materials_sats", "post_total_sats",
                    "operator_sats", "total_sats",
                    "total_toman", "total_rial", "budget_toman", "remainder_toman",
                )}, {
                    "principal_sats": principal, "network_sats": network,
                    "materials_sats": materials,
                    "envelope_sats": envelope, "post_sats": post,
                    "print_materials_sats": materials, "post_total_sats": envelope + post,
                    "operator_sats": operator, "total_sats": total,
                    "total_toman": ceiling(total * sat_price),
                    "total_rial": ceiling(total * sat_price) * 10,
                    "budget_toman": None, "remainder_toman": 0,
                })
                self.assertEqual(pricing.btc_to_sats(row["btc"]), principal)
                table = pricing.quote_table(btc, usdt, fee)
                for key in ("rates", "assumptions", "costs"):
                    self.assertEqual(row[key], table[key])
                self.assertEqual(json.loads(json.dumps(row, allow_nan=False)), row)


if __name__ == "__main__":
    unittest.main()
