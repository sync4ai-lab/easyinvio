"""Public help links, routing and customer documentation boundaries."""
import unittest
from html.parser import HTMLParser
from urllib.parse import urlsplit
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.help_center import router, GUIDES, COMPONENTS


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.ids = set()

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if 'id' in attributes:
            self.ids.add(attributes['id'])
        if tag == 'a' and 'href' in attributes:
            self.hrefs.append(attributes['href'])


class HelpCentreTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_public_guides_and_fragments_have_working_targets(self):
        pages = ['/help', '/help/contact'] + ['/help/' + slug for slug in GUIDES]
        for path in pages:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn('text/html', response.headers['content-type'])
            parser = Links()
            parser.feed(response.text)
            for href in parser.hrefs:
                self.assertNotEqual(href, '#', path)
                target = urlsplit(href)
                if not target.scheme and (target.path.startswith('/help') or not target.path):
                    destination = self.client.get(target.path or path)
                    self.assertEqual(destination.status_code, 200, href)
                    if target.fragment:
                        destination_parser = Links()
                        destination_parser.feed(destination.text)
                        self.assertIn(target.fragment, destination_parser.ids, href)

    def test_search_catalogue_and_feature_guides_are_truthful(self):
        index = self.client.get('/help/search-index.json').json()['guides']
        self.assertEqual(len(index), len(GUIDES))
        self.assertEqual(sum(not guide['prepared'] for guide in index), 1)
        for guide in index:
            response = self.client.get(guide['url'])
            if not guide['prepared']:
                self.assertIn('Guide being prepared', response.text)
        self.assertIn('does not automatically convert', self.client.get('/help/prices-and-currencies').text)
        self.assertIn('does not automatically refund', self.client.get('/help/booking-payments').text)
        self.assertIn('no guaranteed three-minute', self.client.get('/help/connect-shopify').text)

    def test_unknown_routes_do_not_expose_files_or_return_fake_guides(self):
        for path in ['/help/missing-guide', '/help/assets/.env', '/help/assets/help_center.py', '/help/features/unknown']:
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertIn('Browse the Help Centre', self.client.get('/help/missing-guide').text)
        for asset in ['support.css', 'support.js']:
            response = self.client.get('/help/assets/' + asset)
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response.headers['cache-control'])

    def test_markdown_sources_render_and_download_without_duplicate_titles(self):
        from pathlib import Path
        for slug, guide in GUIDES.items():
            if not guide.source_file:
                continue
            response = self.client.get('/help/' + slug)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text.count('<h1>'), 1)
            self.assertIn('In this guide', response.text)
            self.assertIn('Download this guide as Markdown', response.text)
            download = self.client.get('/help/source/' + slug)
            self.assertEqual(download.status_code, 200)
            self.assertIn('text/markdown', download.headers['content-type'])
            self.assertIn(guide.source_file, download.headers['content-disposition'])
            expected = (Path(__file__).resolve().parents[1] / guide.source_file).read_text(encoding='utf-8')
            self.assertEqual(download.text, expected)
        self.assertEqual(self.client.get('/help/source/account-access').status_code, 404)
        self.assertEqual(self.client.get('/help/source/unknown').status_code, 404)

    def test_feature_guides_do_not_claim_unimplemented_services(self):
        pickups = self.client.get('/help/features/carrier-pickups').text
        self.assertIn('does not offer dashboard courier pickup scheduling', pickups)
        pricing = self.client.get('/help/features/pricing').text
        self.assertIn('Automatic highest-profit carrier selection is not implemented', pricing)
        tracking = self.client.get('/help/features/labels-and-tracking').text
        self.assertIn('public holidays are not adjusted', tracking)
        returns = self.client.get('/help/features/returns').text
        self.assertIn('generic Amazon return update is not implemented', returns)
        self.assertIn('does not automatically request CN22/CN23', returns)

    def test_component_has_no_external_runtime_dependency_or_empty_links(self):
        html = (COMPONENTS / 'SupportHub.html').read_text(encoding='utf-8')
        self.assertIn('id="supportSearch"', html)
        self.assertNotIn('href="#"', html)
        self.assertNotIn('cdn.', html)
        self.assertIn('support@easyinvio.com', self.client.get('/help/contact').text)
        self.assertNotIn('method="post"', self.client.get('/help/contact').text)


if __name__ == '__main__':
    unittest.main()
