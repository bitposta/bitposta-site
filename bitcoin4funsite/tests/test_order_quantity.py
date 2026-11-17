"""Order quantity: shared costs are paid once per order, card costs per card.

The owner's requirement: a buyer who orders five cards of different amounts pays
the exchange conversion fee, the 423-satoshi transfer, the postal envelope and the
postage ONE time, not five times. Card-bound costs (the envelope materials, the
delivery network fee, the optional tag and the principal) still scale with the
number of cards. Each table row must also expose the per-card share of the shared
cost so two orders of different quantities are comparable.
"""
import importlib.util
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
LOCKED_EXTERNALS = ('flask', 'jinja2', 'psycopg', 'psycopg2', 'werkzeug')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pricing = load('pricing', PROJECT / 'pricing.py')


RATES = ('10000000000', '100000', '1.1')


class OrderQuantityTest(unittest.TestCase):
    def test_default_quantity_is_one_and_keeps_the_single_card_arithmetic(self):
        quote = pricing.quote_for_principal(*RATES, 100000)
        self.assertEqual(quote['quantity'], 1)
        self.assertEqual(quote['card_sats'], 100000 + quote['network_sats']
                         + quote['materials_sats'] + quote['tag_sats'])
        self.assertEqual(quote['shared_sats'], quote['convert_sats']
                         + quote['transfer_sats'] + quote['envelope_sats'] + quote['post_sats'])
        # quantity 1 must not change any published total.
        self.assertEqual(quote['total_sats'], quote['card_sats'] + quote['shared_sats']
                         + quote['operator_sats'])

    def test_shared_costs_are_charged_once_for_a_multi_card_order(self):
        one = pricing.quote_for_principal(*RATES, 100000, quantity=1)
        five = pricing.quote_for_principal(*RATES, 100000, quantity=5)
        # The four shared components are identical, not multiplied.
        for key in ('convert_sats', 'transfer_sats', 'envelope_sats', 'post_sats'):
            self.assertEqual(five[key], one[key], key)
        self.assertEqual(five['shared_sats'], one['shared_sats'])
        # Card-bound costs scale linearly.
        self.assertEqual(five['card_sats'], one['card_sats'])
        self.assertEqual(five['quantity'], 5)
        # The order subtotal is 5 cards plus the shared block, exactly once.
        self.assertEqual(five['total_sats'] - five['operator_sats'],
                         5 * five['card_sats'] + five['shared_sats'])
        self.assertLess(five['total_sats'], 5 * one['total_sats'],
                        'five cards must cost less than five separate orders')

    def test_each_row_exposes_the_per_card_share_of_the_shared_cost(self):
        five = pricing.quote_for_principal(*RATES, 100000, quantity=5)
        # Share is the ceil of the shared block divided by the card count, so the
        # displayed per-card figure never under-states what the buyer pays.
        expected = -(-five['shared_sats'] // 5)
        self.assertEqual(five['shared_share_sats'], expected)
        self.assertGreaterEqual(five['shared_share_sats'] * 5, five['shared_sats'])

    def test_quantity_one_share_equals_the_whole_shared_block(self):
        one = pricing.quote_for_principal(*RATES, 100000, quantity=1)
        self.assertEqual(one['shared_share_sats'], one['shared_sats'])

    def test_toman_totals_follow_the_order_total_not_a_per_card_total(self):
        from fractions import Fraction
        ceiling = lambda x: -(-x.numerator // x.denominator)
        five = pricing.quote_for_principal(*RATES, 100000, quantity=5)
        sat = Fraction(five['rates']['satoshi_toman'])
        # ceil(total_sats * satoshi_toman), computed independently with Fractions.
        self.assertEqual(five['total_toman'], ceiling(five['total_sats'] * sat))
        self.assertEqual(five['total_rial'], five['total_toman'] * 10)

    def test_operator_fee_is_taken_from_the_whole_order_subtotal(self):
        from fractions import Fraction
        ceiling = lambda x: -(-x.numerator // x.denominator)
        five = pricing.quote_for_principal(*RATES, 100000, quantity=5)
        subtotal = 5 * five['card_sats'] + five['shared_sats']
        self.assertEqual(five['operator_sats'], ceiling(Fraction(3, 20) * subtotal))
        self.assertEqual(five['total_sats'], subtotal + five['operator_sats'])

    def test_quote_table_and_budget_accept_quantity(self):
        table = pricing.quote_table(*RATES, quantity=3)
        self.assertEqual(table['quantity'], 3)
        self.assertTrue(all(row['quantity'] == 3 for row in table['rows']))
        self.assertTrue(all(row['shared_sats'] == table['shared_sats'] for row in table['rows']))
        budget = pricing.quote_for_budget(*RATES, 3000000, quantity=4)
        self.assertEqual(budget['quantity'], 4)
        self.assertLessEqual(budget['total_toman'], 3000000)

    def test_invalid_quantity_is_rejected(self):
        for bad in (0, -1, 1.0, '1', True, None, 501, 10 ** 9):
            with self.subTest(quantity=bad):
                with self.assertRaises(ValueError):
                    pricing.quote_for_principal(*RATES, 100000, quantity=bad)

    def test_quantity_does_not_leak_sensitive_keys(self):
        row = pricing.quote_for_principal(*RATES, 100000, quantity=2)
        for key in ('mnemonic', 'private_key', 'seed', 'contact_value'):
            self.assertNotIn(key, row)
        self.assertEqual(json.loads(json.dumps(row, allow_nan=False)), row)


if __name__ == '__main__':
    unittest.main()
