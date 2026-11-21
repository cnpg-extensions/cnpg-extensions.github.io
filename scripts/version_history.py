#!/usr/bin/env python3
"""Retrieve and reuse timestamp-tagged GHCR assets for website generation."""
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
from tempfile import NamedTemporaryFile
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlsplit
from generate import ROOT, Registry, check_digest, image_package_url

BUILD_TAG = re.compile(r'^.+-\d{12}-\d+-(?:bookworm|trixie)$')
EXTENSION_NAME = re.compile(r'[a-z0-9][a-z0-9_-]*')
HISTORY_WORKERS = 4


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = NamedTemporaryFile(mode='w', dir=path.parent, delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            stream.write(json.dumps(value))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class HistoryCache:
    def __init__(self, history_path=None):
        default_path = ROOT / '.cache/version-history/history.json'
        self.path = Path(history_path) if history_path else default_path
        self.per_extension = self.path.resolve() == default_path.resolve()
        if self.per_extension:
            self.path = default_path
        self.aggregate = None

    def entry_path(self, name):
        if not EXTENSION_NAME.fullmatch(name):
            raise ValueError('Invalid extension name')
        return self.path.parent / 'entries' / f'{name}.json'

    def load(self, name):
        if self.per_extension:
            path = self.entry_path(name)
            if path.exists():
                return json.loads(path.read_text())
        if self.aggregate is None:
            self.aggregate = json.loads(self.path.read_text()) if self.path.exists() else {}
        return self.aggregate.get(name, {})

    def save(self, name, record):
        if self.per_extension:
            atomic_json(self.entry_path(name), record)
        else:
            self.aggregate[name] = record
            atomic_json(self.path, self.aggregate)


def validate(histories):
    if not isinstance(histories, dict) or not histories:
        raise ValueError('Empty or invalid history data')
    for name, entry in histories.items():
        if not EXTENSION_NAME.fullmatch(name):
            raise ValueError('Invalid extension name')
        datetime.fromisoformat(entry['fetchedAt'])
        if not isinstance(entry['builds'], list):
            raise ValueError('Invalid build list')
        for build in entry['builds']:
            if not isinstance(build['version'], str) or not build['version']:
                raise ValueError('Missing image version')
            if not re.fullmatch(r'ghcr\.io/[a-z0-9._/:-]+@sha256:[0-9a-f]{64}', build['reference']):
                raise ValueError('Invalid image reference')
            if not isinstance(build['annotations'], dict) or not isinstance(build['platforms'], list):
                raise ValueError('Invalid image metadata')
            if not re.fullmatch(r'https://github\.com/orgs/[\w.-]+/packages/container/[^?]+/[0-9]+\?tag=[^\s]+', build['imageURL']):
                raise ValueError('Missing verified exact-image link')


def build_tags(registry):
    url = registry.base + 'tags/list?n=1000'
    tags = set()
    visited = set()
    while url:
        if url in visited or urlsplit(url).netloc != 'ghcr.io' or not urlsplit(url).path.startswith(urlsplit(registry.base).path):
            raise ValueError('Unexpected registry pagination URL')
        visited.add(url)
        response = registry.session.get(url, timeout=60)
        response.raise_for_status()
        tags.update(tag for tag in response.json().get('tags', []) if BUILD_TAG.fullmatch(tag))
        next_url = response.links.get('next', {}).get('url')
        url = urljoin(url, next_url) if next_url else None
    return sorted(tags)


def read_build(registry, tag):
    response = registry.session.get(registry.base + 'manifests/' + tag, timeout=60)
    response.raise_for_status()
    digest = response.headers.get('Docker-Content-Digest') or 'sha256:' + hashlib.sha256(response.content).hexdigest()
    check_digest(response.content, digest)
    index = response.json()
    annotations = index.get('annotations', {})
    # Version and dates come from published metadata, never inferred from tag names.
    version = annotations.get('org.opencontainers.image.version')
    if not version:
        raise ValueError(f'{tag}: missing published version metadata')
    reference = f'ghcr.io/{registry.repo}:{tag}@{digest}'
    return {'version': version, 'tag': tag, 'reference': reference,
            'annotations': annotations, 'packageURL': image_package_url(reference),
            'distro': annotations.get('io.cloudnativepg.image.base.os', 'Unknown'),
            'pg': annotations.get('io.cloudnativepg.image.base.pgmajor', 'Unknown'),
            'platforms': [m['platform'] for m in index.get('manifests', [])
                          if m.get('platform', {}).get('os') == 'linux']}


def add_image_links(builds):
    remaining = {b['tag']: b for b in builds}
    packages = {b['packageURL'] for b in builds}
    for package in packages:
        url = package.replace('/package/', '/') + '/versions?filters%5Bversion_type%5D=tagged'
        visited = set()
        while url and url not in visited:
            if urlsplit(url).netloc != 'github.com':
                raise ValueError('Unexpected package pagination host')
            visited.add(url)
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            for anchor in soup.select('a[href]'):
                tag = anchor.get_text(strip=True)
                build = remaining.get(tag)
                if not build or build['packageURL'] != package:
                    continue
                href = anchor['href']
                if not re.search(r'/[0-9]+\?tag=', href):
                    continue
                digest = build['reference'].split('@')[1]
                row = anchor.find_parent('div', class_='flex-column')
                if row and row.find('clipboard-copy', attrs={'value': digest}):
                    build['imageURL'] = urljoin('https://github.com', href)
                    del remaining[tag]
            if not any(b['packageURL'] == package for b in remaining.values()):
                break
            next_link = soup.select_one('a.next_page')
            url = urljoin(url, next_link['href']) if next_link else None
    if remaining:
        raise ValueError(f'Could not verify exact GitHub image links for {len(remaining)} builds')


def recent_builds(repository, cached):
    """Discover newest package versions, processing a whole page until cache overlap.

    This is a website-ordering optimization, not an OCI ordering guarantee.
    A periodic registry reconciliation repairs older changes and deletions.
    """
    package = image_package_url('ghcr.io/' + repository + ':unused')
    prefix = urlsplit(package.replace('/package/', '/') + '/versions').path
    owner, package_name = prefix.removeprefix('/orgs/').split('/packages/container/', 1)
    canonical_pattern = re.compile(
        '/' + re.escape(owner) + r'/[^/]+/pkgs/container/' + re.escape(package_name))
    pagination_path = prefix
    url = 'https://github.com' + prefix + '?filters%5Bversion_type%5D=tagged'
    found = {}
    visited = set()
    with requests.Session() as session:
        session.mount('https://', HTTPAdapter(max_retries=Retry(
            total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])))
        while url:
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.path != pagination_path or url in visited:
                raise ValueError('Unexpected package pagination URL')
            visited.add(url)
            response = session.get(url, timeout=60)
            response.raise_for_status()
            target = urlsplit(response.url)
            # GitHub redirects organization package pages to their linked repo.
            # Pin pagination to that verified path, keeping build links separate.
            if (target.scheme != 'https' or target.netloc != 'github.com'
                    or (target.path != pagination_path and not (
                        len(visited) == 1 and canonical_pattern.fullmatch(target.path)))):
                raise ValueError('Unexpected package redirect URL')
            pagination_path = target.path
            soup = BeautifulSoup(response.text, 'html.parser')
            page = {}
            for anchor in soup.select('a[href]'):
                tag = anchor.get_text(strip=True)
                if not BUILD_TAG.fullmatch(tag):
                    continue
                link = urljoin('https://github.com', anchor['href'])
                target = urlsplit(link)
                if target.netloc != 'github.com' or not re.fullmatch(
                        re.escape(prefix.removesuffix('/versions')) + r'/[0-9]+', target.path):
                    continue
                row = anchor.find_parent('div', class_='flex-column')
                digest = row.find('clipboard-copy') if row else None
                digest = digest.get('value', '') if digest else ''
                if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
                    raise ValueError('Package build is missing its digest')
                page[tag] = {'digest': digest, 'imageURL': link}
            found.update(page)
            if any(tag in cached and cached[tag].get('imageURL')
                            and cached[tag]['reference'].split('@')[1] == item['digest']
                            for tag, item in page.items()):
                break
            next_link = soup.select_one('a.next_page[href]')
            url = urljoin(response.url, next_link['href']) if next_link else None
        if not found:
            raise ValueError('No timestamped builds found on package pages')
    print(f'{repository}: checked {len(visited)} package pages', flush=True)
    return found


