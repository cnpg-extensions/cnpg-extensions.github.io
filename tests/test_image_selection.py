"""Render independent maintained versions for two PostgreSQL majors."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from generate import variant_order


def build_fixture(site):
    """Isolated synthetic site; never add PG19 images to the published catalog."""
    site.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / 'layouts', site / 'layouts', dirs_exist_ok=True)
    shutil.copytree(ROOT / 'assets', site / 'assets', dirs_exist_ok=True)
    shutil.copytree(ROOT / 'static/assets', site / 'static/assets', dirs_exist_ok=True)
    (site / 'hugo.toml').write_text('baseURL = "http://localhost:8766/"\n[markup.goldmark.renderer]\nunsafe = true\n')
    variants = []
    # Deliberately interleave major/distribution order as independent catalogs can.
    for pg, distro in ((18, 'trixie'), (19, 'bookworm'), (18, 'bookworm'), (19, 'trixie')):
        version, sql = ('1.8.4', '1.8') if pg == 18 else ('2.0.1', '2.0')
        platforms = []
        for arch in ('arm64', 'amd64'):
            sbom = f'reports/fixture/{distro}-pg{pg}-{arch}.spdx.json'
            path = site / 'static' / sbom
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}')
            platforms.append({
                'architecture': arch, 'status': 'available', 'sbom': sbom,
                'packages': [{'name': f'dependency-pg{pg}', 'version': version,
                              'declared': 'MIT', 'concluded': 'MIT', 'files': [], 'ecosystem': 'deb'}],
                'scan': {'status': 'not-run'}, 'osvScan': {'status': 'not-run'},
                'setup': {'sqlName': 'fixture', 'sqlVersion': sql, 'requiredExtensions': [],
                          'sharedPreloadLibraries': [], 'postgresqlParameters': {}},
                'containerNotices': {'status': 'available', 'files': [
                    {'path': '/licenses/fixture', 'text': f'PG {pg} synthetic notice', 'sha256': 'fixture'}]},
                'overview': {'licenses': [{'expression': 'MIT', 'count': 1}], 'unknownPackages': 0},
            })
        variants.append({'pg': pg, 'distro': distro, 'version': version, 'annotations': {},
                         'reference': 'ghcr.io/cnpg-extensions/fixture@sha256:' + str(pg) * 32,
                         'platforms': platforms})
    variants.sort(key=variant_order)
    entry = {'name': 'fixture', 'title': 'Version selector fixture', 'sqlName': 'fixture',
             'description': 'Synthetic PG18/PG19 validation data, not a published extension.',
             'publisher': 'cnpg-extensions', 'build': 'Debian', 'declaredLicenses': ['MIT'],
             'source': 'https://example.org/readme', 'variants': variants,
             'version': variants[0]['version'], 'pgVersions': [18, 19], 'distros': ['bookworm', 'trixie']}
    (site / 'data').mkdir(exist_ok=True)
    (site / 'data/generated.json').write_text(json.dumps({'count': 1, 'extensions': [entry]}))
    for view in ('overview', 'documentation', 'dependencies', 'licenses'):
        page = site / 'content/extensions/fixture' / view / 'index.md'
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(f'---\ntitle: Version selector fixture\nextension: fixture\nlayout: extension\ntype: extensions\nview: {view}\n---\n## Test documentation\n\nSynthetic versions for selector validation.\n')
    result = subprocess.run(['hugo', '--source', str(site)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return entry


class VariantOrderingTests(unittest.TestCase):
    def test_stable_precedes_testing_and_unstable_within_each_major(self):
        distros = ['unstable', 'sid', 'testing', 'oldstable', 'bookworm', 'stable', 'trixie']
        images = [{'pg': pg, 'distro': distro} for pg in (18, 19) for distro in distros]
        ordered = sorted(images, key=variant_order)
        expected = ['stable', 'trixie', 'bookworm', 'oldstable', 'testing', 'sid', 'unstable']
        self.assertEqual([(i['pg'], i['distro']) for i in ordered],
                         [(pg, distro) for pg in (19, 18) for distro in expected])

    def test_major_precedes_distribution_even_when_new_major_lacks_trixie(self):
        images = [{'pg': 18, 'distro': 'trixie', 'version': 'old'},
                  {'pg': 19, 'distro': 'bookworm', 'version': 'new'},
                  {'pg': 9, 'distro': 'trixie', 'version': 'legacy'}]
        ordered = sorted(images, key=variant_order)
        self.assertEqual([i['pg'] for i in ordered], [19, 18, 9])
        self.assertEqual(ordered[0]['version'], 'new')


@unittest.skipUnless(shutil.which('hugo'), 'Hugo is required for template integration tests')
class ImageSelectionTemplateTests(unittest.TestCase):
    def test_two_majors_have_ordered_options_and_independent_versions_and_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            build_fixture(site)
            soup = BeautifulSoup((site / 'public/extensions/fixture/overview/index.html').read_text(), 'html.parser')
            options = soup.select('#image-choice option')
            self.assertEqual([o['data-variant'] for o in options], [
                'trixie-pg19', 'trixie-pg19', 'bookworm-pg19', 'bookworm-pg19',
                'trixie-pg18', 'trixie-pg18', 'bookworm-pg18', 'bookworm-pg18'])
            for option in options:
                variant, arch = option['data-variant'], option['data-architecture']
                distro, pg = variant.split('-pg')
                self.assertEqual(option.get_text(), f'PG {pg} · {distro.title()} · {arch}')
                panel = soup.select_one(f'#overview .inventory-panel[data-variant="{variant}"][data-architecture="{arch}"]')
                facts = {dt.get_text(): dt.find_next_sibling('dd').get_text(' ', strip=True) for dt in panel.select('dt')}
                version, sql = ('1.8.4', '1.8') if pg == '18' else ('2.0.1', '2.0')
                self.assertEqual(facts['Extension version'], version)
                self.assertTrue(facts['SQL version'].startswith(sql))
                self.assertEqual(facts['Platform'], option.get_text())
                self.assertIn(f'/reports/fixture/{variant}-{arch}.spdx.json', [a['href'] for a in panel.select('a[href]')])
                deps = soup.select_one(f'#dependencies .inventory-panel[data-variant="{variant}"][data-architecture="{arch}"]')
                self.assertEqual(deps.select_one('[data-package]')['data-package'], f'dependency-pg{pg}')
                notice = soup.select_one(f'#licenses .inventory-panel[data-variant="{variant}"][data-architecture="{arch}"]')
                self.assertIn(f'PG {pg} synthetic notice', notice.get_text())
