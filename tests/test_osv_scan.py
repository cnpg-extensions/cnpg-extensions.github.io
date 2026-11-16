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
                    self.assertEqual(run.call_args.args[0], ['osv-scanner', 'scan', 'source', '-L', str(sbom), '--format', 'json'])
