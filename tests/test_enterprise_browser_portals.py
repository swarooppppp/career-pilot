"""Scope, source freshness and data integrity for the enterprise/finance batch."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'local_career_portals'))
import fetch_enterprise_portals as enterprise
import fetch_security_portals as shared
from filters import engineering_title


class EnterpriseTests(unittest.TestCase):
    def test_sde_titles_are_engineering_with_sales_support_exclusions(self):
        for title in ['SDE III - Mobile Security','SDE-II','SDE3','SDEIV']:
            self.assertTrue(engineering_title({'title':title}))
        self.assertFalse(engineering_title({'title':'Technical Support Engineer'}))
        self.assertFalse(engineering_title({'title':'Sales SDE'}))
    def native(self,data):
        browser=Mock(timeout=30);browser.page=MagicMock()
        response=Mock(ok=True);response.json.return_value=data
        browser.page.expect_response.return_value.__enter__.return_value.value=response
        return browser

    def lever_item(self,title='Software Engineer',location='Bangalore',description='Build Gojek services.'):
        return {'id':'1','text':title,'categories':{'location':location,'team':'Engineering'},
                'description':description,'lists':[{'text':'Requirements','content':'<ul><li>Python.</li></ul>'}],
                'additional':'Benefits section.','hostedUrl':'https://jobs.lever.co/GoToGroup/1','createdAt':12345}

    def test_gojek_brand_evidence_and_full_sections(self):
        browser=Mock();browser.json.return_value=[self.lever_item()]
        jobs,_=enterprise.lever_jobs(browser,'Gojek','GoToGroup')
        self.assertIn('Requirements',jobs[0]['jobDescriptionText'])
        self.assertIn('Benefits',jobs[0]['jobDescriptionText'])
        self.assertIn('Gojek',jobs[0]['brand_evidence'])
        self.assertIsNone(jobs[0]['posted_date'])
        self.assertEqual(jobs[0]['source_created_timestamp'],12345)

    def test_group_board_does_not_adopt_unrelated_brand(self):
        browser=Mock();browser.json.return_value=[self.lever_item(description='Build GoTo Financial services.')]
        self.assertEqual(enterprise.lever_jobs(browser,'Gojek','GoToGroup')[0],[])

    def test_lever_foreign_remote_and_support_titles_excluded(self):
        browser=Mock();browser.json.return_value=[self.lever_item(location='Remote - US'),self.lever_item(title='Technical Support Engineer')]
        browser.json.return_value[1]['id']='2'
        self.assertEqual(enterprise.lever_jobs(browser,'Gojek','GoToGroup')[0],[])

    def test_navi_incomplete_feed_is_failure(self):
        browser=self.native({'Total':10,'Result':[]})
        with self.assertRaisesRegex(RuntimeError,'incomplete'):
            enterprise.turbohire_jobs(browser,'Navi','https://navi.turbohire.co/dashboardv2')

    def test_navi_full_description_and_posting_date(self):
        item={'JobId':'1','JobIdObfuscated':'encoded%2Ftoken','JobTitle':'Software Engineer','Department':'Engineering',
              'Location':json.dumps([{'Address':'Bengaluru, India'}]),'JobDescV2':'<p>Full role.</p>','PublishedDate':'2026-11-18T00:00:00Z'}
        jobs,_=enterprise.turbohire_jobs(self.native({'Total':1,'Result':[item]}),'Navi','https://navi.turbohire.co/dashboardv2')
        self.assertTrue(jobs[0]['application_url'].endswith('encoded%2Ftoken'))
        self.assertEqual(jobs[0]['posted_date'],'2026-11-18T00:00:00Z')

    def test_amd_listing_has_full_details_and_does_not_promote_creation(self):
        browser=Mock();browser.json.return_value={'totalCount':1,'jobs':[{'data':{'req_id':'123','title':'Software Engineer',
            'country':'India','city':'Bangalore','description':'<p>Full description.</p>','posted_date':'2026-11-18', 'create_date':'2026-11-17'}}]}
        jobs,_=enterprise.icims_jobs(browser,'AMD','https://careers.amd.com/jobs')
        self.assertEqual(jobs[0]['posted_date'],'2026-11-18')
        self.assertEqual(jobs[0]['jobDescriptionText'],'Full description.')

    def test_oracle_missing_india_facet_does_not_become_empty_success(self):
        browser=Mock();browser.json.return_value={'items':[{'requisitionList':[],'TotalJobsCount':10,'locationsFacet':[{'Id':1,'Name':'United States'}]}]}
        with self.assertRaisesRegex(RuntimeError,'not discoverable'):
            enterprise.oracle_india_jobs(browser,'JPMorgan Chase','https://example.org|CX_1001')

    def test_oracle_unconfirmed_india_facet_fails(self):
        browser=Mock();browser.json.side_effect=[{'items':[{'requisitionList':[],'TotalJobsCount':1,'locationsFacet':[{'Id':2,'Name':'India'}]}]},
            {'items':[{'requisitionList':[],'TotalJobsCount':0,'SelectedLocationsFacet':None}]}]
        with self.assertRaisesRegex(RuntimeError,'did not confirm'):
            enterprise.oracle_india_jobs(browser,'American Express','https://example.org|CX_1')

    def test_clari_successor_requires_brand_evidence(self):
        with patch.object(shared,'greenhouse_jobs',return_value=([
            {'id':'1','jobDescriptionText':'Build Clari infrastructure.'},
            {'id':'2','jobDescriptionText':'An unrelated Salesloft-only vacancy.'}],{'complete':True})):
            jobs,_=enterprise.clari_jobs(Mock(),'Clari','salesloft')
        self.assertEqual([j['id'] for j in jobs],['1'])
        self.assertEqual(jobs[0]['employer_name'],'Salesloft / Clari')

    def test_structured_country_code_supported_without_description_inference(self):
        self.assertTrue(enterprise.structured_india({'jobLocation':{'address':{'addressCountry':'IN'}}}))
        self.assertFalse(enterprise.structured_india({'description':'Work with India teams','jobLocation':{'address':{'addressCountry':'US'}}}))

    def test_netapp_uses_actual_job_site_not_disabled_pcsx(self):
        self.assertEqual(shared.SOURCES['netapp'][1],'enterprise_talentbrew')
        self.assertEqual(shared.SOURCES['autodesk'][1],'enterprise_pcsx')

    def clinch_browser(self,rows,total,next_url=None):
        browser=Mock();page=Mock();browser.page=page
        row_locator=Mock();row_locator.evaluate_all.side_effect=rows
        counts=Mock();counts.first.inner_text.return_value=f'Displaying jobs of {total} in total'
        next_link=Mock();next_link.first.count.return_value=1 if next_url else 0
        next_link.first.get_attribute.return_value=next_url
        def locator(selector):
            if selector.startswith('input[name="country_codes'):
                return Mock(count=Mock(return_value=1),is_checked=Mock(return_value=True))
            if selector.startswith('tr['):return row_locator
            if selector=='.table-counts':return counts
            if selector.startswith('li.next'):return next_link
            raise AssertionError(selector)
        page.locator.side_effect=locator
        return browser

    def test_duplicate_clinch_records_are_removed_without_losing_count_check(self):
        row={'url':'https://careers.example/jobs/1','title':'Software Engineer','location':'India','department':'Engineering'}
        browser=self.clinch_browser([[row,row]],2)
        schema={'title':'Software Engineer','description':'<p>Full role.</p>','jobLocation':{'address':{'addressCountry':'India'}},'datePosted':'2026-11-18'}
        with patch.object(shared,'json_ld_jobs',return_value=[schema]):
            jobs,metadata=shared.rapid7_jobs(browser,'Toast','https://careers.example/jobs/search')
        self.assertEqual(len(jobs),1)
        self.assertEqual(metadata['duplicate_listings_removed'],1)

    def test_repeated_whole_clinch_page_still_fails(self):
        row={'url':'https://careers.example/jobs/1','title':'Software Engineer','location':'India','department':'Engineering'}
        browser=self.clinch_browser([[row],[row]],2,'https://careers.example/jobs/search?page=2')
        with self.assertRaisesRegex(RuntimeError,'repeated listing page'):
            shared.rapid7_jobs(browser,'Toast','https://careers.example/jobs/search')


if __name__=='__main__':unittest.main()
