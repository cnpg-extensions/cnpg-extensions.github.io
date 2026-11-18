import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import version_history as history


class HistoryTests(unittest.TestCase):
    def test_pagination_excludes_aliases_and_attestations(self):
        first = Mock(links={'next': {'url': '/v2/org/image/tags/list?last=one'}})
        first.json.return_value = {'tags': ['0.41.0-202610100710-18-trixie', '0.41.0-18-trixie', 'sha256-abc.att']}
        second = Mock(links={})
        second.json.return_value = {'tags': ['0.42.0-202610111357-18-trixie']}
        registry = Mock(base='https://ghcr.io/v2/org/image/')
        registry.session.get.side_effect = [first, second]
        self.assertEqual(history.build_tags(registry), ['0.41.0-202610100710-18-trixie', '0.42.0-202610111357-18-trixie'])
        self.assertEqual(registry.session.get.call_count, 2)

    def test_pagination_rejects_foreign_host(self):
        response = Mock(links={'next': {'url': 'https://example.com/tags'}})
        response.json.return_value = {'tags': []}
        registry = Mock(base='https://ghcr.io/v2/org/image/')
        registry.session.get.return_value = response
        with self.assertRaises(ValueError):
            history.build_tags(registry)
        self.assertEqual(registry.session.get.call_count, 1)

    def test_manifest_digest_mismatch_is_rejected(self):
        response = Mock(content=b'changed', headers={'Docker-Content-Digest': 'sha256:' + '0' * 64})
        registry = Mock(base='https://ghcr.io/v2/org/image/')
        registry.session.get.return_value = response
        with self.assertRaises(ValueError):
            history.read_build(registry, '0.41.0-202610100710-18-trixie')

    def test_exact_link_requires_matching_image_digest(self):
        from unittest.mock import patch
        build = {'tag': '0.43.0-202611161804-18-trixie', 'reference': 'ghcr.io/org/image@sha256:abc', 'packageURL': 'https://github.com/orgs/org/packages/container/package/image'}
        response = Mock(text='<div class="flex-column"><a href="/orgs/org/packages/container/image/123?tag=0.43.0-202611161804-18-trixie">0.43.0-202611161804-18-trixie</a><clipboard-copy value="sha256:abc"></clipboard-copy></div>')
        with patch.object(history.requests, 'get', return_value=response):
            history.add_image_links([build])
        self.assertIn('/123?tag=', build['imageURL'])
        response.text = response.text.replace('sha256:abc', 'sha256:attestation')
        with patch.object(history.requests, 'get', return_value=response):
            with self.assertRaises(ValueError):
                history.add_image_links([dict(build)])

    def test_incremental_refresh_only_fetches_new_tags(self):
        from unittest.mock import patch
        registry = Mock(repo='org/image')
        old = {'tag': 'old', 'reference': 'ghcr.io/org/image:old@sha256:old', 'imageURL': 'verified'}
        new = {'tag': 'new', 'reference': 'ghcr.io/org/image:new@sha256:new'}
        with patch.object(history, 'build_tags', return_value=['old', 'new']), patch.object(history, 'read_build', return_value=new) as read, patch.object(history, 'add_image_links') as links:
            result = history.refresh_repository(registry, [old])
            read.assert_called_once_with(registry, 'new')
            links.assert_called_once_with([new])
            self.assertEqual(len(result), 2)

    def test_unchanged_history_needs_no_manifest_or_html_requests(self):
        from unittest.mock import patch
        registry = Mock(repo='org/image')
        old = {'tag': 'old', 'reference': 'ghcr.io/org/image:old@sha256:old', 'imageURL': 'verified'}
        with patch.object(history, 'build_tags', return_value=['old']), patch.object(history, 'read_build') as read, patch.object(history, 'add_image_links') as links:
            self.assertEqual(history.refresh_repository(registry, [old]), [old])
            read.assert_not_called()
            links.assert_not_called()

    def test_full_refresh_and_changed_catalog_digest_refetch(self):
        from unittest.mock import patch
        registry = Mock(repo='org/image')
        old = {'tag': 'old', 'reference': 'ghcr.io/org/image:old@sha256:old', 'imageURL': 'verified'}
        new = {'tag': 'old', 'reference': 'ghcr.io/org/image:old@sha256:new'}
        for kwargs in ({'full_refresh': True}, {'current_digests': {'old': 'sha256:new'}}):
            with self.subTest(kwargs=kwargs), patch.object(history, 'build_tags', return_value=['old']), patch.object(history, 'read_build', return_value=new) as read, patch.object(history, 'add_image_links') as links:
                history.refresh_repository(registry, [old], **kwargs)
                read.assert_called_once()
                links.assert_called_once_with([new])

    def test_removed_tags_do_not_survive_refresh(self):
        from unittest.mock import patch
        registry = Mock(repo='org/image')
        old = {'tag': 'old', 'reference': 'ghcr.io/org/image:old@sha256:old', 'imageURL': 'verified'}
        with patch.object(history, 'build_tags', return_value=[]):
            self.assertEqual(history.refresh_repository(registry, [old]), [])

    def test_all_command_refreshes_catalog_entries_in_order(self):
        import json
        import tempfile
        from unittest.mock import patch, call
        entries=[{'name':'one'},{'name':'two'}]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'data').mkdir()
            (root/'data/generated.json').write_text(json.dumps({'extensions':entries}))
            with patch.object(history,'ROOT',root), patch.object(sys,'argv',['preview-versions.py','--all','--full-refresh']), patch.object(history,'refresh_entry') as refresh, patch.object(history,'install_history'):
                history.main()
            self.assertEqual(refresh.call_args_list,[call(entries[0],True),call(entries[1],True)])

    def test_refresh_failure_preserves_persisted_history(self):
        import json
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'data').mkdir()
            path=root/'.cache/version-history/history.json'
            path.parent.mkdir(parents=True)
            original=json.dumps({'one':{'builds':[],'fetchedAt':'previous'}})
            path.write_text(original)
            entry={'name':'one','variants':[{'reference':'ghcr.io/org/image:tag@sha256:abc'}]}
            with patch.object(history,'ROOT',root), patch.object(history,'Registry'), patch.object(history,'refresh_repository',side_effect=RuntimeError('offline')):
                with self.assertRaises(RuntimeError):
                    history.refresh_entry(entry)
            self.assertEqual(path.read_text(),original)
