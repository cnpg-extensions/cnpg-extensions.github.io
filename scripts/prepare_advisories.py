"""Fetch and validate the advisory databases shared by the workflow's scan jobs."""
import json
import subprocess
from pathlib import Path

from evidence_shards import database_identity
from osv_scan import refresh_database


def main():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['grype', 'db', 'update'], check=True)
    database = json.loads(subprocess.check_output(['grype', 'db', 'status', '-o', 'json']))
    osv_database = refresh_database(root)
    if osv_database.get('error'):
        raise RuntimeError(osv_database['error'])
    database_identity(database, osv_database)
    manifest = root / '.cache/advisory-databases.json'
    manifest.write_text(json.dumps({'database': database, 'osvDatabase': osv_database}))


if __name__ == '__main__':
    main()
