#!/usr/bin/env python3
"""Hosted integration check: populate real caches, then prove reuse on a fresh runner."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
import requests
import yaml
from generate import Registry, ROOT
from image_notices import container_notices

import version_history as history

phase = sys.argv[1]
fixture = ROOT / '.cache/cache-verification.json'
if phase == 'populate':
    response = requests.get('https://raw.githubusercontent.com/cnpg-extensions/artifacts/main/image-catalogs-extensions/catalog-minimal-trixie.yaml', timeout=60)
    response.raise_for_status()
    catalog = yaml.safe_load(response.text)
    item = next(e for image in catalog['spec']['images'] for e in image.get('extensions', []) if e['name'] == 'semver')
    reference = item['image']['reference']
    entry = {'name': 'semver', 'variants': [{'reference': reference}]}
    (ROOT / 'data').mkdir(exist_ok=True)
    history.refresh_entry(entry)
    registry = Registry(reference)
    index = registry.get(registry.digest)
    platform = next(m for m in index['manifests'] if m.get('platform', {}).get('architecture') == 'amd64')
    notice = container_notices(reference, 'amd64', platform['digest'], ROOT / '.cache')
    assert notice['status'] == 'available', notice
    fixture.parent.mkdir(exist_ok=True)
    fixture.write_text(json.dumps({'entry': entry, 'digest': platform['digest'], 'notices': notice}))
    print('COLD CACHE: fetched real semver history and extracted real image notices.', flush=True)
elif phase == 'restore':
    saved = json.loads(fixture.read_text())
    registry = Registry(saved['entry']['variants'][0]['reference'])
    with patch.object(registry.session, 'get', side_effect=AssertionError('Unexpected OCI fetch')):
        registry.get(registry.digest)
    before = json.loads((ROOT / '.cache/version-history/history.json').read_text())['semver']['builds']
    with patch.object(history, 'read_build', side_effect=AssertionError('Unexpected manifest fetch')) as manifests, patch.object(history, 'add_image_links', side_effect=AssertionError('Unexpected GitHub HTML fetch')) as links:
        history.refresh_entry(saved['entry'])
        manifests.assert_not_called()
        links.assert_not_called()
    with patch('image_notices.subprocess.run', side_effect=AssertionError('Unexpected Docker command')) as run, patch('image_notices.subprocess.check_output', side_effect=AssertionError('Unexpected Docker command')) as output:
        notice = container_notices(saved['entry']['variants'][0]['reference'], 'amd64', saved['digest'], ROOT / '.cache')
        assert notice == saved['notices']
        run.assert_not_called()
        output.assert_not_called()
    after = json.loads((ROOT / '.cache/version-history/history.json').read_text())['semver']['builds']
    assert before == after, 'Unchanged history must preserve all records'
    print(f'WARM CACHE VERIFIED: {len(after)} history records; zero manifest fetches, zero GitHub page fetches, zero Docker commands.', flush=True)
else:
    raise SystemExit('Expected populate or restore')
