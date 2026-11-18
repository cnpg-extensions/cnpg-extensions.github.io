import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from osv_scan import findings, scan_osv

class OSVTests(unittest.TestCase):
    def test_ids_deduplicate_per_package_version_not_across_versions(self):
        def entry(version):
            return {'package': {'name': 'crate', 'version': version}, 'vulnerabilities': [{'id': 'RUSTSEC-1'}, {'id': 'RUSTSEC-1'}]}
        self.assertEqual(len(findings({'results': [{'packages': [entry('1'), entry('2')]}]})), 2)

    def test_findings_exit_code_is_success_and_failures_are_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sbom = root / 'static' / 'image.spdx.json'
            sbom.parent.mkdir()
            for code, output, expected in [(1, '{"results": []}', 'scanned'), (2, '{}', 'unavailable'), (0, 'invalid', 'unavailable'), (0, '{}', 'unavailable')]:
                with self.subTest(code=code, output=output), patch('osv_scan.subprocess.run', return_value=SimpleNamespace(returncode=code, stdout=output, stderr='error')) as run:
                    result = scan_osv(sbom, root, 'osv-scanner')
                    self.assertEqual(result['status'], expected)
                    self.assertEqual(run.call_args.args[0], ['osv-scanner', 'scan', 'source', '--offline', '-L', str(sbom), '--format', 'json'])

    def test_failed_refresh_prevents_scanning_stale_database(self):
        with patch('osv_scan.subprocess.run') as run:
            result=scan_osv(Path('unused'),Path('.'),'osv-scanner',{'error':'refresh failed'})
        self.assertEqual(result['status'],'unavailable')
        self.assertNotIn('findings',result)
        run.assert_not_called()

    def test_database_refresh_records_both_archives_and_rejects_bad_downloads(self):
        import io
        import zipfile
        from osv_scan import refresh_database
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('example.json','{}')
        from unittest.mock import Mock
        response=Mock(content=archive.getvalue(),headers={'Last-Modified':'today'})
        with tempfile.TemporaryDirectory() as directory:
            with patch('osv_scan.requests.get',return_value=response) as get:
                result=refresh_database(Path(directory))
            self.assertEqual(get.call_count,2)
            self.assertEqual(set(result['databases']),{'crates.io','Debian'})
            self.assertNotIn('error',result)
            saved=Path(directory)/'.cache/osv-local-db/osv-scalibr/crates.io/all.zip'
            previous=saved.read_bytes()
            response.content=b'invalid archive'
            with patch('osv_scan.requests.get',return_value=response):
                failed=refresh_database(Path(directory))
            self.assertIn('error',failed)
            self.assertEqual(saved.read_bytes(),previous)
