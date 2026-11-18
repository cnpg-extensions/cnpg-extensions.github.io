import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('hugo'), 'Hugo is required for template integration tests')
class TimestampTests(unittest.TestCase):
    def test_utc_fallback_and_date_only_precision(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            (site / 'layouts/_partials').mkdir(parents=True)
            (site / 'hugo.toml').write_text('baseURL = "https://example.org/"\n')
            shutil.copy(root / 'layouts/_partials/timestamp.html', site / 'layouts/_partials')
            (site / 'layouts/index.html').write_text(
                '{{ partial "timestamp.html" "2026-11-10T05:30:00+05:30" }}'
                '{{ partial "timestamp.html" "2026-11-10" }}')
            result = subprocess.run(['hugo', '--source', str(site)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            html = (site / 'public/index.html').read_text()
            self.assertIn('datetime="2026-11-10T00:00:00Z"', html)
            self.assertIn('10 Nov 2026, 00:00 UTC', html)
            self.assertEqual(html.count('data-local-time'), 1)
            self.assertIn('>10 Nov 2026</time>', html)
            self.assertNotIn('(date only;', html)
