"""Run the documented OSV supplement against an unchanged SPDX document."""
import json
import os
import hashlib
import zipfile
from pathlib import Path
import requests
import subprocess
from datetime import datetime, timezone


def refresh_database(root):
    """Refresh each supported ecosystem once; never scan stale data after failure."""
    cache = Path(root) / '.cache/osv-local-db'
    metadata = {'path': str(cache), 'databases': {}}
    try:
        for ecosystem in ('crates.io', 'Debian'):
            url = f'https://osv-vulnerabilities.storage.googleapis.com/{ecosystem}/all.zip'
            response = requests.get(url, timeout=180)
            response.raise_for_status()
            destination = cache / 'osv-scalibr' / ecosystem / 'all.zip'
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix('.tmp')
            try:
                temporary.write_bytes(response.content)
                with zipfile.ZipFile(temporary) as archive:
                    if archive.testzip() is not None:
                        raise ValueError('Corrupt OSV database archive')
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
            metadata['databases'][ecosystem] = {'sha256': hashlib.sha256(response.content).hexdigest(), 'lastModified': response.headers.get('Last-Modified')}
        metadata['refreshedAt'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    except Exception as error:
        metadata['error'] = 'OSV database refresh failed: ' + str(error)
    return metadata


def findings(raw):
    found = {}
    for result in raw.get('results', []):
        for entry in result.get('packages', []):
            package = entry['package']
            for advisory in entry.get('vulnerabilities', []):
                key = (advisory['id'], package['name'], package['version'])
                found[key] = dict(id=key[0], package=key[1], version=key[2])
    return list(found.values())


def scan_osv(sbom, root, executable, database=None):
    if not executable:
        return {'status': 'not-run', 'reason': 'OSV scanning was not requested.'}
    if database and database.get('error'):
        return {'status': 'unavailable', 'reason': database['error']}
    env = {**os.environ, 'OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY': str(Path(root) / '.cache/osv-local-db')}
    try:
        result = subprocess.run([executable, 'scan', 'source', '--offline', '-L', str(sbom), '--format', 'json'], capture_output=True, text=True, timeout=600, env=env)
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr[-400:])
        raw = json.loads(result.stdout)
        if not isinstance(raw.get('results'), list):
            raise ValueError('OSV report lacks results')
        report = sbom.with_suffix('.osv.json')
        report.write_text(result.stdout)
        return {'status': 'scanned', 'scannedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'database': database or {}, 'findings': findings(raw), 'report': str(report.relative_to(root / 'static'))}
    except Exception as error:
        return {'status': 'unavailable', 'reason': str(error)}
