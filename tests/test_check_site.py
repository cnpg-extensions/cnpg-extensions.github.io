import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'check-site.py'


class CheckSiteTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.write('data/generated.json', json.dumps({
            'count': 1,
            'extensions': [{'name': 'sample', 'variants': []}],
        }))
        self.write('public/extensions/sample/index.html', '<main></main>')
        for view in ('overview', 'documentation', 'dependencies', 'licenses', 'versions'):
            self.write(
                f'public/extensions/sample/{view}/index.html',
                f'<section class="tab detail-view" id="{view}"></section>'
                '<section class="detail-view" id="other" hidden></section>',
            )

    def write(self, path, text):
        file = self.directory / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding='utf-8')

    def check_site(self):
        return subprocess.run(
            [sys.executable, SCRIPT, 'public'], cwd=self.directory, capture_output=True, text=True,
        )

    def test_local_links_decode_paths_and_fragments(self):
        self.write('public/icons/sample icon.svg', '<svg/>')
        self.write('public/guide/index.html', '<div id="setup&amp;usage"></div>')
        self.write('public/index.html', '''
            <main id="start here">
              <a href="#start%20here">Local anchor</a>
              <a href="guide/?mode=quick#setup%26usage">Relative page</a>
              <a href="/guide/index.html#setup%26usage">Root-relative page</a>
              <a href="/cnpg-extensions-website/guide/#setup%26usage">Deployed page</a>
              <img href="" src="icons/sample%20icon.svg"/>
              <script>const markup = '<a href="missing.html">';</script>
              <a href="https://example.com/missing.html">External page</a>
            </main>
        ''')
        result = self.check_site()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('and 4 local links.', result.stdout)

    def test_reports_missing_targets_and_anchors(self):
        self.write('public/index.html', '''
            <a href="#missing">Local anchor</a>
            <a href="extensions/sample/overview/#missing">Other page anchor</a>
            <img src="missing.svg"/>
        ''')
        result = self.check_site()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.splitlines(), [
            'public/index.html: missing anchor #missing',
            'public/index.html: missing anchor extensions/sample/overview/#missing',
            'public/index.html: missing missing.svg',
        ])

    def test_rejects_extra_visible_detail_views(self):
        page = 'public/extensions/sample/overview/index.html'
        self.write(page, '''
            <section class="detail-view" id="overview"></section>
            <section class="tab detail-view" id="documentation"></section>
        ''')
        result = self.check_site()
        self.assertEqual(result.returncode, 1)
        self.assertIn(f'AssertionError: {page}', result.stderr)
