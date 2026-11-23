"""Locate the source recipe used to build a catalog extension."""
import hcl2
from hcl2.utils import SerializationOptions

from source_commits import REPOS


def recipe_index(cache, commits):
    recipes = {}
    routes = {}
    options = SerializationOptions(strip_string_quotes=True, with_comments=False)
    for source in ('upstream', 'source'):
        root = cache / source
        repo = REPOS[source]
        for path in root.rglob('metadata.hcl'):
            readme = path.with_name('README.md')
            if '.git' in path.parts or not readme.is_file():
                continue
            try:
                with path.open() as stream:
                    metadata = hcl2.load(stream, serialization_options=options).get('metadata', {})
            except Exception:
                continue
            name = metadata.get('name') or metadata.get('image_name')
            if not isinstance(name, str):
                continue
            relative = readme.relative_to(root).as_posix()
            default_build = {'pgrx': 'PGRX', 'universe': 'Universe'}.get(relative.split('/')[0], 'Debian')
            recipes[repo, name] = {
                'meta': metadata, 'readme': readme, 'repo': repo, 'commit': commits[source],
                'path': relative, 'build': metadata.get('build_system') or default_build,
            }
            routes[repo, relative] = 'extensions/' + name
        routes[repo, 'README.md'] = 'get-started'
    return recipes, routes


def find_recipe(cache, recipes, publisher, name, commits):
    source = 'upstream' if publisher == 'cloudnative-pg' else 'source'
    repo = REPOS[source]
    if (repo, name) in recipes:
        return recipes[repo, name]
    # Some recipes use a different image_name, but their directory matches the catalog.
    root = cache / source
    readme = next(root.rglob(name + '/README.md'), None)
    if readme:
        return {'meta': {}, 'readme': readme, 'repo': repo, 'commit': commits[source],
                'path': readme.relative_to(root).as_posix(), 'build': 'Debian'}
