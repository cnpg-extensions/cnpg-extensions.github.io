"""Render historical records with absent PG metadata through the real Hugo template."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('hugo'), 'Hugo is required for template integration tests')
class VersionsTemplateTests(unittest.TestCase):
    def test_unknown_pg_sorts_after_known_majors(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            (site / 'layouts/_partials').mkdir(parents=True)
            (site / 'data').mkdir()
            (site / 'hugo.toml').write_text('baseURL = "https://example.org/"\n')
            shutil.copy(root / 'layouts/_partials/extension-versions.html', site / 'layouts/_partials')
            (site / 'layouts/index.html').write_text('{{ partial "extension-versions.html" hugo.Data.entry }}')
            builds = []
            for pg in ['Unknown', '17', '18']:
                builds.append({'version': '1.0', 'pg': pg, 'distro': 'trixie',
                               'reference': 'ghcr.io/org/image@sha256:' + 'a' * 64,
                               'annotations': {'org.opencontainers.image.created': '2026-11-10T00:00:00Z'}})
            for version, timestamp in [('before-cutoff', '2026-11-09T23:59:59Z'),
                                       ('after-cutoff', '2026-11-10T00:00:01Z')]:
                builds.append({'version': version, 'pg': '18', 'distro': 'trixie',
                               'reference': 'ghcr.io/org/image@sha256:' + 'b' * 64,
                               'annotations': {'org.opencontainers.image.created': timestamp}})
            (site / 'data/entry.json').write_text(json.dumps({'name': 'example', 'variants': [builds[1]]}))
            (site / 'data/version_history.json').write_text(json.dumps({
                'example': {'fetchedAt': '2026-11-10T00:00:00Z', 'builds': builds}}))
            result = subprocess.run(['hugo', '--source', str(site)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            html = (site / 'public/index.html').read_text()
            self.assertLess(html.index('PG 18'), html.index('PG 17'))
            self.assertLess(html.index('PG 17'), html.index('PG Unknown'))
            self.assertNotIn('before-cutoff', html)
            self.assertIn('after-cutoff', html)
            self.assertIn('1.0', html)  # The exact cutoff remains visible.
