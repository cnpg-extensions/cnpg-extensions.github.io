import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import generate


class RegistryCacheTests(unittest.TestCase):
    def test_saved_asset_reused_unless_refresh_requested(self):
        data = b'{"schemaVersion":2}'
        digest = 'sha256:' + hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'oci').mkdir()
            saved = root/'oci'/digest.replace(':', '-')
            saved.write_bytes(data)
            registry = generate.Registry.__new__(generate.Registry)
            registry.base = 'https://ghcr.io/v2/org/image/'
            registry.session = Mock()
            registry.session.get.return_value.content = data
            with patch.object(generate, 'CACHE', root):
                registry.refresh = False
                self.assertEqual(registry.get(digest), json.loads(data))
                registry.session.get.assert_not_called()
                registry.refresh = True
                self.assertEqual(registry.get(digest), json.loads(data))
                registry.session.get.assert_called_once()
            self.assertEqual(saved.read_bytes(), data)
