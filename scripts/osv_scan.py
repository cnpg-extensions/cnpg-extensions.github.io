"""Run the documented OSV supplement against an unchanged SPDX document."""
import json
import subprocess
from datetime import datetime, timezone


def findings(raw):
    found = {}
    for result in raw.get('results', []):
        for entry in result.get('packages', []):
            package = entry['package']
            for advisory in entry.get('vulnerabilities', []):
                key = (advisory['id'], package['name'], package['version'])
                found[key] = dict(id=key[0], package=key[1], version=key[2])
    return list(found.values())


def scan_osv(sbom, root, executable):
    if not executable:
        return {'status': 'not-run', 'reason': 'OSV scanning was not requested.'}
    try:
        result = subprocess.run([executable, 'scan', 'source', '-L', str(sbom), '--format', 'json'], capture_output=True, text=True, timeout=600)
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr[-400:])
        raw = json.loads(result.stdout)
        if not isinstance(raw.get('results'), list):
            raise ValueError('OSV report lacks results')
        report = sbom.with_suffix('.osv.json')
        report.write_text(result.stdout)
        return {'status': 'scanned', 'scannedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'findings': findings(raw), 'report': str(report.relative_to(root / 'static'))}
    except Exception as error:
        return {'status': 'unavailable', 'reason': str(error)}
