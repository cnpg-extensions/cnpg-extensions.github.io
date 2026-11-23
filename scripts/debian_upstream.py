"""Read upstream declarations and release watches from PGDG source packaging."""
from email.parser import Parser
from functools import lru_cache
import gzip
import hashlib
from io import BytesIO
import re
import tarfile
from urllib.parse import unquote, urlsplit

import requests
import yaml

ARCHIVE = 'https://apt.postgresql.org/pub/repos/apt'
SLUG = r'[A-Za-z0-9_.-]+'
FILES = {'debian/upstream/metadata', 'debian/watch'}


@lru_cache(maxsize=None)
def source_archives(distro):
    try:
        response = requests.get(f'{ARCHIVE}/dists/{distro}-pgdg/main/source/Sources.gz', timeout=60)
        response.raise_for_status()
        paragraphs = gzip.decompress(response.content).decode().split('\n\n')
    except (requests.RequestException, OSError, EOFError) as exc:
        print(f'PGDG source index unavailable for {distro}: {exc}', flush=True)
        return {}
    archives = {}
    for paragraph in paragraphs:
        record = Parser().parsestr(paragraph)
        for line in record.get('Checksums-Sha256', '').splitlines():
            parts = line.split()
            if len(parts) == 3 and re.fullmatch(r'[^/]+\.debian\.tar\.(?:xz|gz|bz2)', parts[2]):
                digest, _, filename = parts
                archives[record['Package'], record['Version']] = (
                    f"{ARCHIVE}/{record['Directory']}/{filename}", digest)
    return archives


def watch_repositories(text):
    # Read literal upstream locations only. Watch options and patterns are never executed.
    for stanza in re.split(r'\n\s*\n', text.replace('\\\n', '')):
        lines = [line.strip() for line in stanza.splitlines() if not line.lstrip().startswith('#')]
        fields = {}
        for line in lines:
            key, separator, value = line.partition(':')
            if separator:
                fields[key.lower()] = value.strip()
        template = fields.get('template', '').lower()
        owner, project = fields.get('owner', ''), fields.get('project', '')
        if template in ('github', 'gitlab') and re.fullmatch(SLUG, owner) and re.fullmatch(SLUG, project):
            yield f'https://{template}.com/{owner}/{project}'
        for line in lines:
            # v5 Source or v4's URL after optional opts="...".
            line = re.sub(r'^(?:opts|options)=(?:"[^"]*"|\S+)\s+', '', line)
            if template in ('github', 'gitlab') and line.lower().startswith('dist:'):
                line = line.partition(':')[2].strip()
            match = re.match(r'^(?:Source:\s*)?(https?://\S+)', line, re.I)
            if not match:
                continue
            url = urlsplit(match[1])
            path = unquote(url.path).strip('/')
            if url.netloc == 'api.github.com' and path.startswith('repos/'):
                path = path.removeprefix('repos/')
                host = 'github.com'
            else:
                host = url.netloc
            if host == 'github.com':
                path = '/'.join(path.split('/')[:2])
            elif host in ('gitlab.com', 'salsa.debian.org'):
                if url.path.startswith('/api/v4/projects/'):
                    encoded_project = url.path.split('/api/v4/projects/', 1)[1].split('/', 1)[0]
                    path = unquote(encoded_project)
                else:
                    path = path.split('/-/')[0]
                    path = re.sub(r'/(?:tags|releases|archive)(?:/.*)?$', '', path)
            else:
                continue
            path = path.removesuffix('.git')
            if re.fullmatch(SLUG + r'(?:/' + SLUG + r')+', path):
                yield f'https://{host}/{path}'


@lru_cache(maxsize=None)
def packaging_links(url, digest):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != digest:
        raise ValueError(f'PGDG source archive checksum mismatch: {url}')
    files = {}
    with tarfile.open(fileobj=BytesIO(response.content)) as archive:
        for member in archive:
            name = member.name.removeprefix('./')
            if name in FILES and member.isfile() and member.size <= 256 * 1024:
                files[name] = archive.extractfile(member).read().decode(errors='replace')
    if 'debian/watch' in files:
        repositories = sorted(set(watch_repositories(files['debian/watch'])))
        if repositories:
            return [{'label': 'Upstream release repository', 'url': repo,
                     'evidence': f'{url} · debian/watch'} for repo in repositories]
        return [{'label': 'Debian release watch', 'url': url, 'evidence': 'debian/watch'}]
    links = []
    metadata = yaml.safe_load(files.get('debian/upstream/metadata', ''))
    if isinstance(metadata, dict):
        for key in ('Repository', 'Repository-Browse'):
            value = metadata.get(key)
            if isinstance(value, str) and value.startswith('git://'):
                value = 'https://' + value.removeprefix('git://')
            if isinstance(value, str) and value.startswith(('https://', 'http://')):
                links.append({'label': 'Debian upstream repository', 'url': value,
                              'evidence': f'{url} · debian/upstream/metadata ({key})'})
    return links


@lru_cache(maxsize=None)
def upstream_links(distro, source, version):
    try:
        archive = source_archives(distro).get((source, version))
        return packaging_links(*archive) if archive else []
    except (requests.RequestException, OSError, EOFError, ValueError, tarfile.TarError, yaml.YAMLError) as exc:
        print(f'Debian upstream metadata unavailable for {source} {version}: {exc}', flush=True)
        return []
