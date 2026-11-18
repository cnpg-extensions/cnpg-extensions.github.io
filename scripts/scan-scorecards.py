#!/usr/bin/env python3
"""Scan catalog upstreams without building or executing their code."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
import yaml

ROOT = Path(__file__).resolve().parents[1]


def catalog_names(directory):
    names = set()
    for path in sorted(Path(directory).glob('catalog-*.yaml')):
        doc = yaml.safe_load(path.read_text())
        for image in doc['spec']['images']:
            names.update(e['name'] for e in image.get('extensions', []))
    if not names:
        raise ValueError('Catalog contains no extensions')
    return names


def diagnostic(text):
    # Never persist authentication material, even if a tool includes it in an error.
    for name in ('GITHUB_AUTH_TOKEN', 'GITHUB_TOKEN', 'GH_TOKEN', 'GITLAB_AUTH_TOKEN'):
        if os.environ.get(name):
            text = text.replace(os.environ[name], '[REDACTED]')
    return text[-6000:]


def scan(repository, binary, output, timeout):
    host = urlsplit(repository).netloc
    if host not in ('github.com', 'gitlab.com'):
        return {'status': 'unsupported', 'reason': 'Host not enabled for this scanner'}
    if host == 'gitlab.com' and not os.environ.get('GITLAB_AUTH_TOKEN'):
        return {'status': 'unavailable', 'reason': 'GITLAB_AUTH_TOKEN is not configured'}
    try:
        result = subprocess.run([binary, '--repo='+repository, '--show-details', '--format=json'],
                                capture_output=True, text=True, timeout=timeout)
        try:
            report = json.loads(result.stdout)
        except ValueError:
            return {'status': 'unavailable', 'reason': 'Invalid JSON from Scorecard',
                    'diagnostic': diagnostic(result.stderr + '\n' + result.stdout),
                    'exitCode': result.returncode}
        if not isinstance(report.get('checks'), list) or not report['checks']:
            raise ValueError('No check results')
        if not report.get('repo', {}).get('commit') or not report.get('date'):
            raise ValueError('Missing report provenance')
        filename = hashlib.sha256(repository.encode()).hexdigest()+'.json'
        (output/filename).write_text(result.stdout)
        return {'status': 'available', 'report': filename, 'date': report['date'],
                'inconclusiveChecks': sum(c.get('score', -1) < 0 for c in report['checks']),
                'exitCode': result.returncode,
                **({'diagnostic': diagnostic(result.stderr)} if result.returncode else {})}
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        return {'status': 'unavailable', 'reason': type(exc).__name__}


def scan_targets(catalog, configured, requested):
    if set(configured) - catalog:
        raise ValueError('Configured extensions absent from catalog: '+', '.join(sorted(set(configured)-catalog)))
    if requested - set(configured):
        raise ValueError('Extensions not in local scan list: '+', '.join(sorted(requested-set(configured))))
    return sorted(requested or configured)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog-dir', required=True)
    parser.add_argument('--output', default='scorecard-results')
    parser.add_argument('--extensions', default='', help='Comma-separated subset of local scan list; empty scans the complete list')
    parser.add_argument('--binary', default='scorecard')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        parser.error('workers must be between 1 and 4')
    names = catalog_names(args.catalog_dir)
    selected = {n.strip() for n in args.extensions.split(',') if n.strip()}
    if selected - names:
        parser.error('Unknown extensions: '+', '.join(sorted(selected-names)))
    mappings = json.loads((ROOT/'data/scorecard-repositories.json').read_text())
    configured = json.loads((ROOT/'data/scorecard-local-scans.json').read_text())['extensions']
    try:
        targets = scan_targets(names, configured, selected)
    except ValueError as exc:
        parser.error(str(exc))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error('Output directory must be empty to prevent stale reports')
    repositories = sorted({mappings[n]['repository'] for n in targets if n in mappings})
    def run(repository):
        result = scan(repository, args.binary, output, args.timeout)
        print(repository + ': ' + result['status'], flush=True)
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = dict(zip(repositories, pool.map(run, repositories)))
    entries = {n: {**mappings.get(n, {}), **results.get(mappings.get(n, {}).get('repository'),
               {'status': 'unavailable', 'reason': 'No reviewed upstream repository mapping'})} for n in targets}
    catalog_commit = subprocess.check_output(['git', '-C', args.catalog_dir, 'rev-parse', 'HEAD'], text=True).strip()
    index = {'schemaVersion': 1, 'generatedAt': datetime.now(timezone.utc).isoformat(),
             'catalogCommit': catalog_commit, 'scope': 'subset' if selected else 'local-list',
             'configuredExtensions': configured,
             'producer': os.environ.get('GITHUB_REPOSITORY', 'local'),
             'runId': os.environ.get('GITHUB_RUN_ID'), 'extensions': entries}
    (output/'index.json').write_text(json.dumps(index, indent=2)+'\n')
    available = sum(r['status'] == 'available' for r in entries.values())
    summary = f'Scorecard reports: {available}/{len(entries)} extensions; scope: {index["scope"]}.\n'
    summary += '\n'.join(f'- {n}: {r["status"]}'+(' — '+r['reason'] if 'reason' in r else '') for n, r in entries.items())+'\n'
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(summary)
    if not available:
        raise SystemExit('No reports produced')

if __name__ == '__main__':
    main()
