"""Resolve catalog source revisions once for a website run."""

import json
import subprocess

REPOS = {'source':'cnpg-extensions/postgres-extensions-containers', 'upstream':'cloudnative-pg/postgres-extensions-containers', 'artifacts':'cnpg-extensions/artifacts'}


if __name__ == "__main__":
    commits = {}
    for name, repo in REPOS.items():
        result = subprocess.check_output(
            ["git", "ls-remote", "--exit-code", f"https://github.com/{repo}.git", "HEAD"], text=True
        )
        commits[name] = result.split()[0]
    print(json.dumps(commits))
