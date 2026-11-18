"""Read /licenses from a digest-pinned image's final filesystem, without running it."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile


def read_notices(archive):
    notices = []
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('Unsafe path in exported image')
        if not path.parts or path.parts[0] != 'licenses' or member.isdir():
            continue
        if not (member.isfile() or member.issym() or member.islnk()):
            continue
        # tarfile resolves archive links without following paths on the host.
        stream = archive.extractfile(member)
        if stream is None:
            raise ValueError(f'Cannot read notice: {path}')
        data = stream.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError(f'Notice exceeds 8 MiB: {path}')
        text = data.decode('utf-8')
        notices.append({'path': '/' + str(path), 'text': text,
                        'sha256': hashlib.sha256(data).hexdigest()})
    return sorted(notices, key=lambda item: item['path'])


def container_notices(reference, architecture, digest, cache, refresh=False):
    cache = Path(cache) / 'image-notices-v1'
    cached = cache / (digest.replace(':', '-') + '.json')
    if refresh:
        cached.unlink(missing_ok=True)
    if cached.exists():
        return json.loads(cached.read_text())
    # The platform manifest belongs to the catalog index resolved by the generator.
    image = reference.split('@')[0].split(':')[0] + '@' + digest
    container = None
    try:
        subprocess.run(['docker', 'pull', '--platform', 'linux/' + architecture, image],
                       check=True, capture_output=True, text=True, timeout=600)
        container = subprocess.check_output(
            ['docker', 'create', '--platform', 'linux/' + architecture, image, '/unused'],
            text=True, stderr=subprocess.PIPE, timeout=60).strip()
        with tempfile.TemporaryDirectory(prefix='cnpg-notices-') as directory:
            exported = Path(directory) / 'image.tar'
            subprocess.run(['docker', 'export', '--output', str(exported), container],
                           check=True, capture_output=True, text=True, timeout=300)
            with tarfile.open(exported) as archive:
                files = read_notices(archive)
        result = {'status': 'available', 'files': files}
        cache.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(result))
        return result
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError) as error:
        # Failed retrieval is different from a successfully inspected, empty directory.
        return {'status': 'unavailable', 'files': [], 'reason': str(error)}
    finally:
        if container:
            subprocess.run(['docker', 'rm', container], capture_output=True, timeout=60)
