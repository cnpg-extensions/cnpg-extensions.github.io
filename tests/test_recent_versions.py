import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import version_history as h

OLD = '1.0-202611100000-18-trixie'
NEW = '0.9-202611180000-18-trixie'  # A newer rebuild of an older version.
DIGEST = 'sha256:' + 'a' * 64
VERSIONS = 'https://github.com/orgs/org/packages/container/image/versions'
CANONICAL = 'https://github.com/org/source/pkgs/container/image/versions'


def page(tags, next_page=False, url=VERSIONS):
    html = ''.join(f'<div class="flex-column"><a href="/orgs/org/packages/container/image/123?tag={tag}">{tag}</a><clipboard-copy value="{DIGEST}"></clipboard-copy></div>' for tag in tags)
    if next_page:
        html += '<a class="next_page" href="/orgs/org/packages/container/image/versions?page=2">Next</a>'
    return Mock(text=html, url=url)


def cached():
    return {OLD: {'tag': OLD, 'reference': f'ghcr.io/org/image:{OLD}@{DIGEST}', 'imageURL': 'verified'}}


class RecentVersionsTests(unittest.TestCase):
    def test_overlap_stops_pagination_but_processes_rest_of_page(self):
        with patch.object(h.requests, 'Session') as factory:
            session = factory.return_value.__enter__.return_value
            session.get.side_effect = [page([OLD, NEW], True), page([OLD], True)]
            found = h.recent_builds('org/image', cached())
            self.assertEqual(set(found), {OLD, NEW})
            self.assertEqual(session.get.call_count, 1)

    def test_known_page_stops_without_following_next_link(self):
        with patch.object(h.requests, 'Session') as factory:
            session = factory.return_value.__enter__.return_value
            session.get.return_value = page([OLD], True)
            h.recent_builds('org/image', cached())
            self.assertEqual(session.get.call_count, 1)

    def test_invalid_html_fails_instead_of_claiming_freshness(self):
        with patch.object(h.requests, 'Session') as factory:
            factory.return_value.__enter__.return_value.get.return_value = Mock(text='<html>Login required</html>', url=VERSIONS)
            with self.assertRaisesRegex(ValueError, 'No timestamped'):
                h.recent_builds('org/image', cached())

    def test_new_build_uses_discovered_link_and_preserves_older_history(self):
        registry = Mock(repo='org/image')
        build = {'tag': NEW, 'reference': f'ghcr.io/org/image:{NEW}@{DIGEST}'}
        with patch.object(h, 'recent_builds', return_value={NEW: {'digest': DIGEST, 'imageURL': 'new-link'}}), patch.object(h, 'read_build', return_value=build) as read, patch.object(h, 'add_image_links') as links:
            result = h.refresh_recent_repository(registry, cached(), {})
            self.assertEqual(len(result), 2)
            self.assertEqual(build['imageURL'], 'new-link')
            read.assert_called_once_with(registry, NEW)
            links.assert_not_called()

    def test_changed_catalog_digest_is_refetched_even_beyond_overlap(self):
        registry = Mock(repo='org/image')
        build = {'tag': OLD, 'reference': f'ghcr.io/org/image:{OLD}@sha256:' + 'b' * 64}
        with patch.object(h, 'recent_builds', return_value={}), patch.object(h, 'read_build', return_value=build) as read, patch.object(h, 'add_image_links') as links:
            h.refresh_recent_repository(registry, cached(), {OLD: 'sha256:' + 'b' * 64})
            read.assert_called_once()
            links.assert_called_once_with([build])

    def test_full_refresh_bypasses_incremental_discovery(self):
        with patch.object(h, 'build_tags', return_value=[]), patch.object(h, 'recent_builds') as recent:
            self.assertEqual(h.refresh_repository(Mock(repo='org/image'), list(cached().values()), full_refresh=True, incremental=True), [])
            recent.assert_not_called()

    def test_reconciliation_timestamp_does_not_slide_on_incremental_runs(self):
        import json
        import tempfile
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        for age, expected in [(1, True), (8, False)]:
            with self.subTest(age=age), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'history.json'
                stamp = (now - timedelta(days=age)).isoformat()
                old = list(cached().values())
                old[0]['annotations'] = {}
                path.write_text(json.dumps({'example': {'fetchedAt': now.isoformat(),
                                                       'reconciledAt': stamp, 'builds': old}}))
                entry = {'name': 'example', 'variants': old}
                with patch.object(h, 'Registry'), patch.object(h, 'refresh_repository', return_value=old) as refresh, patch.object(h, 'validate'):
                    h.refresh_entry(entry, history_path=path)
                self.assertEqual(refresh.call_args.kwargs['incremental'], expected)
                saved = json.loads(path.read_text())['example']
                if expected:
                    self.assertEqual(saved['reconciledAt'], stamp)
                else:
                    self.assertGreater(saved['reconciledAt'], stamp)

    def test_changed_digest_does_not_count_as_cached_overlap(self):
        old = cached()
        old[OLD]['reference'] = f'ghcr.io/org/image:{OLD}@sha256:' + 'b' * 64
        with patch.object(h.requests, 'Session') as factory:
            session = factory.return_value.__enter__.return_value
            session.get.side_effect = [page([OLD], True), page([NEW])]
            self.assertEqual(set(h.recent_builds('org/image', old)), {OLD, NEW})
            self.assertEqual(session.get.call_count, 2)

    def test_foreign_pagination_link_rejected_before_request(self):
        response = page([NEW], True)
        response.text = response.text.replace('/orgs/org/packages/container/image/versions?page=2', 'https://example.com/versions')
        with patch.object(h.requests, 'Session') as factory:
            session = factory.return_value.__enter__.return_value
            session.get.return_value = response
            with self.assertRaisesRegex(ValueError, 'pagination'):
                h.recent_builds('org/image', cached())
            self.assertEqual(session.get.call_count, 1)

    def test_redirected_pagination_preserves_organization_build_links(self):
        first = page([NEW], True, CANONICAL)
        first.text = first.text.replace('/orgs/org/packages/container/image/versions?page=2', '?page=2')
        with patch.object(h.requests, 'Session') as factory:
            session = factory.return_value.__enter__.return_value
            session.get.side_effect = [first, page([OLD], url=CANONICAL + '?page=2')]
            found = h.recent_builds('org/image', cached())
            self.assertEqual(set(found), {NEW, OLD})
            self.assertTrue(found[NEW]['imageURL'].startswith(VERSIONS.removesuffix('/versions')))
            self.assertEqual(session.get.call_count, 2)
            self.assertEqual(session.get.call_args.args[0], CANONICAL + '?page=2')

    def test_unrelated_redirects_rejected(self):
        for url in ['https://example.com/versions', CANONICAL.replace('/org/', '/other/'),
                    CANONICAL.replace('/image/', '/other/'), 'https://github.com/orgs/org/packages',
                    CANONICAL.replace('https:', 'http:')]:
            with self.subTest(url=url), patch.object(h.requests, 'Session') as factory:
                session = factory.return_value.__enter__.return_value
                session.get.return_value = page([OLD], url=url)
                with self.assertRaisesRegex(ValueError, 'redirect'):
                    h.recent_builds('org/image', cached())

    def test_redirect_does_not_allow_unrelated_pagination(self):
        first = page([NEW], True, CANONICAL)
        first.text = first.text.replace('/orgs/org/packages/container/image/versions?page=2',
                                        '/org/other/pkgs/container/image/versions?page=2')
        with patch.object(h.requests, 'Session') as factory:
            session = factory.return_value.__enter__.return_value
            session.get.return_value = first
            with self.assertRaisesRegex(ValueError, 'pagination'):
                h.recent_builds('org/image', cached())
            self.assertEqual(session.get.call_count, 1)
