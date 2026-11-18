"""Employer-specific public browser collectors for enterprise and finance sources."""
import base64
import html
import importlib.util
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode, urlsplit, urljoin

from common import plain_text
from filters import in_india, engineering_title
import fetch_security_portals as shared
from fetch_eightfold_company_jobs import iso


def flight_text(page):
    chunks = []
    for raw in page.locator('script').all_text_contents():
        for match in re.finditer(r'self\.__next_f\.push\((.*)\)', raw):
            try:
                value = json.loads(match.group(1))
                if len(value) > 1 and isinstance(value[1], str):
                    chunks.append(value[1])
            except ValueError:
                continue
    return "".join(chunks)


def json_after(text, key):
    for match in re.finditer(r'"' + re.escape(key) + r'"\s*:\s*', text):
        try:
            value, _ = json.JSONDecoder().raw_decode(text[match.end():])
            yield value
        except ValueError:
            continue


def lever_jobs(browser, company, board):
    items, seen, offset = [], set(), 0
    for _ in range(100):
        data = browser.json(f"https://api.lever.co/v0/postings/{board}?mode=json&limit=100&skip={offset}")
        if not isinstance(data, list):
            raise RuntimeError("Lever feed response shape changed")
        for item in data:
            if not item.get('id') or item['id'] in seen:
                raise RuntimeError("Lever repeated/missing job ID")
            seen.add(item['id']); items.append(item)
        if len(data) < 100:
            break
        offset += len(data)
    else:
        raise RuntimeError("Lever pagination limit reached")
    jobs = []
    for item in items:
        categories = item.get('categories') or {}
        locations = [categories.get('location') or '', *(categories.get('allLocations') or [])]
        if not in_india({'locations': locations}) or not engineering_title({'title': item.get('text')}):
            continue
        if shared.department_excluded([categories.get('department') or '', categories.get('team') or '']):
            continue
        sections = [item.get('description') or '']
        sections += ['<h2>' + html.escape(str(s.get('text') or '')) + '</h2>' + str(s.get('content') or '') for s in item.get('lists') or []]
        sections.append(item.get('additional') or '')
        description = '\n'.join(filter(None, sections))
        evidence = re.search(r'\b' + re.escape(company) + r'\b', plain_text(description), re.I)
        if company in {'Gojek', 'Dream11'} and not evidence:
            continue
        if not plain_text(description) or not item.get('hostedUrl'):
            raise RuntimeError("Lever selected posting lacks full description/application URL")
        jobs.append({'id': item['id'], 'title': item['text'], 'company': company,
                     'location': ' | '.join(filter(None, locations)), 'locations': locations,
                     'department': categories.get('team'), 'source_categories': categories,
                     'application_url': item['hostedUrl'], 'posted_date': item.get('datePosted') or item.get('publishedAt'),
                     'source_created_timestamp': item.get('createdAt'),
                     'brand_evidence': plain_text(description)[max(0,evidence.start()-40):evidence.end()+80] if evidence else None,
                     'jobDescriptionHtml': description, 'jobDescriptionText': plain_text(description)})
    return jobs, {'global_results': len(items), 'complete': True,
                  'date_limitation': 'Lever createdAt is retained separately and is not treated as a publication date'}


