from hashlib import sha256
from io import BytesIO
from pathlib import Path
import sys
import tarfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from debian_upstream import packaging_links, watch_repositories
from scorecard_repositories import project_links
from scorecard_repositories import repository_mapping


class DebianUpstreamTests(unittest.TestCase):
    def test_watch_reads_literal_targets_only(self):
        watch = '''version=4
# https://github.com/unrelated/comment
opts="mode=git" https://github.com/example/database.git refs/tags/v(.*)

Version: 5
Template: Github
Owner: documentdb
Project: documentdb

Source: https://gitlab.com/group/subgroup/project/-/tags
Matching-Pattern: https://github.com/unrelated/pattern

Source: https://gitlab.com/api/v4/projects/another%2Fdatabase/repository/tags
'''
        self.assertEqual(list(watch_repositories(watch)), [
            'https://github.com/example/database', 'https://github.com/documentdb/documentdb',
            'https://gitlab.com/group/subgroup/project', 'https://gitlab.com/another/database'])

    def test_watch_salsa_legacy_tags_and_github_template_dist(self):
        self.assertEqual(list(watch_repositories('opts=searchmode=plain https://salsa.debian.org/team/sub/repo/tags v(.*)')),
                         ['https://salsa.debian.org/team/sub/repo'])
        self.assertEqual(list(watch_repositories('Version: 5\nTemplate: Github\nDist: https://github.com/example/project')),
                         ['https://github.com/example/project'])

    def test_release_watch_wins_and_preserves_homepage(self):
        blob = BytesIO()
        with tarfile.open(fileobj=blob, mode='w:gz') as tar:
            for filename, body in [('debian/upstream/metadata', b'Repository: https://github.com/up/extension.git'),
                                   ('debian/watch', b'https://github.com/other/release/tags v(.*)')]:
                header = tarfile.TarInfo(filename)
                header.size = len(body)
                tar.addfile(header, BytesIO(body))
        archive = blob.getvalue()
        with patch('debian_upstream.requests.get', return_value=Mock(content=archive)):
            links = packaging_links('https://example.org/source', sha256(archive).hexdigest())
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                packaging_links('https://example.org/source', 'wrong')
        record = {'Source': 'extension (1.0)', 'Version': '1.0+b1', 'Homepage': 'https://example.org'}
        with patch('scorecard_repositories.upstream_links', return_value=links) as lookup:
            result = project_links('// renovate: suite=trixie-pgdg depName=extension-pg18',
                                   {'extension-pg18': record}, 'trixie')
        lookup.assert_called_once_with('trixie', 'extension', '1.0')
        self.assertIn('https://example.org', [link['url'] for link in result])
        self.assertEqual(repository_mapping(result)['repository'], 'https://github.com/other/release')
