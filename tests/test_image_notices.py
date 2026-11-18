import io
import json
import tempfile
from unittest.mock import patch
import sys
import tarfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from image_notices import read_notices, container_notices

class NoticeTests(unittest.TestCase):
    def archive(self, entries):
        data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w') as archive:
            for name, body in entries:
                item=tarfile.TarInfo(name)
                if isinstance(body,tuple):
                    item.type=tarfile.SYMTYPE;item.linkname=body[0]
                    archive.addfile(item)
                else:
                    item.size=len(body);archive.addfile(item,io.BytesIO(body))
        data.seek(0)
        return tarfile.open(fileobj=data)

    def test_only_shipped_license_directory_and_exact_text(self):
        with self.archive([('licenses/pkg/copyright',b'Terms\n'),('usr/lib/code.so',b'ignore')]) as archive:
            notices=read_notices(archive)
        self.assertEqual([n['path'] for n in notices],['/licenses/pkg/copyright'])
        self.assertEqual(notices[0]['text'],'Terms\n')
        self.assertEqual(len(notices[0]['sha256']),64)

    def test_shared_notice_link(self):
        with self.archive([('licenses/shared',b'Shared terms'),('licenses/pkg/copyright',('../shared',))]) as archive:
            notices=read_notices(archive)
        self.assertEqual(len(notices),2)
        self.assertEqual(notices[0]['text'],notices[1]['text'])

    def test_empty_is_not_a_failure(self):
        with self.archive([('usr/lib/code.so',b'ignore')]) as archive:
            self.assertEqual(read_notices(archive),[])

    def test_broken_link_is_not_silently_omitted(self):
        with self.archive([('licenses/missing',('absent',))]) as archive:
            with self.assertRaises((KeyError,ValueError)):
                read_notices(archive)

    def test_cached_digest_skips_all_docker_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            cache=Path(directory)/'image-notices-v1'
            cache.mkdir()
            expected={'status':'available','files':[]}
            (cache/'sha256-abc.json').write_text(json.dumps(expected))
            with patch('image_notices.subprocess.run') as run, patch('image_notices.subprocess.check_output') as output:
                self.assertEqual(container_notices('ghcr.io/org/image@sha256:index','amd64','sha256:abc',directory),expected)
                run.assert_not_called()
                output.assert_not_called()

    def test_failed_extraction_is_not_cached_and_is_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('image_notices.subprocess.run',side_effect=OSError('offline')) as run:
                for _ in range(2):
                    result=container_notices('ghcr.io/org/image@sha256:index','amd64','sha256:abc',directory)
                    self.assertEqual(result['status'],'unavailable')
                self.assertEqual(run.call_count,2)
            self.assertFalse((Path(directory)/'image-notices-v1'/'sha256-abc.json').exists())

    def test_refresh_bypasses_saved_notices(self):
        with tempfile.TemporaryDirectory() as directory:
            cache=Path(directory)/'image-notices-v1'
            cache.mkdir()
            (cache/'sha256-abc.json').write_text(json.dumps({'status':'available','files':[]}))
            with patch('image_notices.subprocess.run',side_effect=OSError('offline')) as run:
                result=container_notices('ghcr.io/org/image@sha256:index','amd64','sha256:abc',directory,refresh=True)
                self.assertEqual(result['status'],'unavailable')
                run.assert_called_once()
            self.assertFalse((cache/'sha256-abc.json').exists())