def deel_jobs(browser, company, url):
    browser.goto(url)
    text = flight_text(browser.page)
    listings = next((v for v in json_after(text, 'jobs') if isinstance(v, list) and v and 'attributes' in v[0]), None)
    counts = list(json_after(text, 'jobsCount'))
    if listings is None or not counts or len(listings) != counts[0]:
        raise RuntimeError("Deel's embedded listing/count could not be reconciled")
    jobs = []
    for row in listings:
        item = row['attributes']
        locations = [v.get('location') for v in item.get('locations_list', [])]
        if not item.get('is_listed') or not in_india({'locations': locations}) or not engineering_title(item):
            continue
        if shared.department_excluded([item.get('department_name') or '', item.get('team_name') or '']):
            continue
        browser.goto(item['external_link'].replace('/application','/overview'))
        schemas = shared.json_ld_jobs(browser.page)
        detail = schemas[0] if len(schemas)==1 else {}
        if detail.get('title') and detail['title'].casefold()!=item['title'].casefold():
            raise RuntimeError('Deel detail title does not match selected role')
        detail_text = flight_text(browser.page)
        description = detail.get('description') or next((v for v in json_after(detail_text, 'full_job_description') if isinstance(v,str) and plain_text(v)), '')
        if not description:
            rich = browser.page.locator('main .prose, main [class*="rich-text"], main .rich-text')
            if rich.count():
                description = '\n'.join(rich.all_inner_texts())
        if not plain_text(description):
            raise RuntimeError("Deel selected role lacks its full description")
        jobs.append({'id': item['ashby_id'], 'title': item['title'], 'company': company,
                     'department': item.get('department_name'), 'locations': locations, 'location': ' | '.join(locations),
                     'application_url': item['external_link'], 'posted_date': detail.get('datePosted') or item.get('ashby_published_date'),
                     'updated_date': item.get('ashby_updated_at'), 'jobDescriptionHtml': description,
                     'jobDescriptionText': plain_text(description)})
    return jobs, {'global_results': len(listings), 'complete': True}


def turbohire_jobs(browser, company, url):
    with browser.page.expect_response(lambda r: '/api/careerpagev2/filteredjobs?' in r.url, timeout=browser.timeout*1000) as pending:
        browser.goto(url)
    response = pending.value
    if not response.ok:
        raise RuntimeError(f"TurboHire native feed HTTP {response.status}")
    data = response.json()
    if not isinstance(data.get('Result'), list) or len(data['Result']) != data.get('Total'):
        raise RuntimeError("TurboHire feed is missing, paginated or incomplete")
    jobs = []
    for item in data['Result']:
        locations = item.get('Location') or []
        if isinstance(locations,str): locations=json.loads(locations)
        addresses = [v.get('Address','') for v in locations]
        if not in_india({'locations': addresses}) or not engineering_title({'title':item.get('JobTitle')}):continue
        if shared.department_excluded([item.get('Department') or '']):continue
        description = item.get('JobDescV2') or ''
        if not plain_text(description) or not item.get('JobIdObfuscated'):raise RuntimeError('TurboHire full posting missing')
        origin = f"https://{urlsplit(url).netloc}"
        jobs.append({'id':item['JobId'],'title':item['JobTitle'],'company':company,'department':item.get('Department'),
                     'locations':addresses,'location':' | '.join(addresses),'country':'India',
                     'application_url':origin+'/job/publicjobs/'+item['JobIdObfuscated'],
                     'posted_date':item.get('PublishedDate'),'updated_date':item.get('UpdatedDate'),
                     'jobDescriptionHtml':description,'jobDescriptionText':plain_text(description)})
    return jobs, {'global_results':data['Total'],'complete':True}


def icims_jobs(browser, company, url):
    jobs, seen, scanned, total = [], set(), 0, 0
    for page in range(1, 101):
        data = browser.json('https://careers.amd.com/api/jobs?' + urlencode({'country':'India','categories':'Engineering',
            'page':page,'sortBy':'posted_date','descending':'true','internal':'false'}))
        if not isinstance(data.get('jobs'),list) or 'totalCount' not in data:raise RuntimeError('AMD API shape changed')
        total = max(total,int(data['totalCount']))
        for wrapper in data['jobs']:
            item=wrapper.get('data') or {}; ident=item.get('req_id') or item.get('slug')
            if not ident or ident in seen:raise RuntimeError('AMD repeated/missing ID')
            seen.add(ident)
            if not engineering_title(item) or not in_india(item):continue
            desc=item.get('description') or ''
            if not plain_text(desc):raise RuntimeError('AMD full description missing')
            jobs.append({'id':str(ident),'title':item['title'],'company':company,'department':'Engineering',
                         'location':item.get('location_name') or ', '.join(str(item.get(k) or '') for k in ['city','state','country']),
                         'locations':item.get('locations') or [],'country':'India','application_url':f'https://careers.amd.com/careers-home/jobs/{ident}?lang=en-us',
                         'posted_date':item.get('posted_date') or item.get('postedDate'),
                         'jobDescriptionHtml':desc,'jobDescriptionText':plain_text(desc)})
        scanned += len(data['jobs'])
        if scanned >= total:return jobs,{'global_india_engineering_results':total,'complete':True}
        if not data['jobs']:raise RuntimeError('AMD premature pagination end')
    raise RuntimeError('AMD page limit reached')


