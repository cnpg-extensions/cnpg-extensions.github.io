import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('scorecard_data', Path(__file__).resolve().parents[1] / 'scripts/scorecard_data.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

REPO = 'https://github.com/example/project'
REPORT = {'date': '2026-11-18', 'repo': {'name': 'github.com/example/project', 'commit': 'abc'},
          'score': 4.2, 'checks': [{'name': 'Packaging', 'score': -1, 'reason': 'Not detected',
                                   'documentation': {'short': 'Checks packaging', 'url': 'https://example.com/check'}}]}


class ScorecardDataTests(unittest.TestCase):
    def test_api_wins_and_keeps_unknown_check_without_total(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(m.requests, 'get', return_value=Mock(json=lambda: REPORT)):
            result = m.resolve(REPO, {REPO: (REPORT, json.dumps(REPORT))}, Path(directory))
            self.assertEqual(result['source'], 'OpenSSF API')
            self.assertEqual(result['checks'][0]['score'], -1)
            self.assertNotIn('score', result)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_api_failure_downloads_unmodified_fallback(self):
        raw = json.dumps(REPORT, indent=2)
        with tempfile.TemporaryDirectory() as directory, patch.object(m.requests, 'get', side_effect=m.requests.ConnectionError):
            result = m.resolve(REPO, {REPO: (REPORT, raw)}, Path(directory))
            self.assertEqual(result['source'], 'Cached scan')
            self.assertEqual((Path(directory) / Path(result['url']).name).read_text(), raw)
            self.assertEqual(result['date'], REPORT['date'])

    def test_wrong_repository_report_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(m.requests, 'get', return_value=Mock(json=lambda: REPORT)):
            self.assertEqual(m.resolve('https://github.com/other/project', {}, Path(directory))['status'], 'unavailable')

    def test_artifact_rejects_subset_and_wrong_producer(self):
        with tempfile.TemporaryDirectory() as directory:
            index = {'schemaVersion': 1, 'scope': 'subset', 'producer': m.PRODUCER, 'runId': '123'}
            path = Path(directory) / 'index.json'
            path.write_text(json.dumps(index))
            self.assertEqual(m.read_artifact(Path(directory), '123'), {})
            index.update(scope='local-list', producer='other/repo')
            path.write_text(json.dumps(index))
            self.assertEqual(m.read_artifact(Path(directory), '123'), {})

    def test_artifact_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            index = {'schemaVersion': 1, 'scope': 'local-list', 'producer': m.PRODUCER, 'runId': '123',
                     'extensions': {'example': {'status': 'available', 'repository': REPO, 'report': '../secret.json'}}}
            (Path(directory) / 'index.json').write_text(json.dumps(index))
            self.assertEqual(m.read_artifact(Path(directory), '123'), {})

    def test_checks_order_by_risk_then_name_without_exposing_risk(self):
        names = ['License', 'SAST', 'Webhooks', 'Maintained', 'CI-Tests',
                 'Code-Review', 'Dangerous-Workflow', 'New-Check']
        checks = [{'name': name, 'score': i % 11} for i, name in enumerate(names)]
        report = {**REPORT, 'checks': checks}
        result = m.present(report, REPO, 'OpenSSF API', 'https://example.com')
        self.assertEqual([c['name'] for c in result['checks']],
                         ['Dangerous-Workflow', 'Webhooks', 'Code-Review', 'Maintained',
                          'SAST', 'CI-Tests', 'License', 'New-Check'])
        self.assertEqual(report['checks'], checks)
        self.assertTrue(all('risk' not in c for c in result['checks']))