def read_builds(registry, tags, workers):
    if workers == 1 or len(tags) < 2:
        return [read_build(registry, tag) for tag in tags]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda tag: read_build(registry, tag), tags))


def refresh_recent_repository(registry, cached, current_digests, manifest_workers=HISTORY_WORKERS):
    discovered = recent_builds(registry.repo, cached)
    results = dict(cached)
    pending = set(discovered) | set(current_digests)
    missing = [tag for tag in sorted(pending)
               if tag not in cached or not cached[tag].get('imageURL')
               or cached[tag]['reference'].split('@')[1] != current_digests.get(
                   tag, discovered.get(tag, {}).get('digest'))]
    fetched = read_builds(registry, missing, manifest_workers)
    unresolved = []
    for build in fetched:
        item = discovered.get(build['tag'])
        if item and item['digest'] == build['reference'].split('@')[1]:
            build['imageURL'] = item['imageURL']
        else:
            unresolved.append(build)
        results[build['tag']] = build
    if unresolved:
        add_image_links(unresolved)
    print(f'{registry.repo}: reused {len(results) - len(fetched)}, fetched {len(fetched)}; incremental', flush=True)
    return list(results.values())


def refresh_repository(registry, previous, current_digests=None, full_refresh=False,
                       incremental=False, manifest_workers=HISTORY_WORKERS):
    current_digests = current_digests or {}
    cached = {b['tag']: b for b in previous
              if b['reference'].split('@')[0].rsplit(':', 1)[0] == 'ghcr.io/' + registry.repo}
    if incremental and cached and not full_refresh:
        return refresh_recent_repository(registry, cached, current_digests, manifest_workers)
    tags = build_tags(registry)
    reused = []
    missing = []
    for tag in tags:
        build = cached.get(tag)
        expected = current_digests.get(tag)
        if (not full_refresh and build and
                (not expected or build['reference'].split('@')[1] == expected)):
            reused.append(dict(build))
        else:
            missing.append(tag)
    fetched = read_builds(registry, missing, manifest_workers)
    builds = reused + fetched
    # Only unresolved/new images require GitHub HTML pagination.
    unresolved = [b for b in builds if not b.get('imageURL')]
    if unresolved:
        add_image_links(unresolved)
    print(f'{registry.repo}: reused {len(reused)}, fetched {len(fetched)}, resolved {len(unresolved)} links')
    return builds


