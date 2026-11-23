import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
spec = importlib.util.spec_from_file_location('scorecards', Path(__file__).resolve().parents[1]/'scripts/scan-scorecards.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
import yaml
from scorecard_repositories import catalog_variants, project_links, repository_mapping


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
            extension = {'name': 'new-extension', 'image': {'reference': 'ghcr.io/cnpg-extensions/new'}}
            doc = {'metadata': {'labels': {'images.cnpg.io/os': 'trixie'}},
                   'spec': {'images': [{'extensions': [extension]}, {'extensions': [extension]}]}}
            Path(tmp, 'catalog-test.yaml').write_text(yaml.safe_dump(doc))
            self.assertEqual(catalog_variants(tmp), {'new-extension': {('cnpg-extensions', 'trixie')}})

    def test_diagnostics_redact_token(self):
        with patch.dict(m.os.environ, {'GITHUB_AUTH_TOKEN': 'secret-value'}):
            self.assertEqual(m.diagnostic('error secret-value'), 'error [REDACTED]')

    def test_invalid_json_has_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'not json', 'error')):
            result = m.scan('https://github.com/example/repo', 'scorecard', Path(tmp), 10)
            self.assertEqual(result['status'], 'unavailable')
            self.assertIn('not json', result['diagnostic'])

    def test_scan_only_when_public_report_is_unavailable(self):
        args = ('https://github.com/example/project', 'scorecard', Path('.'), 10)
        report = {'url': 'https://example.org/report', 'date': '2026-11-23'}
        with patch.object(m, 'public_report', side_effect=[report, None]) as lookup, patch.object(m, 'scan') as scan:
            self.assertEqual(m.scan_if_needed(*args)['status'], 'public')
            scan.assert_not_called()
            self.assertEqual(m.scan_if_needed(*args), scan.return_value)
            scan.assert_called_once_with(*args)
            self.assertEqual(lookup.call_count, 2)

    def test_partial_report_survives_nonzero_exit(self):
        report = {'date': '2026-11-18', 'repo': {'commit': 'abc'},
                  'checks': [{'name': 'Branch-Protection', 'score': -1},
                             {'name': 'Maintained', 'score': 10}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, json.dumps(report), 'check failed')):
            result = m.scan('https://github.com/example/repo', 'scorecard', Path(tmp), 10)
            self.assertEqual(result['status'], 'available')
            self.assertEqual(result['exitCode'], 1)
            self.assertEqual(result['inconclusiveChecks'], 1)

    @patch('scorecard_repositories.upstream_links', return_value=[])
    def test_package_homepage_discovery(self, lookup):
        links = project_links('// renovate: suite=trixie-pgdg depName=postgresql-18-documentdb',
                                {'postgresql-18-documentdb': {'Version': '1', 'Homepage': 'https://github.com/documentdb/documentdb'}}, 'trixie')
        self.assertEqual(repository_mapping(links)['repository'], 'https://github.com/documentdb/documentdb')

    def test_renovate_precedence_and_ambiguous_fallback(self):
        recipe = '// renovate: datasource=github-tags depName=example/upstream'
        links = project_links(recipe, {}, 'trixie')
        fallback = {'repository': 'https://github.com/example/reviewed'}
        self.assertEqual(repository_mapping(links, fallback)['repository'], 'https://github.com/example/upstream')
        links.extend(project_links('// renovate: datasource=gitlab-releases depName=other/project', {}, 'trixie'))
        self.assertEqual(repository_mapping(links, fallback), fallback)
        self.assertIsNone(repository_mapping(links))

    def test_git_tags_and_salsa_source_discovery(self):
        links = project_links('# renovate: datasource=git-tags depName=https://github.com/neondatabase/pg_session_jwt.git', {}, 'trixie')
        self.assertEqual(repository_mapping(links)['repository'], 'https://github.com/neondatabase/pg_session_jwt')
        source = {'label': 'Upstream release repository', 'url': 'https://salsa.debian.org/team/source', 'evidence': 'watch'}
        self.assertEqual(repository_mapping([source])['repository'], source['url'])
        self.assertIn('salsa.debian.org', m.scan_skip_reason(repository_mapping([source])))

    def test_archive_only_watch_does_not_select_a_metadata_mirror(self):
        mirror = 'https://github.com/example/mirror'
        links = [{'label': 'Debian release watch', 'url': 'https://example.org/tarball', 'evidence': 'watch'},
                 {'label': 'Debian upstream repository', 'url': mirror, 'evidence': 'metadata'}]
        self.assertIsNone(repository_mapping(links))
        canonical = {'repository': 'https://git.example.org/source', 'mirrors': [mirror]}
        self.assertEqual(repository_mapping(links[1:], canonical), canonical)
        self.assertIn('git.example.org', m.scan_skip_reason(canonical))
