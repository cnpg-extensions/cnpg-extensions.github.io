import sys
import unittest
from pathlib import Path
from bs4 import BeautifulSoup
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from guide_layout import getting_started

class GuideLayoutTests(unittest.TestCase):
    def test_imported_alerts_and_maintenance_are_preserved_in_order(self):
        html='<h2 id="requirements">Requirements</h2><ul><li>Runtime requirement</li></ul><h3>Alerts</h3><pre>metric == 1</pre><h3>Maintenance</h3><details><summary>RBAC</summary><pre>kind: ClusterRole</pre></details><p>Rollout caveat</p>'
        soup=BeautifulSoup(getting_started(html),'html.parser')
        self.assertIn('Runtime requirement',soup.select_one('.guide-prerequisites').text)
        self.assertFalse(soup.select('details.guide-disclosure'))
        self.assertIsNone(soup.find('pre',string='metric == 1').find_parent('details'))
        self.assertEqual(soup.find('details').summary.text, 'RBAC')
        self.assertIn('kind: ClusterRole',soup.find('details').text)
        self.assertIn('Rollout caveat',soup.text)
        self.assertEqual([pre.text for pre in soup.find_all('pre')], ['metric == 1', 'kind: ClusterRole'])
        self.assertEqual(soup.select_one('#schedule-maintenance').name, 'h2')

    def test_source_structure_changes_require_review(self):
        with self.assertRaises(ValueError):
            getting_started('<h2>Requirements</h2><h3>Changed setup</h3>')