def fetch_entry(entry, saved, full_refresh=False, manifest_workers=HISTORY_WORKERS):
    repositories = {v['reference'].split('@')[0].split(':')[0] for v in entry['variants']}
    previous = saved.get('builds', [])
    now = datetime.now(timezone.utc)
    reconciled = saved.get('reconciledAt') or saved.get('fetchedAt')
    incremental = bool(previous and reconciled and not full_refresh
                       and now - datetime.fromisoformat(reconciled) < timedelta(days=7))
    builds = []
    for repository in sorted(repositories):
        registry = Registry(repository + '@sha256:unused')
        current = {v['reference'].split('@')[0].rsplit(':', 1)[1]: v['reference'].split('@')[1]
                   for v in entry['variants'] if v['reference'].startswith(repository + ':')}
        with registry.session:
            builds.extend(refresh_repository(registry, previous, current, full_refresh,
                                             incremental=incremental, manifest_workers=manifest_workers))
    # Mutable aliases and attestation tags are excluded; deduplicate image digests.
    builds = list({b['reference'].split('@')[1]: b for b in builds}.values())
    builds.sort(key=lambda b: b['annotations'].get('org.opencontainers.image.created', ''), reverse=True)
    record = {'fetchedAt': now.isoformat(),
              'reconciledAt': reconciled if incremental else now.isoformat(), 'builds': builds}
    validate({entry['name']: record})
    print(f"{entry['name']}: {len(builds)} images", flush=True)
    return record


def refresh_entry(entry, full_refresh=False, history_path=None):
    cache = HistoryCache(history_path)
    name = entry['name']
    record = fetch_entry(entry, cache.load(name), full_refresh=full_refresh)
    cache.save(name, record)


def install_history(entries, records, destination):
    complete = {entry['name']: records[entry['name']] for entry in entries}
    validate(complete)
    atomic_json(destination, complete)


def generate_history(entries, refresh_extension=None, *, full_refresh=False, history_path=None):
    cache = HistoryCache(history_path)
    saved = {entry['name']: cache.load(entry['name']) for entry in entries}
    records = {}
    failure = None
    # Each completed extension is saved immediately. Hugo data changes only once
    # all required retrievals succeed; a failure stops the website build.
    with ThreadPoolExecutor(max_workers=HISTORY_WORKERS) as pool:
        pending = {
            pool.submit(fetch_entry, entry, saved[entry['name']],
                        full_refresh=full_refresh or entry['name'] == refresh_extension,
                        manifest_workers=1): entry['name']
            for entry in entries
        }
        for future in as_completed(pending):
            if future.cancelled():
                continue
            name = pending[future]
            try:
                record = future.result()
                cache.save(name, record)
                records[name] = record
            except Exception as error:
                if failure is None:
                    error.add_note(f'Refreshing version history for {name}')
                    failure = error
                    for queued in pending:
                        queued.cancel()
    if failure is not None:
        raise failure
    install_history(entries, records, ROOT / 'data/version_history.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('extension', nargs='?')
    parser.add_argument('--all', action='store_true', help='Refresh every catalog extension')
    parser.add_argument('--full-refresh', action='store_true', help='Refetch all historical manifests and exact image links')
    parser.add_argument('--catalog', type=Path, default=ROOT / 'data/generated.json')
    parser.add_argument('--history-file', type=Path, help='Private incremental cache destination')
    args = parser.parse_args()
    if bool(args.extension) == args.all:
        parser.error('Specify an extension or --all')
    data = json.loads(args.catalog.read_text())
    entries = data['extensions'] if args.all else [e for e in data['extensions'] if e['name'] == args.extension]
    if not entries:
        parser.error('Extension not found in catalog')
    if args.all:
        generate_history(entries, full_refresh=args.full_refresh, history_path=args.history_file)
    else:
        refresh_entry(entries[0], args.full_refresh, args.history_file)


if __name__ == '__main__':
    main()