def clari_jobs(browser, company, board):
    jobs, metadata = shared.greenhouse_jobs(browser, company, board)
    results=[]
    for job in jobs:
        match=re.search(r'\bClari\b',job['jobDescriptionText'],re.I)
        if match:
            job['employer_name']='Salesloft / Clari'
            job['brand_evidence']=job['jobDescriptionText'][max(0,match.start()-40):match.end()+100]
            results.append(job)
    return results,{**metadata,'scope':'Successor Salesloft board with explicit Clari brand evidence'}


def oracle_india_jobs(browser, company, source):
    origin,site=source.split('|')
    base=origin+'/hcmRestApi/resources/latest/'
    def listing(offset,location=None,expand='requisitionList'):
        finder=f'findReqs;siteNumber={site},limit=100,offset={offset},sortBy=POSTING_DATES_DESC'
        if location:finder+=f',selectedLocationsFacet={location}'
        data=browser.json(base+'recruitingCEJobRequisitions?'+urlencode({'onlyData':'true','expand':expand,'finder':finder}))
        if not data.get('items') or not isinstance(data['items'][0].get('requisitionList'),list):raise RuntimeError('Oracle listing shape changed')
        return data['items'][0]
    discovery=listing(0,expand='all')
    india=next((v['Id'] for v in discovery.get('locationsFacet',[]) if v.get('Name','').casefold()=='india'),None)
    if india is None:raise RuntimeError('Oracle India country facet was not discoverable; not a verified empty result')
    jobs,seen,offset,total=[],set(),0,0
    for _ in range(100):
        data=listing(offset,india)
        if str(data.get('SelectedLocationsFacet'))!=str(india):raise RuntimeError('Oracle did not confirm India facet')
        total=max(total,int(data['TotalJobsCount']))
        for item in data['requisitionList']:
            ident=str(item['Id'])
            if ident in seen:raise RuntimeError('Oracle repeated a job across pages')
            seen.add(ident)
            if not engineering_title({'title':item.get('Title')}):continue
            detail=browser.json(base+'recruitingCEJobRequisitionDetails?'+urlencode({'onlyData':'true','expand':'all','finder':f'ById;Id={ident},siteNumber={site}'}))
            values=detail.get('items') or []
            if not values or str(values[0].get('Id'))!=ident:raise RuntimeError('Oracle detail identity mismatch')
            job=shared.oracle.normalize(values[0],company,origin,site)
            if job:jobs.append(job)
            time.sleep(0.2)
        offset+=len(data['requisitionList'])
        if offset>=total:return jobs,{'global_results':discovery['TotalJobsCount'],'india_results':total,'india_facet_id':india,'complete':True}
        if not data['requisitionList']:raise RuntimeError('Oracle pagination ended before count')
    raise RuntimeError('Oracle page limit reached')


def structured_india(detail):
    locations=detail.get('jobLocation') or []
    if isinstance(locations,dict):locations=[locations]
    for entry in locations:
        address=entry.get('address') or {}
        if isinstance(address,dict):
            country=address.get('addressCountry') or ''
            if isinstance(country,dict):country=country.get('name','')
            if str(country).casefold() in {'in','india'}:return True
    return in_india({'jobLocation':locations})


