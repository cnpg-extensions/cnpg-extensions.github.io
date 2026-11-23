"""Select a repository from the same upstream links shown on the extension page."""
from collections import defaultdict
from functools import lru_cache
import gzip
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import quote, urlsplit

import requests
import yaml

from catalog_recipes import find_recipe, recipe_index
from debian_upstream import upstream_links

ROOT = Path(__file__).resolve().parents[1]



def repository_mapping(links, fallback=None):
    for label in ('Upstream release repository', 'Debian release watch', 'Upstream repository',
                  'Debian upstream repository', 'Upstream homepage'):
        candidates = {}
        for link in links:
            if link['label'] != label:
                continue
            if label == 'Debian release watch':
                # An archive-only watch does not identify a Git repository.
                return fallback
            url = link['url'].rstrip('/').removesuffix('.git')
            parsed = urlsplit(url)
            if label == 'Upstream homepage' and not re.fullmatch(
                r'https?://(github\.com/[\w.-]+/[\w.-]+|(?:gitlab\.com|salsa\.debian\.org)/[\w.-]+(?:/[\w.-]+)+)', url
            ):
                continue
            if parsed.scheme in ('http', 'https') and parsed.hostname and '/-/' not in parsed.path:
                repository = parsed._replace(scheme='https').geturl()
                candidates[repository] = {'repository': repository, 'evidence': link['evidence']}
        if len(candidates) == 1:
            result = next(iter(candidates.values()))
            if fallback and result['repository'] in fallback.get('mirrors', []):
                return fallback
            return result
        if candidates:
            break
    return fallback


def scan_skip_reason(mapping):
    if not mapping:
        return 'The catalog could not identify a single upstream source repository.'
    if 'mirror' in mapping.get('note', '').lower():
        # Older generated catalogs identified mirror mappings with this note.
        return 'The recorded repository is a mirror. Scorecards cover upstream repositories only.'
    if mapping.get('scanSkipReason'):
        return mapping['scanSkipReason']
    host = urlsplit(mapping['repository']).hostname
    if host not in ('github.com', 'gitlab.com'):
        return f'The upstream repository is hosted on {host}, which this scanner does not support.'
    return ''


def valid_url(value):
    return value if isinstance(value, str) and urlsplit(value).scheme in ('http', 'https') and urlsplit(value).netloc else ''

def package_index(distro):
    url = f'https://apt.postgresql.org/pub/repos/apt/dists/{distro}-pgdg/main/binary-amd64/Packages.gz'
    cache = ROOT / '.cache' / f'overview-{distro}-Packages.gz'
    if not cache.exists():
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(response.content)
    records = {}
    for paragraph in gzip.decompress(cache.read_bytes()).decode().split('\n\n'):
        fields = {}
        for line in paragraph.splitlines():
            if line and not line.startswith((' ', '\t')) and ': ' in line:
                key, value = line.split(': ', 1)
                fields[key] = value
        if fields.get('Package'):
            records[fields['Package']] = fields
    return records, url

def project_links(recipe_text, index, distro):
    upstream_repos = sorted(set(re.findall(r'datasource=(github|gitlab)-(?:tags|releases)\s+depName=([\w.-]+(?:/[\w.-]+)+)', recipe_text)))
    deb_names = list(dict.fromkeys(re.findall(r'suite=[\w-]+\s+depName=([\w.+-]+)', recipe_text)))
    links = [{'label': 'Upstream repository', 'url': f'https://{host}.com/{repo}', 'evidence': 'Recipe Renovate metadata'} for host, repo in upstream_repos]
    for url in sorted(set(re.findall(r'datasource=git-tags\s+depName=(https?://[^\s"\']+)', recipe_text))):
        links.append({'label': 'Upstream repository', 'url': url.removesuffix('.git'),
                      'evidence': 'Recipe Renovate metadata'})
    for name in deb_names:
        record = index.get(name)
        if not record:
            continue
        source = record.get('Source', name).split(' ')[0]
        links.append({'label': 'Debian source package', 'url': 'https://tracker.debian.org/pkg/' + quote(source, safe=''), 'evidence': f'PGDG package metadata: {name}'})
        source_field = record.get('Source', name)
        version = source_field.partition(' (')[2].rstrip(')') or record['Version']
        links.extend(upstream_links(distro, source, version))
        homepage = valid_url(record.get('Homepage'))
        if homepage:
            links.append({'label': 'Upstream homepage', 'url': homepage, 'evidence': f'Homepage field in PGDG package metadata: {name}'})
    return list({(x['label'], x['url']): x for x in links}.values())

def publisher_for(reference):
    return 'cloudnative-pg' if '/cloudnative-pg/' in reference else 'cnpg-extensions'


def catalog_variants(directory):
    variants = defaultdict(set)
    for path in sorted(Path(directory).glob('catalog-*.yaml')):
        doc = yaml.safe_load(path.read_text())
        distro = doc['metadata']['labels']['images.cnpg.io/os']
        for image in doc['spec']['images']:
            for extension in image.get('extensions', []):
                name = extension['name']
                if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', name):
                    raise ValueError('Unsafe extension name')
                reference = extension['image']['reference']
                publisher = publisher_for(reference)
                variants[name].add((publisher, distro))
    if not variants:
        raise ValueError('Catalog contains no extensions')
    return variants


def discover_projects(directory, cache, selected=()):
    variants = catalog_variants(directory)
    unknown = set(selected) - variants.keys()
    if unknown:
        raise ValueError('Unknown extensions: ' + ', '.join(sorted(unknown)))
    reviewed = json.loads((ROOT/'data/scorecard-repositories.json').read_text())
    commits = {source: subprocess.check_output(['git', '-C', cache/source, 'rev-parse', 'HEAD'],
                                               text=True).strip() for source in ('upstream', 'source')}
    recipes, _ = recipe_index(cache, commits)
    packages = lru_cache(maxsize=None)(package_index)
    projects = {}
    for name in sorted(selected or variants):
        by_variant = {}
        for publisher, distro in sorted(variants[name]):
            recipe = find_recipe(cache, recipes, publisher, name, commits)
            links = []
            if recipe:
                metadata = recipe['readme'].with_name('metadata.hcl')
                if metadata.is_file():
                    links = project_links(metadata.read_text(), packages(distro)[0], distro)
            by_variant[publisher, distro] = links
        candidates = [link for links in by_variant.values() for link in links]
        projects[name] = (repository_mapping(candidates, reviewed.get(name)), by_variant)
    return projects
