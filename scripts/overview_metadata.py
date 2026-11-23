#!/usr/bin/env python3
"""Enrich generated catalog evidence with license summaries and upstream links.

Does not refresh source checkouts, image versions, scan results, or timestamps.
"""
from collections import Counter
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, quote
from scorecard_repositories import discover_projects, publisher_for
import hcl2
from hcl2.utils import SerializationOptions

ROOT = Path(__file__).resolve().parents[1]

def deb_identity(package):
    for ref in package.get('externalRefs', []):
        value = ref.get('referenceLocator', '')
        if ref.get('referenceType') == 'purl' and value.startswith('pkg:deb/debian/'):
            path, _, query = value.partition('?')
            # The upstream qualifier may include a source version (e.g. cairo@1.18.4-1).
            source = parse_qs(query).get('upstream', [''])[0].partition('@')[0]
            return unquote(path.split('@')[0].split('/')[-1]), source
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

def main():
    path = ROOT / 'data/generated.json'
    data = json.loads(path.read_text())
    cache = ROOT / '.cache'
    projects = discover_projects(cache/'artifacts/image-catalogs-extensions', cache)
    for entry in data['extensions']:
        repository, by_variant = projects[entry['name']]
        entry['sourceRepository'] = repository
        cache_source = 'upstream' if entry['publisher'] == 'cloudnative-pg' else 'source'
        recipe_path = entry['source'].split('/blob/main/', 1)[-1]
        recipe = ROOT / '.cache' / cache_source / Path(recipe_path).with_name('metadata.hcl')
        recipe_text = recipe.read_text() if recipe.exists() else ''
        metadata = hcl2.loads(recipe_text, serialization_options=SerializationOptions(strip_string_quotes=True, with_comments=False)).get('metadata', {}) if recipe_text else {}
        entry['title'] = entry['name']
        entry['sqlName'] = metadata.get('sql_name', '')
        for variant in entry['variants']:
            variant['projectLinks'] = by_variant[publisher_for(variant['reference']), variant['distro']]
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
