import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, call

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import version_history as history


class HistoryGenerationTests(unittest.TestCase):
    def test_selective_refresh_only_bypasses_selected_extension(self):
        entries = [{'name': 'one'}, {'name': 'two'}]
        with patch.object(history, 'refresh_entry') as refresh, patch.object(history, 'install_history'):
            history.generate_history(entries, refresh_extension='two')
        self.assertEqual(refresh.call_args_list, [call(entries[0], full_refresh=False), call(entries[1], full_refresh=True)])

    def test_failed_generation_preserves_hugo_data_and_successful_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / 'data/version_history.json'
            destination.parent.mkdir()
            destination.write_text('previous good data')
            cache = root / '.cache/version-history/history.json'
            def retrieve(entry, **kwargs):
                if entry['name'] == 'two':
                    raise RuntimeError('offline')
                history.atomic_json(cache, {'one': {'fetchedAt': '2026-11-18T00:00:00Z', 'builds': []}})
            with patch.object(history, 'ROOT', root), patch.object(history, 'refresh_entry', side_effect=retrieve):
                with self.assertRaisesRegex(RuntimeError, 'offline'):
                    history.generate_history([{'name': 'one'}, {'name': 'two'}])
            self.assertEqual(destination.read_text(), 'previous good data')
            self.assertIn('one', json.loads(cache.read_text()))

    def test_install_validates_all_entries_before_replacing_hugo_data(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'cache.json'
            destination = Path(directory) / 'hugo.json'
            destination.write_text('previous good data')
            history.atomic_json(cache, {'one': {'fetchedAt': '2026-11-18T00:00:00Z', 'builds': []}})
            with self.assertRaises(KeyError):
                history.install_history([{'name': 'one'}, {'name': 'two'}], cache, destination)
            self.assertEqual(destination.read_text(), 'previous good data')
            history.install_history([{'name': 'one'}], cache, destination)
            self.assertEqual(json.loads(destination.read_text()), json.loads(cache.read_text()))
