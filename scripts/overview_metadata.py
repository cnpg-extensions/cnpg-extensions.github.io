#!/usr/bin/env python3
"""Enrich generated catalog evidence with license summaries and upstream links.

Does not refresh source checkouts, image versions, scan results, or timestamps.
"""
from collections import Counter
import gzip
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, quote, urlsplit
import requests
import hcl2
from hcl2.utils import SerializationOptions

ROOT = Path(__file__).resolve().parents[1]

def valid_url(value):
    return value if isinstance(value, str) and urlsplit(value).scheme in ('http', 'https') and urlsplit(value).netloc else ''

def deb_identity(package):
    for ref in package.get('externalRefs', []):
        value = ref.get('referenceLocator', '')
        if ref.get('referenceType') == 'purl' and value.startswith('pkg:deb/debian/'):
            path, _, query = value.partition('?')
            return unquote(path.split('@')[0].split('/')[-1]), parse_qs(query).get('upstream', [''])[0]
    return '', ''

def license_summary(packages):
    counts = Counter()
    unknown = 0
    for package in packages:
        expressions = [package.get('declared'), package.get('concluded')]
        expressions = [x for x in expressions if x and x not in ('NOASSERTION', 'NONE')]
        if not expressions:
            expressions = [x for x in package.get('files', []) if x and x not in ('NOASSERTION', 'NONE')]
        if not expressions:
            unknown += 1
        # Preserve whole expressions and count a package once per distinct expression.
        for expression in set(expressions):
            counts[expression] += 1
    return {'licenses': [{'expression': k, 'count': v} for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0]))], 'unknownPackages': unknown}

def setup_metadata(metadata, variant):
    version = metadata.get('versions', {}).get(variant['distro'], {}).get(str(variant['pg']), {})
    return {
        'sqlName': metadata.get('sql_name'),
        'sqlVersion': version.get('sql'),
        'sharedPreloadLibraries': metadata.get('shared_preload_libraries'),
        'postgresqlParameters': metadata.get('postgresql_parameters'),
        'requiredExtensions': metadata.get('required_extensions'),
        'createExtension': metadata.get('create_extension'),
    }

def package_index(distro):
    url = f'https://apt.postgresql.org/pub/repos/apt/dists/{distro}-pgdg/main/binary-amd64/Packages.gz'
    cache = ROOT / '.cache' / f'overview-{distro}-Packages.gz'
    if not cache.exists():
        response = requests.get(url, timeout=60)
        response.raise_for_status()
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

def main():
    path = ROOT / 'data/generated.json'
    data = json.loads(path.read_text())
    indexes = {d: package_index(d) for d in sorted({v['distro'] for e in data['extensions'] for v in e['variants']})}
    for entry in data['extensions']:
        cache_source = 'upstream' if entry['publisher'] == 'cloudnative-pg' else 'source'
        recipe_path = entry['source'].split('/blob/main/', 1)[-1]
        recipe = ROOT / '.cache' / cache_source / Path(recipe_path).with_name('metadata.hcl')
        recipe_text = recipe.read_text() if recipe.exists() else ''
        metadata = hcl2.loads(recipe_text, serialization_options=SerializationOptions(strip_string_quotes=True, with_comments=False)).get('metadata', {}) if recipe_text else {}
        entry['title'] = entry['name']
        entry['sqlName'] = metadata.get('sql_name', '')
        upstream_repos = sorted(set(re.findall(r'datasource=(github|gitlab)-(?:tags|releases)\s+depName=([\w.-]+(?:/[\w.-]+)+)', recipe_text)))
        deb_names = list(dict.fromkeys(re.findall(r'suite=[\w-]+\s+depName=([\w.+-]+)', recipe_text)))
        for variant in entry['variants']:
            index, index_url = indexes[variant['distro']]
            links = [{'label': 'Upstream repository', 'url': f'https://{host}.com/{repo}', 'evidence': 'Recipe Renovate metadata'} for host, repo in upstream_repos]
            for name in deb_names:
                record = index.get(name)
                if not record:
                    continue
                source = record.get('Source', name).split(' ')[0]
                links.append({'label': 'Debian source package', 'url': 'https://tracker.debian.org/pkg/' + quote(source, safe=''), 'evidence': f'PGDG package metadata: {name}'})
                homepage = valid_url(record.get('Homepage'))
                if homepage:
                    links.append({'label': 'Upstream homepage', 'url': homepage, 'evidence': f'Homepage field in PGDG package metadata: {name}'})
            variant['projectLinks'] = list({(x['label'], x['url']): x for x in links}.values())
            for platform in variant['platforms']:
                platform['setup'] = setup_metadata(metadata, variant)
                if platform.get('sbom') and entry['publisher'] != 'cloudnative-pg':
                    sbom = json.loads((ROOT / 'static' / platform['sbom']).read_text())
                    originals = {(p['name'], p.get('versionInfo', 'Not recorded')): p for p in sbom.get('packages', [])}
                    for package in platform.get('packages', []):
                        original = originals.get((package['name'], package['version']), {})
                        name, source = deb_identity(original)
                        if source:
                            package['packageURL'] = 'https://tracker.debian.org/pkg/' + quote(source, safe='')
                        elif name:
                            package['packageURL'] = 'https://packages.debian.org/search?keywords=' + quote(name, safe='') + '&searchon=names&suite=all&section=all'
                    platform['overview'] = license_summary(platform.get('packages', []))
    path.write_text(json.dumps(data))
    print('Enriched existing catalog; source and scan timestamps unchanged.')

if __name__ == '__main__':
    main()
