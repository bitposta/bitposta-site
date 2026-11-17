"""Rebrand contract: the public site speaks bitposta.com and only two owned domains.

Written before the rebrand so every assertion below fails on the pre-rebrand tree.
Backward compatibility is deliberately NOT required by the owner: the legacy
domains are removed from the allowlists, not kept beside the new one.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

SITE = Path(__file__).resolve().parents[1]
ROOT = SITE.parent
sys.path.insert(0, str(SITE))

BRAND = 'bitposta.com'
BRAND_FA = 'بیت‌پستا'
PRINTABLE_EMAIL = '09113458375@bitposta.com'
REPO = 'https://github.com/bitposta/bitposta-site'
LEGACY = ('btc4.fun', 'go.btc4.fun', 'bitcoin4.fun', 'b.tc4fun.ir', 'btc4-fun')
PUBLIC_ROUTES = ('/', '/guide', '/security', '/terms', '/t', '/costs', '/contact', '/lookup')


def load_app():
    spec = importlib.util.spec_from_file_location('rebrand_app', SITE / 'app.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_app(module):
    service = Mock()
    service.token.return_value = 'SYNTHETIC_FORM_TOKEN'
    limiter = Mock()
    limiter.admit.return_value = 0
    return module.create_app({'TESTING': True, 'WALLET_LOOKUP': lambda serial: None,
                              'ADDRESS_LOOKUP': lambda address: None,
                              'CONTACT_SERVICE': service, 'LOOKUP_LIMITER': limiter})


class RebrandContract(unittest.TestCase):
    def setUp(self):
        self.module = load_app()
        self.app = make_app(self.module)
        self.client = self.app.test_client()

    def test_public_routes_speak_the_new_brand_and_never_a_legacy_domain(self):
        for route in PUBLIC_ROUTES:
            with self.subTest(route=route):
                response = self.client.get(route, base_url='https://' + BRAND)
                self.assertEqual(response.status_code, 200)
                text = response.text
                self.assertIn(BRAND, text)
                self.assertIn(BRAND_FA, text)
                self.assertIn('mailto:' + PRINTABLE_EMAIL, text)
                for legacy in LEGACY:
                    self.assertNotIn(legacy, text)

    def test_canonical_sitemap_and_robots_use_the_new_origin(self):
        for route, suffix in (('/', '/'), ('/guide', '/guide'), ('/security', '/security'),
                              ('/terms', '/terms'), ('/t', '/terms'), ('/download', '/download'),
                              ('/costs', '/costs'), ('/aml', '/aml')):
            with self.subTest(route=route):
                self.assertIn('href="https://' + BRAND + suffix + '"',
                              self.client.get(route).text)
        sitemap = self.client.get('/sitemap.xml').text
        robots = self.client.get('/robots.txt').text
        self.assertIn('https://' + BRAND + '/guide</loc>', sitemap)
        self.assertIn('Sitemap: https://' + BRAND + '/sitemap.xml', robots)
        for legacy in LEGACY:
            self.assertNotIn(legacy, sitemap)
            self.assertNotIn(legacy, robots)

    def test_security_page_lists_only_the_two_owned_domains(self):
        text = self.client.get('/security').text
        self.assertIn('btc.saeb.id.ir', text)
        self.assertIn(BRAND, text)
        self.assertIn('.id.ir', text)
        self.assertIn('احراز هویت', text)
        for legacy in LEGACY:
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, text)

    def test_image_and_url_host_allowlists_accept_only_the_new_hosts(self):
        self.assertIn(BRAND, self.module.PUBLIC_URL_HOSTS)
        for legacy in LEGACY:
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, self.module.PUBLIC_URL_HOSTS)
        csp = self.client.get('/').headers['Content-Security-Policy']
        self.assertIn('https://' + BRAND, csp)
        for legacy in LEGACY:
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, csp)

    def test_browser_payload_contract_uses_the_new_origin(self):
        site_js = (SITE / 'static/site.js').read_text()
        self.assertIn('https://' + BRAND + '/s/', site_js)
        self.assertIn(BRAND, site_js)
        for legacy in LEGACY:
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, site_js)

    def test_contact_page_links_the_new_social_accounts(self):
        text = self.client.get('/contact').text
        self.assertIn('https://www.instagram.com/bitposta.ir/', text)
        self.assertIn('https://t.me/bitposta', text)
        self.assertIn('https://x.com/bitposta', text)
        for legacy in LEGACY:
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, text)
        self.assertNotIn('b_tc4fun_ir', text)
        self.assertNotIn('btc4_fun', text)

    def test_current_public_docs_link_the_new_repositories_and_email(self):
        readme = (ROOT / 'README.md').read_text()
        self.assertIn('https://' + BRAND, readme)
        self.assertIn('https://github.com/bitposta/', readme)
        self.assertIn('https://github.com/bitposta/bitposta-checker', readme)
        self.assertNotIn('btc4-fun', readme)
        self.assertIn(PRINTABLE_EMAIL, (ROOT / 'SECURITY.md').read_text())
        self.assertIn(PRINTABLE_EMAIL, (ROOT / 'NOTICE').read_text())


if __name__ == '__main__':
    unittest.main()
