import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from overview_metadata import deb_identity, license_summary, valid_url

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

    def test_only_web_metadata_links(self):
        self.assertEqual(valid_url('javascript:alert(1)'), '')
        self.assertEqual(valid_url('NOASSERTION'), '')
        self.assertEqual(valid_url('https://postgis.net/'), 'https://postgis.net/')
