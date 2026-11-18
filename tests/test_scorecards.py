import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('scorecards', Path(__file__).resolve().parents[1]/'scripts/scan-scorecards.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ScorecardTests(unittest.TestCase):
    def test_preserves_scores_and_details(self):
        report = {'date': '2026-11-18', 'repo': {'commit': 'abc'},
                  'checks': [{'name': 'Maintained', 'score': 0, 'details': ['quiet']},
                             {'name': 'Branch-Protection', 'score': -1}]}
        raw = json.dumps(report)
        with tempfile.TemporaryDirectory() as tmp, patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, raw, '')):
            result = m.scan('https://github.com/example/repo', 'scorecard', Path(tmp), 10)
            self.assertEqual(result['status'], 'available')
            self.assertEqual(result['inconclusiveChecks'], 1)
            self.assertEqual((Path(tmp)/result['report']).read_text(), raw)

    def test_failure_does_not_become_zero(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'private diagnostics')):
            result = m.scan('https://github.com/example/repo', 'scorecard', Path(tmp), 10)
            self.assertEqual(result['status'], 'unavailable')
            self.assertNotIn('score', result)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_unsupported_host_is_not_executed(self):
        with patch.object(m.subprocess, 'run') as run:
            self.assertEqual(m.scan('https://salsa.debian.org/a/b', 'scorecard', Path('.'), 10)['status'], 'unsupported')
            run.assert_not_called()

    def test_catalog_deduplicates_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'catalog-test.yaml').write_text('spec:\n  images:\n  - extensions: [{name: pgvector}, {name: http}]\n  - extensions: [{name: pgvector}]\n')
            self.assertEqual(m.catalog_names(tmp), {'pgvector', 'http'})

    def test_diagnostics_redact_token(self):
        with patch.dict(m.os.environ, {'GITHUB_AUTH_TOKEN': 'secret-value'}):
            self.assertEqual(m.diagnostic('error secret-value'), 'error [REDACTED]')

    def test_invalid_json_has_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'not json', 'error')):
            result = m.scan('https://github.com/example/repo', 'scorecard', Path(tmp), 10)
            self.assertEqual(result['status'], 'unavailable')
            self.assertIn('not json', result['diagnostic'])

    def test_partial_report_survives_nonzero_exit(self):
        report = {'date': '2026-11-18', 'repo': {'commit': 'abc'},
                  'checks': [{'name': 'Branch-Protection', 'score': -1},
                             {'name': 'Maintained', 'score': 10}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, json.dumps(report), 'check failed')):
            result = m.scan('https://github.com/example/repo', 'scorecard', Path(tmp), 10)
            self.assertEqual(result['status'], 'available')
            self.assertEqual(result['exitCode'], 1)
            self.assertEqual(result['inconclusiveChecks'], 1)

    def test_only_explicit_list_is_scanned(self):
        self.assertEqual(m.scan_targets({'http', 'pgvector', 'new-extension'}, ['http'], set()), ['http'])
        with self.assertRaisesRegex(ValueError, 'not in local scan list'):
            m.scan_targets({'http', 'pgvector'}, ['http'], {'pgvector'})

    def test_local_subset_and_removed_catalog_entry(self):
        self.assertEqual(m.scan_targets({'http', 'hypopg'}, ['http', 'hypopg'], {'http'}), ['http'])
        with self.assertRaisesRegex(ValueError, 'absent from catalog'):
            m.scan_targets({'http'}, ['http', 'hypopg'], set())

    def test_reviewed_list(self):
        names = json.loads((m.ROOT/'data/scorecard-local-scans.json').read_text())['extensions']
        mappings = json.loads((m.ROOT/'data/scorecard-repositories.json').read_text())
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(set(names) <= set(mappings))