def talentbrew_jobs(browser, company, url):
    from playwright.sync_api import expect
    page=browser.page;browser.goto(url)
    # Country handlers and the dismissible notice are attached after initial SSR.
    page.wait_for_timeout(2500)
    reject=page.get_by_role('button',name='Reject All',exact=True)
    if reject.count() and reject.is_visible():reject.click()
    notice_reject=page.locator('#system-ialert-reject-button')
    if notice_reject.count() and notice_reject.is_visible():notice_reject.click()
    country=page.locator('input.filter-checkbox[data-id="1269750"][data-facet-type="2"]')
    country.wait_for(state='attached')
    toggle=page.locator('#country-toggle')
    if toggle.count():
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        for _ in range(3):
            if toggle.get_attribute('aria-expanded')=='true':break
            toggle.click()
            try:
                expect(toggle).to_have_attribute('aria-expanded','true',timeout=2000)
                break
            except (PlaywrightTimeout,AssertionError):
                # SSR controls can be clicked before their deferred handlers attach.
                continue
    expected_count=int(country.get_attribute('data-count'))
    page.locator('label[for="'+country.get_attribute('id')+'"]').click()
    apply_filter=page.get_by_role('button',name='Go',exact=True)
    if apply_filter.count() and apply_filter.is_visible():apply_filter.click()
    expect(country).to_be_checked()
    count_attribute='data-total-job-results' if page.locator('#search-results').get_attribute('data-total-job-results') is not None else 'data-total-results'
    expect(page.locator('#search-results')).to_have_attribute(count_attribute,str(expected_count),timeout=browser.timeout*1000)
    seen=set();candidates=[];total=None
    for _ in range(100):
        root=page.locator('#search-results')
        if total is None:total=int(root.get_attribute('data-total-job-results') or root.get_attribute('data-total-results'))
        links=page.locator('#search-results-list a[href*="/job/"]').evaluate_all('els=>els.map(e=>({url:e.href,title:e.innerText.trim()}))')
        links=list({v['url']:v for v in links}.values())
        previous_seen=len(seen)
        for item in links:
            if item['url'] in seen:continue
            seen.add(item['url'])
            if engineering_title(item):candidates.append(item)
        print(f'{company}: collected {len(seen)}/{total} India listings',flush=True)
        if len(seen)>=total:break
        if len(seen)==previous_seen:raise RuntimeError('TalentBrew pagination did not advance')
        more=page.get_by_role('button',name='View More Jobs',exact=True)
        if more.count() and more.is_visible():
            before_count=page.locator('#search-results-list a[href*="/job/"]').count()
            more.click()
            page.locator('#search-results-list a[href*="/job/"]').nth(before_count).wait_for(state='attached')
            continue
        next_link=page.get_by_role('button',name='Next',exact=True).first
        if not next_link.count():next_link=page.locator('a.next:not(.disabled):visible').first
        if not next_link.count():raise RuntimeError('TalentBrew pagination incomplete')
        previous=links[0]['url'] if links else ''
        previous_href=page.locator('#search-results-list a[href*="/job/"]').first.get_attribute('href')
        next_link.click()
        expect(page.locator('#search-results-list a[href*="/job/"]').first).not_to_have_attribute('href',previous_href)
    else:raise RuntimeError('TalentBrew page limit reached')
    if len(seen)!=total:raise RuntimeError('TalentBrew result count mismatch')
    jobs=[]
    for item in candidates:
        browser.goto(item['url']);details=shared.json_ld_jobs(page)
        if len(details)!=1:raise RuntimeError('TalentBrew full JobPosting missing or ambiguous')
        detail=details[0]
        if not structured_india(detail):continue
        description=detail.get('description') or ''
        if not plain_text(description):raise RuntimeError('TalentBrew full description missing')
        ident=detail.get('identifier') or item['url'].rstrip('/').rsplit('/',1)[-1]
        if isinstance(ident,dict):ident=ident.get('value')
        location=detail.get('jobLocation') or []
        jobs.append({'id':str(ident),'title':detail.get('title') or item['title'],'company':company,
                     'jobLocation':location,'location':'India','country':'India','application_url':item['url'],
                     'posted_date':detail.get('datePosted'),'jobDescriptionHtml':description,'jobDescriptionText':plain_text(description)})
    return jobs,{'india_results':total,'complete':True}


