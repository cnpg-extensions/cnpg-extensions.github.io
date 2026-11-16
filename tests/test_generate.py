import sys, unittest
from unittest.mock import patch
import hcl2
from hcl2.utils import SerializationOptions
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from generate import source_refresh_time, packages, check_digest, readme_html, scan, inspect_image, advisory_url

class MetadataTests(unittest.TestCase):
    def test_license_expressions_and_unknowns_are_not_lost(self):
        result=packages({'packages':[{'name':'library','versionInfo':'2','licenseDeclared':'MIT OR Apache-2.0','licenseConcluded':'LicenseRef-custom','licenseInfoFromFiles':['BSD-3-Clause']},{'name':'unknown'}]})
        self.assertEqual(result[0]['declared'],'MIT OR Apache-2.0')
        self.assertEqual(result[0]['concluded'],'LicenseRef-custom')
        self.assertEqual(result[0]['files'],['BSD-3-Clause'])
        self.assertEqual(result[1]['declared'],'NOASSERTION')
    def test_mismatched_registry_content_is_rejected(self):
        with self.assertRaises(ValueError):check_digest(b'changed','sha256:'+'0'*64)
    def test_readme_links_follow_source_location(self):
        html=readme_html('[Sibling](../../pgextwlist/README.md) ![image](logo.png)\n\n<script>alert(1)</script>', 'org/repo','abc','pgrx/example/README.md',{('org/repo','pgextwlist/README.md'):'extensions/pgextwlist'})
        self.assertIn('../../extensions/pgextwlist/',html)
        self.assertIn('raw.githubusercontent.com/org/repo/abc/pgrx/example/logo.png',html)
        self.assertNotIn('<script>',html)
    def test_metadata_strings_are_unquoted(self):
        parsed=hcl2.loads('metadata = { name = "pg-cron", licenses = ["PostgreSQL"] }',serialization_options=SerializationOptions(strip_string_quotes=True,with_comments=False))
        self.assertEqual(parsed['metadata']['name'],'pg-cron')
        self.assertEqual(parsed['metadata']['licenses'],['PostgreSQL'])
    def test_missing_upstream_sbom_preserves_image_and_version(self):
        index={'manifests':[{'digest':'sha256:platform','platform':{'os':'linux','architecture':'amd64'}}], 'annotations':{'org.opencontainers.image.version':'1.2'}}
        with patch('generate.Registry') as factory:
            factory.return_value.get.side_effect=[index,{'config':{'digest':'sha256:config'}},{'config':{}}]
            result=inspect_image({'name':'example','reference':'ghcr.io/cloudnative-pg/example@sha256:index','distro':'trixie','pg':18},None,{})
        self.assertEqual(result['version'],'1.2')
        self.assertEqual(result['status'],'available')
        self.assertEqual(result['platforms'][0]['status'],'unavailable')
        self.assertIn('not published',result['platforms'][0]['reason'])
        self.assertNotIn('scan',result['platforms'][0])
    def test_advisory_links_use_exact_cargo_versions(self):
        p={'externalRefs':[{'referenceType':'purl','referenceLocator':'pkg:cargo/tokio@1.43.0'}]}
        self.assertEqual(advisory_url(p),'https://deps.dev/cargo/tokio/1.43.0')
    def test_debian_link_uses_source_package_not_binary_name(self):
        p={'name':'libssl3','externalRefs':[{'referenceType':'purl','referenceLocator':'pkg:deb/debian/libssl3@3.0.1?upstream=openssl'}]}
        self.assertEqual(advisory_url(p),'https://security-tracker.debian.org/tracker/source-package/openssl')
        p['externalRefs'][0]['referenceLocator']='pkg:deb/debian/libssl3@3.0.1?upstream=openssl%403.0.1'
        self.assertEqual(advisory_url(p),'https://security-tracker.debian.org/tracker/source-package/openssl')
    def test_debian_source_defaults_to_binary_name_when_omitted(self):
        p={'externalRefs':[{'referenceType':'purl','referenceLocator':'pkg:deb/debian/postgresql-18-age@1.8.0?arch=amd64'}]}
        self.assertEqual(advisory_url(p),'https://security-tracker.debian.org/tracker/source-package/postgresql-18-age')
    def test_unknown_ecosystems_do_not_get_guessed_links(self):
        self.assertEqual(advisory_url({'name':'custom-library'}),'')
    def test_unavailable_database_is_not_clean_scan(self):
        result=scan(Path('unused'),'grype',{'error':'DB unavailable'})
        self.assertEqual(result['status'],'unavailable')
        self.assertNotIn('findings',result)

if __name__=='__main__': unittest.main()

class RefreshTimeTests(unittest.TestCase):
    def test_reuse_keeps_original_refresh_time(self):
        self.assertEqual(source_refresh_time(False, {'source':'abc'}, {'commits':{'source':'abc'}, 'refreshedAt':'old'}, 'new'),'old')
    def test_unknown_or_changed_cache_does_not_claim_freshness(self):
        self.assertIsNone(source_refresh_time(False, {'source':'abc'}, {}, 'new'))
        self.assertIsNone(source_refresh_time(False, {'source':'abc'}, {'commits':{'source':'other'},'refreshedAt':'old'}, 'new'))
    def test_actual_refresh_records_fetch_time(self):
        self.assertEqual(source_refresh_time(True, {'source':'abc'}, {}, 'new'),'new')

class MarkdownAlertTests(unittest.TestCase):
    def test_github_warning_keeps_code_and_links(self):
        from bs4 import BeautifulSoup
        html=readme_html('> [!WARNING]\n> Use `instances: 1`. See [details](#replication).', 'org/repo','abc','extension/README.md',{})
        soup=BeautifulSoup(html,'html.parser')
        warning=soup.select_one('.github-alert-warning')
        self.assertIsNotNone(warning)
        self.assertEqual(warning.select_one('.github-alert-icon').text,'⚠')
        self.assertIn('Warning',warning.select_one('.github-alert-title').text)
        self.assertEqual(warning.code.text,'instances: 1')
        self.assertEqual(warning.a['href'],'#replication')
        self.assertNotIn('[!WARNING]',html)
    def test_ordinary_quote_and_code_example_are_unchanged(self):
        html=readme_html('> Ordinary quote\n\n```\n> [!WARNING]\n```','org/repo','abc','README.md',{})
        self.assertNotIn('github-alert',html)
        self.assertIn('[!WARNING]',html)
