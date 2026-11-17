"""Search-discovery contract: the public pages must be findable for the
Persian paper-wallet queries a real buyer types.

Written before the change so it fails on the pre-SEO tree.

Deliberately NOT asserted: a meta keywords tag. Google has ignored it since
2009 and stuffing one is a spam signal, so what this pins is the surface that
actually ranks — title, description, headings, body text, structured data and
crawlability.
"""
from __future__ import annotations

import importlib.util
import json
import re
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

SITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SITE))

# The head terms the owner asked to be findable for. Persian buyers type these.
PHONEY_TERMS = ("کیف پول کاغذی", "بیت‌کوین کاغذی", "پیپروالت", "paper wallet", "paperwallet")
INDEXABLE = ("/", "/guide", "/security", "/terms", "/download", "/costs", "/aml")


class Head(HTMLParser):
    def __init__(self):
        super().__init__()
        self.description = None
        self.title = None
        self.ld = []
        self._in_title = False
        self._in_ld = False
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name") == "description":
            self.description = attrs.get("content")
        if tag == "title":
            self._in_title = True
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self._in_ld = True
            self._buf = ""

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._in_ld:
            self._in_ld = False
            try:
                parsed = json.loads(self._buf)
            except json.JSONDecodeError:
                self.ld.append(None)
                return
            # A page may publish one object or a list of blocks.
            self.ld.extend(parsed if isinstance(parsed, list) else [parsed])

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data
        if self._in_ld:
            self._buf += data


def load_app():
    spec = importlib.util.spec_from_file_location("seo_app", SITE / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_app(module):
    limiter = Mock()
    limiter.admit.return_value = 0
    service = Mock()
    service.token.return_value = "SYNTHETIC"
    return module.create_app({"TESTING": True, "WALLET_LOOKUP": lambda s: None,
                              "ADDRESS_LOOKUP": lambda a: None,
                              "LOOKUP_LIMITER": limiter, "CONTACT_SERVICE": service})


class SearchDiscovery(unittest.TestCase):
    def setUp(self):
        self.client = make_app(load_app()).test_client()

    def test_indexable_pages_name_the_paper_wallet_search_terms(self):
        for route in INDEXABLE:
            with self.subTest(route=route):
                text = self.client.get(route).text
                self.assertTrue(any(term in text for term in PHONEY_TERMS),
                                f"{route} carries none of the paper-wallet search terms")

    def test_home_title_and_description_carry_the_head_term(self):
        parser = Head()
        parser.feed(self.client.get("/").text)
        combined = f"{parser.title} {parser.description}"
        self.assertIn("کیف پول کاغذی", combined)
        self.assertLessEqual(len(parser.title.strip()), 70)

    def test_meta_descriptions_stay_unique_and_within_a_snippet(self):
        seen = {}
        for route in INDEXABLE:
            with self.subTest(route=route):
                parser = Head()
                parser.feed(self.client.get(route).text)
                description = (parser.description or "").strip()
                self.assertTrue(description)
                self.assertLessEqual(len(description), 200)
                self.assertNotIn(description, seen)
                seen[description] = route

    def test_pages_carry_valid_structured_data_for_a_product_and_a_site(self):
        parser = Head()
        parser.feed(self.client.get("/").text)
        blocks = [b for b in parser.ld if isinstance(b, dict)]
        self.assertTrue(blocks, "home must publish JSON-LD")
        types = {b.get("@type") for b in blocks}
        self.assertIn("WebSite", types)
        self.assertTrue(types & {"Product", "WebPage"}, types)
        for block in blocks:
            self.assertIn("@context", block)
            self.assertEqual(block["@context"], "https://schema.org")

    def test_indexable_pages_are_crawlable_and_operational_ones_are_not(self):
        for route in INDEXABLE:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertNotIn("X-Robots-Tag", response.headers, route)
        for route in ("/lookup", "/contact", "/api/wallets/x"):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertIn("X-Robots-Tag", response.headers, route)

    def test_sitemap_and_robots_point_at_the_new_origin(self):
        sitemap = self.client.get("/sitemap.xml").text
        robots = self.client.get("/robots.txt").text
        self.assertIn("https://bitposta.com/", sitemap)
        self.assertIn("Sitemap: https://bitposta.com/sitemap.xml", robots)

    def test_no_meta_keywords_tag_is_shipped(self):
        # Google ignores it and a stuffed one is a spam signal; assert its absence
        # rather than let a later "SEO" pass reintroduce it.
        for route in INDEXABLE:
            with self.subTest(route=route):
                self.assertNotIn('name="keywords"', self.client.get(route).text)


if __name__ == "__main__":
    unittest.main()
