"""Resolve upstream Scorecards: public API first, weekly artifact second."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlsplit

import requests

from scorecard_repositories import discover_projects, scan_skip_reason

ROOT = Path(__file__).resolve().parents[1]
PRODUCER = 'cnpg-extensions/cnpg-extensions.github.io'


def valid_report(report, repository):
    return (isinstance(report, dict) and report.get('date')
            and report.get('repo', {}).get('name', '').removeprefix('https://').rstrip('/').lower()
            == repository.removeprefix('https://').rstrip('/').lower()
            and report.get('repo', {}).get('commit')
            and isinstance(report.get('checks'), list) and report['checks']
            and all(isinstance(c, dict) and isinstance(c.get('name'), str)
                    and isinstance(c.get('score'), (int, float)) and -1 <= c['score'] <= 10
                    for c in report['checks']))


def gh_json(endpoint):
    return json.loads(subprocess.check_output(['gh', 'api', endpoint], text=True, timeout=60))


def cached_reports():
    """Read only a complete artifact from a successful main-branch workflow run."""
    try:
        runs = gh_json(f'repos/{PRODUCER}/actions/workflows/scorecards.yml/runs?branch=main&status=success&per_page=100')
        for run in runs['workflow_runs']:
            artifacts = gh_json(f'repos/{PRODUCER}/actions/runs/{run["id"]}/artifacts')['artifacts']
            if not any(a['name'] == 'scorecard-results' and not a['expired'] for a in artifacts):
                continue
            with tempfile.TemporaryDirectory() as directory:
                subprocess.run(['gh', 'run', 'download', str(run['id']), '--repo', PRODUCER,
                                '--name', 'scorecard-results', '--dir', directory], check=True, timeout=120)
                return read_artifact(Path(directory), str(run['id']))
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        print(f'Scorecard artifact unavailable: {type(exc).__name__}')
    return {}


def read_artifact(directory, run_id):
    index = json.loads((directory / 'index.json').read_text())
    if (index.get('schemaVersion') != 1 or index.get('scope') not in ('catalog', 'local-list')
            or index.get('producer') != PRODUCER or str(index.get('runId')) != run_id):
        return {}
    reports = {}
    for entry in index['extensions'].values():
        repository = entry.get('repository', '')
        filename = entry.get('report', '')
        if entry.get('status') != 'available' or filename != hashlib.sha256(repository.encode()).hexdigest() + '.json':
            continue
        try:
            raw = (directory / filename).read_text()
            report = json.loads(raw)
            if valid_report(report, repository):
                reports[repository] = (report, raw)
        except (OSError, ValueError, TypeError):
            continue
    return reports


def public_report(repository):
    api_url = 'https://api.securityscorecards.dev/projects/' + repository.removeprefix('https://')
    if urlsplit(repository).netloc in ('github.com', 'gitlab.com'):
        try:
            response = requests.get(api_url, timeout=20)
            response.raise_for_status()
            report = response.json()
            if valid_report(report, repository):
                return present(report, repository, 'OpenSSF API', api_url)
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            pass
    return None


def resolve(repository, fallback, output):
    report = public_report(repository)
    if report:
        return report
    if repository in fallback:
        report, raw = fallback[repository]
        filename = hashlib.sha256(repository.encode()).hexdigest() + '.json'
        output.mkdir(parents=True, exist_ok=True)
        (output / filename).write_text(raw)
        return present(report, repository, 'Cached scan', 'reports/scorecards/' + filename)
    return {'status': 'unavailable', 'repository': repository,
            'reason': 'No usable OpenSSF report or cached scan was available for the upstream repository.'}


# OpenSSF v5.6.0, matching the pinned scanner:
# https://github.com/ossf/scorecard/blob/v5.6.0/docs/checks/internal/checks.yaml
# Risk is only an ordering input; do not add labels or alter report scores.
CHECK_RISK_ORDER = {
    **dict.fromkeys(('Dangerous-Workflow', 'Webhooks'), 0),
    **dict.fromkeys(('Maintained', 'Dependency-Update-Tool', 'Binary-Artifacts',
                     'Branch-Protection', 'Code-Review', 'Signed-Releases',
                     'Token-Permissions', 'Vulnerabilities'), 1),
    **dict.fromkeys(('Fuzzing', 'Packaging', 'Pinned-Dependencies', 'SAST',
                     'SBOM', 'Security-Policy'), 2),
    **dict.fromkeys(('CI-Tests', 'CII-Best-Practices', 'Contributors', 'License'), 3),
}


def check_order(check):
    # Keep new, unclassified checks visible after known checks until reviewed.
    return CHECK_RISK_ORDER.get(check['name'], 4), check['name'].lower()


def present(report, repository, source, url):
    # Deliberately exclude the aggregate score; preserve each check's raw score and explanation.
    return {'status': 'available', 'repository': repository, 'source': source, 'url': url,
            'date': report['date'], 'commit': report['repo']['commit'],
            'checks': sorted(report['checks'], key=check_order)}


def generate_scorecards():
    extensions = json.loads((ROOT / 'data/generated.json').read_text())['extensions']
    if all('sourceRepository' in entry for entry in extensions):
        mappings = {entry['name']: entry['sourceRepository'] for entry in extensions}
    else:
        # Older generated catalogs predate sourceRepository.
        cache = ROOT / '.cache'
        projects = discover_projects(cache/'artifacts/image-catalogs-extensions', cache)
        mappings = {entry['name']: projects.get(entry['name'], (None, {}))[0] for entry in extensions}
    fallback = cached_reports()
    repositories = sorted({entry['repository'] for entry in mappings.values() if not scan_skip_reason(entry)})
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = dict(zip(repositories, pool.map(
            lambda repository: resolve(repository, fallback, ROOT / 'static/reports/scorecards'), repositories)))
    data = {}
    for name, mapping in mappings.items():
        reason = scan_skip_reason(mapping)
        data[name] = {'status': 'unavailable', 'reason': reason} if reason else results[mapping['repository']]
    (ROOT / 'data/scorecards.json').write_text(json.dumps(data))
    print(f'Scorecards available: {sum(r["status"] == "available" for r in data.values())}/{len(data)}')


if __name__ == '__main__':
    generate_scorecards()