def goldman_jobs(browser, company, url):
    path=Path(__file__).resolve().parents[1]/'career portal scripts/fetch_goldman_sachs_jobs.py'
    spec=importlib.util.spec_from_file_location('goldman_shared_queries',path);adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
    browser.goto(url)
    def gql(operation,variables,query):
        result=browser.page.evaluate('''async ({endpoint,payload,timeout})=>{
            const r=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},
                body:JSON.stringify(payload),signal:AbortSignal.timeout(timeout*1000)});
            return {status:r.status,body:await r.text(),retry:r.headers.get('retry-after')};}''',
            {'endpoint':adapter.ENDPOINT,'payload':{'operationName':operation,'variables':variables,'query':query},'timeout':browser.timeout})
        if result['status']!=200:raise RuntimeError(f"Goldman API HTTP {result['status']}; Retry-After={result['retry'] or 'unspecified'}")
        payload=json.loads(result['body'])
        if payload.get('errors'):raise RuntimeError('Goldman GraphQL response errors')
        return payload['data']
    filters=[{'filterCategoryType':'LOCATION','filters':[{'filter':'India','subFilters':[]}]}]
    summaries=[];seen=set();total=0
    for number in range(100):
        params={'page':{'pageSize':20,'pageNumber':number},'sort':{'sortStrategy':'RELEVANCE','sortOrder':'DESC'},
                'filters':filters,'experiences':['EARLY_CAREER','PROFESSIONAL'],'searchTerm':''}
        data=gql('GetRoles',{'searchQueryInput':params},adapter.SEARCH)['roleSearch'];total=int(data['totalCount'])
        for item in data.get('items',[]):
            ident=str((item.get('externalSource') or {}).get('sourceId') or '')
            if not ident or ident in seen:raise RuntimeError('Goldman repeated/missing role identity')
            seen.add(ident)
            if in_india({'locations':item.get('locations')}) and engineering_title({'title':item.get('jobTitle')}):summaries.append((ident,item))
        if len(seen)>=total:break
        if not data.get('items'):raise RuntimeError('Goldman pagination incomplete')
    else:raise RuntimeError('Goldman page limit reached')
    jobs=[]
    for ident,item in summaries:
        detail=gql('GetRoleById',{'externalSourceId':ident,'externalSourceFetch':True},adapter.DETAIL)['role']
        if not in_india({'locations':detail.get('locations')}):continue
        description=detail.get('descriptionHtml') or ''
        if not plain_text(description):raise RuntimeError('Goldman full description missing')
        locations=[', '.join(str(v.get(k) or '') for k in ['city','state','country']) for v in detail.get('locations',[])]
        jobs.append({'id':ident,'title':detail.get('jobTitle') or item['jobTitle'],'company':company,
                     'location':' | '.join(locations),'department':detail.get('jobFunction'),
                     'application_url':(detail.get('externalSource') or {}).get('externalApplicationUrl') or 'https://higher.gs.com/roles/'+ident,
                     'posted_date':None,'jobDescriptionHtml':description,'jobDescriptionText':plain_text(description)})
    return jobs,{'india_results':total,'complete':True,'date_limitation':'Public Higher query exposes no publication field; source relevance order retained for undated roles'}


