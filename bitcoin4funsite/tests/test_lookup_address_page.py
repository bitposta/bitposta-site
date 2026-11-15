"""Public address lookup on the page: synthetic records, no real services.

The page route reuses the /api/addresses contract, so these tests also pin that
the API response shape the Android app consumes did not change.
"""
import importlib.util
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ADDRESS = 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu'
OTHER_ADDRESS = 'bc1qzmtrqsfuaf6l6kkcsseumq26ukaphfj9skkug6'
SERIAL = 'TEST-DO-NOT-FUND-0587k45300'
BALANCE = {'address': ADDRESS, 'confirmed_sats': 500, 'pending_delta_sats': -50,
           'source': 'https://blockstream.info/api',
           'fetched_at': '1970-01-01T00:16:40+00:00'}
EXPLORERS = ('https://mempool.space/address/', 'https://blockstream.info/address/',
             'https://www.blockchain.com/explorer/addresses/btc/')


def load_app():
    spec = importlib.util.spec_from_file_location('lookup_address_page_app', ROOT / 'app.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LookupAddressPage(unittest.TestCase):
    def fixture(self, record=None, balance=None):
        limiter = Mock()
        limiter.admit.return_value = 0
        lookup = Mock(return_value=record)
        service = Mock()
        service.balance.return_value = dict(BALANCE) if balance is None else balance
        app = load_app().create_app({'TESTING': True, 'LOOKUP_LIMITER': limiter,
                                     'ADDRESS_LOOKUP': lookup, 'SERIAL_BALANCE': service})
        return app.test_client(), lookup, service, limiter

    def test_registered_address_renders_the_serial_card_without_any_balance_read(self):
        client, lookup, service, limiter = self.fixture({'serial': SERIAL, 'address': ADDRESS})
        response = client.get('/lookup?address=' + ADDRESS)
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-initial-state="found"', response.text)
        self.assertIn('data-initial-serial="' + SERIAL + '"', response.text)
        self.assertIn('data-initial-address="' + ADDRESS + '"', response.text)
        self.assertIn('/api/wallets/' + SERIAL + '/qr.svg', response.text)
        # No automatic balance fetch: the service is untouched until the user asks.
        service.assert_not_called()
        lookup.assert_called_once_with(ADDRESS)
        limiter.admit.assert_called_once_with('127.0.0.1', 'address_' + ADDRESS, qr=False)

    def test_explicit_balance_puts_the_numbers_before_the_address(self):
        client, _, service, _ = self.fixture({'serial': SERIAL, 'address': ADDRESS})
        response = client.get('/lookup?address=' + ADDRESS + '&balance=1')
        self.assertEqual(response.status_code, 200)
        service.balance.assert_called_once_with(ADDRESS)
        self.assertIn('data-initial-balance=', response.text)
        noscript = response.text.split('<noscript>')[1]
        for value in ('500', '-50', '0.00000500', '-0.00000050',
                      'https://blockstream.info/api', '1970-01-01T00:16:40+00:00'):
            self.assertIn(value, noscript)
        # Balance first, then the address, then the serial, then the QR.
        self.assertLess(noscript.index('موجودی تأییدشده'), noscript.index(ADDRESS))
        self.assertLess(noscript.index(ADDRESS), noscript.index(SERIAL))
        self.assertLess(noscript.index(SERIAL), noscript.index('qr-block'))

    def test_unregistered_address_shows_three_explorer_links_and_no_balance_read(self):
        client, lookup, service, _ = self.fixture(None)
        response = client.get('/lookup?address=' + ADDRESS)
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-initial-state="address_not_found"', response.text)
        self.assertIn('این آدرس در فهرست ما ثبت نشده است', response.text)
        service.assert_not_called()
        lookup.assert_called_once_with(ADDRESS)
        noscript = response.text.split('<noscript>')[1]
        for prefix in EXPLORERS:
            self.assertIn('href="' + prefix + ADDRESS + '"', noscript)
        self.assertNotIn('موجودی تأییدشده', noscript)
        self.assertNotIn('data-initial-balance="', response.text)
        # The three links are opt-in anchors, never a prefetched resource.
        self.assertNotRegex(response.text, r'<(?:img|iframe)[^>]+src="https?://')

    def test_unregistered_address_with_balance_flag_still_reads_no_balance(self):
        client, _, service, _ = self.fixture(None)
        response = client.get('/lookup?address=' + ADDRESS + '&balance=1')
        self.assertEqual(response.status_code, 200)
        service.assert_not_called()
        self.assertIn('data-initial-state="address_not_found"', response.text)

    def test_balance_failure_keeps_the_card_and_never_claims_zero(self):
        client, _, service, _ = self.fixture({'serial': SERIAL, 'address': ADDRESS})
        service.balance.side_effect = TimeoutError('synthetic upstream timeout')
        response = client.get('/lookup?address=' + ADDRESS + '&balance=1')
        self.assertEqual(response.status_code, 503)
        self.assertIn('data-initial-state="found"', response.text)
        self.assertIn('data-balance-error="unavailable"', response.text)
        self.assertIn(ADDRESS, response.text)
        self.assertNotIn('0.00000000', response.text)

    def test_serial_wins_when_both_inputs_are_submitted(self):
        client, lookup, _, _ = self.fixture({'serial': SERIAL, 'address': ADDRESS})
        client.application.config['WALLET_LOOKUP'] = Mock(
            return_value={'serial': SERIAL, 'address': ADDRESS})
        response = client.get('/lookup?serial=' + SERIAL + '&address=' + ADDRESS)
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-initial-serial="' + SERIAL + '"', response.text)
        lookup.assert_not_called()

    def test_invalid_and_unknown_parameters_are_rejected_before_any_lookup(self):
        client, lookup, service, limiter = self.fixture({'serial': SERIAL, 'address': ADDRESS})
        for query in ('?address=' + ADDRESS.upper(), '?address=' + ADDRESS[:-1] + 'q',
                      '?address=' + OTHER_ADDRESS + '&view=1',
                      '?address=' + ADDRESS + '&address=' + ADDRESS,
                      '?balance=1', '?address=' + ADDRESS + '&balance=0'):
            with self.subTest(query=query[:80]):
                response = client.get('/lookup' + query)
                self.assertEqual(response.status_code, 400)
        lookup.assert_not_called()
        service.assert_not_called()
        limiter.admit.assert_not_called()

    def test_address_page_shares_the_serial_quota(self):
        from lookup_limit import LookupLimiter
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            now = [1000.0]
            limiter = LookupLimiter(Path(directory) / 'quota.sqlite3',
                                    'SYNTHETIC_PAGE_QUOTA_SECRET_' * 2, clock=lambda: now[0])
            lookup = Mock(return_value={'serial': SERIAL, 'address': ADDRESS})
            app = load_app().create_app({'TESTING': True, 'LOOKUP_LIMITER': limiter,
                                         'ADDRESS_LOOKUP': lookup,
                                         'WALLET_LOOKUP': lookup})
            client = app.test_client()
            for path in ('/lookup?address=' + ADDRESS, '/lookup?serial=' + SERIAL,
                         '/lookup?address=' + ADDRESS, '/lookup?serial=' + SERIAL,
                         '/lookup?address=' + ADDRESS):
                self.assertEqual(client.get(path).status_code, 200)
            now[0] = 1017
            denied = client.get('/lookup?address=' + ADDRESS)
            self.assertEqual(denied.status_code, 429)
            self.assertEqual(denied.headers['Retry-After'], '43')
            self.assertIn('۴۳ ثانیه', denied.text)
            self.assertEqual(lookup.call_count, 5)

    def test_api_contract_is_unchanged_for_the_android_consumer(self):
        client, _, service, _ = self.fixture({'serial': SERIAL, 'address': ADDRESS})
        plain = client.get('/api/addresses/' + ADDRESS)
        self.assertEqual(plain.status_code, 200)
        self.assertEqual(plain.json, {'address': ADDRESS, 'serial': SERIAL,
                                      'lookup_url': 'https://btc4.fun/s/' + SERIAL})
        service.assert_not_called()
        with_balance = client.get('/api/addresses/' + ADDRESS + '?balance=1')
        self.assertEqual(with_balance.status_code, 200)
        self.assertEqual(set(with_balance.json), {'address', 'serial', 'lookup_url', 'balance'})
        self.assertEqual(with_balance.json['balance'], BALANCE)
        missing = self.fixture(None)[0].get('/api/addresses/' + ADDRESS)
        self.assertEqual((missing.status_code, missing.json), (404, {'error': 'not_found'}))


class LookupMobileLayout(unittest.TestCase):
    """Static contract for the mobile-first rules the browser check measures."""

    def setUp(self):
        self.css = (ROOT / 'static' / 'site.css').read_text()

    def rule(self, selector):
        found = re.findall(re.escape(selector) + r'\{([^}]*)\}', self.css)
        self.assertTrue(found, 'Missing CSS rule: ' + selector)
        return ';'.join(found)

    def test_narrow_screens_collapse_to_one_column(self):
        mobile = re.search(r'@media\(max-width:700px\)\{([^@]*\.lookup-layout[^@]*)\}', self.css)
        self.assertIsNotNone(mobile, 'The lookup layout needs a <=700px rule')
        self.assertIn('grid-template-columns:minmax(0,1fr)', mobile.group(1))

    def test_touch_targets_are_at_least_44px(self):
        for selector in ('#serial,#address', '.lookup-controls .button',
                         '.lookup-controls .secondary-button', '.secondary-button',
                         '.explorer-link'):
            with self.subTest(selector=selector):
                heights = [int(value) for value in
                           re.findall(r'min-height:(\d+)px', self.rule(selector))]
                self.assertTrue(heights, 'No min-height for ' + selector)
                self.assertGreaterEqual(max(heights), 44)

    def test_balance_numbers_wrap_and_stay_readable_without_zoom(self):
        rule = self.rule('.balance-value')
        self.assertIn('overflow-wrap:anywhere', rule)
        self.assertIn('tabular-nums', rule)
        size = float(re.search(r'font:([\d.]+)rem', rule).group(1))
        self.assertGreaterEqual(size, 1.2)
        self.assertIn('overflow-wrap:anywhere', self.rule('.public-address'))

    def test_balance_panel_is_the_first_block_of_the_result_card(self):
        source = (ROOT / 'static' / 'site.js').read_text()
        nodes = re.search(r'const nodes = \[([^\]]*)\]', source).group(1)
        order = [part.strip() for part in nodes.split(',')]
        self.assertEqual(order[0], 'heading')
        self.assertEqual(order[1], 'balanceSlot')
        self.assertLess(order.index('addressLabel'), order.index('serialLabel'))
        self.assertLess(order.index('serialLabel'), order.index('figure'))


if __name__ == '__main__':
    unittest.main()
