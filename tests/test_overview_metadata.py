import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from overview_metadata import deb_identity, license_summary, setup_metadata
from scorecard_repositories import valid_url

class OverviewMetadataTests(unittest.TestCase):
    def test_license_expressions_preserved_and_package_not_double_counted(self):
        result = license_summary([
            {'declared': 'MIT OR Apache-2.0', 'concluded': 'MIT OR Apache-2.0'},
            {'declared': 'NOASSERTION', 'files': ['BSD-3-Clause', 'BSD-3-Clause']},
            {'declared': 'NOASSERTION', 'concluded': 'NOASSERTION'},
        ])
        self.assertEqual({x['expression']: x['count'] for x in result['licenses']}, {'MIT OR Apache-2.0': 1, 'BSD-3-Clause': 1})
        self.assertEqual(result['unknownPackages'], 1)

    def test_debian_source_comes_from_purl_not_binary_name(self):
        package = {'externalRefs': [{'referenceType': 'purl', 'referenceLocator': 'pkg:deb/debian/postgresql-18-ogr-fdw@1.0?upstream=pgsql-ogr-fdw&arch=amd64'}]}
        self.assertEqual(deb_identity(package), ('postgresql-18-ogr-fdw', 'pgsql-ogr-fdw'))
        self.assertEqual(deb_identity({'externalRefs': []}), ('', ''))

    def test_versioned_debian_source_qualifier_excludes_version_from_identity(self):
        package = {'externalRefs': [{'referenceType': 'purl', 'referenceLocator':
            'pkg:deb/debian/libcairo2@1.18.4-1%2Bb1?arch=amd64&upstream=cairo%401.18.4-1'}]}
        self.assertEqual(deb_identity(package), ('libcairo2', 'cairo'))

    def test_only_web_metadata_links(self):
        self.assertEqual(valid_url('javascript:alert(1)'), '')
        self.assertEqual(valid_url('NOASSERTION'), '')
        self.assertEqual(valid_url('https://postgis.net/'), 'https://postgis.net/')

    def test_setup_uses_recipe_sql_version_and_preserves_requirements(self):
        meta = {'sql_name': 'pg_cron', 'versions': {'trixie': {'18': {'sql': '2.0'}}},
                'shared_preload_libraries': ['pg_cron'], 'postgresql_parameters': {'cron.database_name': 'app'},
                'required_extensions': ['base-image:btree_gist'], 'create_extension': False}
        setup = setup_metadata(meta, {'distro': 'trixie', 'pg': 18})
        self.assertEqual(setup['sqlVersion'], '2.0')
        self.assertEqual(setup['postgresqlParameters'], {'cron.database_name': 'app'})
        self.assertEqual(setup['requiredExtensions'], ['base-image:btree_gist'])
        self.assertFalse(setup['createExtension'])

    def test_setup_missing_metadata_is_not_an_empty_requirement_list(self):
        setup = setup_metadata({}, {'distro': 'trixie', 'pg': 18})
        self.assertIsNone(setup['sharedPreloadLibraries'])
        self.assertIsNone(setup['sqlVersion'])
        fallback = setup_metadata({'versions': {'trixie': {'18': {'sql': '1.6'}}}}, {'distro': 'trixie', 'pg': 18})
        self.assertEqual(fallback['sqlVersion'], '1.6')