def sharechat_jobs(browser, company, url):
    data=browser.json('https://sharechat.com/api/careersList')
    groups=(data.get('data') or {}).get('careersList')
    if not isinstance(groups,list):raise RuntimeError('ShareChat listing shape changed')
    items=[j for g in groups for j in g.get('data',[])];jobs=[]
    for item in items:
        locations=item.get('officeLocationNames') or []
        if not in_india({'locations':locations}) or not engineering_title({'title':item.get('requisitionTitle')}):continue
        if shared.department_excluded([item.get('orgUnitName') or '']):continue
        parameter={'pageType':'jd','cvSource':'careers','reqId':item['requisitionId'],'requester':{'id':'','code':'','name':''},'page':'careers','bufilter':-1,'customFields':{}}
        link='https://sharechat.mynexthire.com/employer/jobs?'+urlencode({'src':'careers','p':base64.b64encode(json.dumps(parameter,separators=(',',':')).encode()).decode()})
        with browser.page.expect_response(lambda r:'/careers/requisition/object' in r.url,timeout=browser.timeout*1000) as pending:browser.goto(link)
        response=pending.value
        if not response.ok:raise RuntimeError(f'MyNextHire full detail HTTP {response.status}')
        payload=response.json();detail=(payload.get('data') or {}).get('reqDetailsBO') or {}
        if str(detail.get('reqId'))!=str(item['requisitionId']):raise RuntimeError('ShareChat detail identity mismatch')
        description=detail.get('jdDisplay') or ''
        if not plain_text(description):raise RuntimeError('ShareChat full description missing')
        jobs.append({'id':str(item['requisitionId']),'title':item['requisitionTitle'],'company':company,
                     'location':' | '.join(locations),'locations':locations,'department':item.get('orgUnitName'),
                     'application_url':link,'posted_date':None,'source_created_timestamp':item.get('createdDate'),
                     'source_approved_timestamp':item.get('approvedDate'),'jobDescriptionHtml':description,'jobDescriptionText':plain_text(description)})
    return jobs,{'global_results':len(items),'complete':True,'date_limitation':'Creation and approval dates retained separately, not promoted to publication dates'}


def cards_jobs(browser, company, url):
    browser.goto(url)
    pattern='/careers/open-positions/jobs/' if company=='Opendoor' else '/careers/'
    links=browser.page.locator('a[href]').evaluate_all('els=>els.map(e=>({url:e.href,text:e.innerText.trim()}))')
    links=list({v['url']:v for v in links if pattern in v['url'] and urlsplit(v['url']).netloc==urlsplit(url).netloc and len(urlsplit(v['url']).path.rstrip('/').split('/'))>len(urlsplit(url).path.rstrip('/').split('/'))}.values())
    if not links:raise RuntimeError(f'{company} current job cards missing')
    jobs=[]
    for item in links:
        parts=[s.strip() for s in item['text'].splitlines() if s.strip()]
        if len(parts)<2:raise RuntimeError('Job card location/title unavailable')
        title=parts[0];location=' | '.join(parts[1:])
        if not engineering_title({'title':title}) or not in_india({'location':location}):continue
        browser.goto(item['url']);details=shared.json_ld_jobs(browser.page)
        detail=details[0] if len(details)==1 else {}
        description=detail.get('description') or ''
        if not description:
            rich=browser.page.locator('main .w-richtext, article .w-richtext, main article')
            if rich.count():description='\n'.join(rich.all_inner_texts())
        if not plain_text(description):raise RuntimeError('Selected native role lacks a full description')
        jobs.append({'id':item['url'].rstrip('/').rsplit('/',1)[-1],'title':title,'company':company,
                     'location':location,'application_url':item['url'],'posted_date':detail.get('datePosted'),
                     'jobDescriptionHtml':description,'jobDescriptionText':plain_text(description)})
    return jobs,{'global_results':len(links),'complete':True}


def collect_enterprise(browser, company, kind, source):
    if kind=='enterprise_pcsx':
        origin,domain=source.split('|')
        return shared.twilio_jobs(browser,company,origin,domain)
    functions={'enterprise_lever':lever_jobs,'enterprise_deel':deel_jobs,'enterprise_turbohire':turbohire_jobs,
               'enterprise_icims':icims_jobs,'enterprise_clari':clari_jobs,'enterprise_oracle':oracle_india_jobs,
               'enterprise_talentbrew':talentbrew_jobs,'enterprise_goldman':goldman_jobs,
               'enterprise_sharechat':sharechat_jobs,'enterprise_cards':cards_jobs}
    return functions[kind](browser,company,source)
