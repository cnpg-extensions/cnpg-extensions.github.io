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

from scorecard_repositories import discover_projects, scan_skip_reason

ROOT = Path(__file__).resolve().parents[1]


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog-dir', required=True)
    parser.add_argument('--recipe-cache', type=Path, default=ROOT/'.cache', help='Directory containing source and upstream checkouts')
    parser.add_argument('--output', default='scorecard-results')
    parser.add_argument('--extensions', default='', help='Comma-separated catalog extension names; empty scans the complete catalog')
    parser.add_argument('--binary', default='scorecard')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        parser.error('workers must be between 1 and 4')
    selected = {n.strip() for n in args.extensions.split(',') if n.strip()}
    try:
        projects = discover_projects(args.catalog_dir, args.recipe_cache, selected)
    except ValueError as exc:
        parser.error(str(exc))
    targets = sorted(projects)
    mappings = {name: mapping for name, (mapping, _) in projects.items() if mapping}
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error('Output directory must be empty to prevent stale reports')
    repositories = sorted({mappings[n]['repository'] for n in targets if not scan_skip_reason(mappings.get(n))})
    def run(repository):
        result = scan(repository, args.binary, output, args.timeout)
        print(repository + ': ' + result['status'], flush=True)
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = dict(zip(repositories, pool.map(run, repositories)))
    entries = {}
    for name in targets:
        mapping = mappings.get(name, {})
        reason = scan_skip_reason(mapping)
        result = {'status': 'skipped', 'reason': reason} if reason else results[mapping['repository']]
        entries[name] = {**mapping, **result}
    catalog_commit = subprocess.check_output(['git', '-C', args.catalog_dir, 'rev-parse', 'HEAD'], text=True).strip()
    index = {'schemaVersion': 1, 'generatedAt': datetime.now(timezone.utc).isoformat(),
             'catalogCommit': catalog_commit, 'scope': 'subset' if selected else 'catalog',
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
    if repositories and not available:
        raise SystemExit('No reports produced')

if __name__ == '__main__':
    main()
