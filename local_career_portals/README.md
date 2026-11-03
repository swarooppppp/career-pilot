# Local career portal collection

This collection runs independently of the application. It reuses existing adapters in place and writes snapshots under `local_career_portals/data/`. The application database, `.env` switches, and installed scheduling are unchanged. `companies.json` is this collection's independent source configuration.

## Engineering and India audit

Every runnable entry has an explicit `filter_policy`. The runner validates India against location fields, structured offices, country names, and recognized Indian city names; it never uses incidental description mentions to infer location. Automattic also accepts an explicit role-specific worldwide hiring statement, retained as evidence in each accepted record. Unknown locations are excluded. Existing narrower city and other search constraints are retained unless noted below.

| Company | Engineering selection | India selection |
| --- | --- | --- |
| Databricks | Native Engineering department checked by adapter | India location checked by adapter |
| Rubrik | Exact Engineering department | Explicit `--location India` before limiting |
| Uber | Native `team=Engineer` | Native `countries=India`, plus output location check |
| Google | Software Engineer search plus conservative engineering-title check | Native India location plus output check |
| Atlassian | Native Engineering team checked by adapter | India location checked by adapter |
| LinkedIn | Engineering keyword plus conservative engineering-title check | India geography, employer 1337, past 24 hours |
| Stripe | Software Engineer search plus conservative engineering-title check | Native India search plus output location check |
| Rippling | Native Algolia Engineering department facet | Bangalore, India facet plus output check |
| Glean | Exact Engineering board department, excluding Sales Engineering | India board location before limiting |
| Abnormal AI | Actual Engineering category membership from the portal | Exact supplied Hybrid - Bangalore, India location |
| Microsoft | Verified native Software Engineering profession and Mid-Level/Senior/Entry facets | India search, remote included, relocation excluded, plus output location check |
| Amazon | Native software-development category | Country IND, existing Bengaluru/Hyderabad restrictions, plus output check |
| Airbnb | Public board Software Engineering and Engineering & Technology departments | Structured India location/office check before limiting |
| Cloudflare | Exact Career Site Department metadata = Engineering | Exact Job Posting Location metadata = Bengaluru, India |
| MongoDB | Actual native Engineering checkbox, verified after hydration | OR selection of India and recognized Indian city facets; structured office check |
| Intuit | Saved category facets plus conservative engineering-title check | Adapter `--country India` plus output check |
| Postman | Exact Engineering department | Existing Bangalore/Hyderabad filter plus output check |
| Salesforce | Native Software Engineering team checked by adapter | Native India country checked by adapter |

For sources without a verified department facet, title matching includes engineers, developers, architects, SRE, SDET, DevOps, and MTS/Member of Technical Staff, and excludes sales, solutions engineering, customer success, recruiting, and technical support. This is a conservative approximation, not a claim of exact department equivalence; it can exclude relevant roles. No description keyword matching is used by that final check.

MongoDB's India checkbox alone excludes city-labeled jobs. Its adapter selects the Indian cities as well. Its visible Engineering grouping differs from Greenhouse department names, so headless Chromium applies the real UI filter and collects all paginated matching IDs. The full descriptions are then joined from the public Greenhouse feed. The adapter waits for filter handlers and verifies the Engineering result count changes before collecting anything. Abnormal AI uses the portal's own category IDs; Cloudflare uses career-site metadata, since its main `location` field often says only Hybrid or In-Office.

Snowflake remains pending. Confluent is deferred. IBM's adapter is retained but excluded from runs as `unconfirmed` after the user clarified that IBM was not the intended company; no IBM URL is presented as a Confluent source.

## Ordering

Recent-first selection is requested where the source supports it. Rubrik and the three new board adapters sort first-publication dates before limiting, falling back to update timestamps. Databricks and Atlassian sort portal update dates before limiting. Google, Microsoft, Amazon, and LinkedIn request native recent-first ordering. Other results are sorted by available dates within the fetched subset; undated jobs preserve portal order. An update date is not necessarily a publication date.

The final Engineering/India guard runs after existing adapters return their bounded results. It may produce fewer jobs than requested; it does not fetch more pages to compensate for exclusions or guarantee that a subset contains the entire portal's newest matching jobs.

## Run manually

From the repository root:

```sh
.venv/bin/python local_career_portals/run.py --list
.venv/bin/python local_career_portals/run.py --dry-run
.venv/bin/python local_career_portals/run.py abnormal_ai cloudflare mongodb --max-jobs 50
.venv/bin/python local_career_portals/run.py rubrik glean --max-jobs 50
```

Omitting company arguments runs all 96 implemented/reused company configurations. The nine previously failed validations have now passed through headless Chrome. Missing, deferred, unconfirmed, and unavailable-source companies are excluded. Defaults are 50 jobs and 600 seconds per source. Outputs are atomic; source failures preserve previous snapshots and produce a nonzero exit status. Partial LinkedIn metadata is retained. Concurrent runs are not supported yet.

Headless is the browser default. Existing headed Uber automation and hiding support remain under `automation/`; this runner does not yet automatically retry headed or minimize windows. Cron installation, overlap locking, and unattended browser cleanup integration remain pending. HTTP rate limits and verification challenges remain possible. LinkedIn makes zero immediate 429 retries in this collection rather than spending many minutes backing off.

## Validation

On 31 October 2026, complete filtered live runs returned 10 Abnormal AI jobs, 6 Cloudflare jobs, and 16 MongoDB jobs, including full descriptions. Corrected live Rubrik and Glean runs returned 8 and 4 jobs respectively. Rubrik uses structured offices and Indian city names because its main locations do not always contain the word India. MongoDB's first smoke test exposed a hydration timing issue; the invalid snapshot was removed and the corrected run verified filter activation and complete pagination. Live checks do not establish sustained access or an absence of rate limits.

Tests cover portal category parsing, Cloudflare metadata, India and engineering exclusion checks, date ordering, per-source policies, IBM's retained parser, and LinkedIn filters. Existing Databricks, Atlassian, and LinkedIn tests pass. Adapter CLI construction is checked for all 57 runnable entries. The remaining reused portals have not all had fresh live fetches during this audit. An attempted check of an old Airbnb snapshot job returned 404, so Airbnb current live behavior remains unverified; the structured-location parser and output guard are covered by tests.

## Microsoft headless adapter

The local Microsoft entry now runs `fetch_microsoft_browser_jobs.py` with the supplied careers URL. It launches a temporary headless Chromium session, reuses the UI's initial search response, and retrieves later pages and full descriptions through same-origin browser requests. It removes `pid` (a selected job, not a search filter), starts at zero, and checks that the actual profession and seniority request parameters and API-applied remote/relocation/profession/seniority facets match the URL.

Requests are sequential and paced at one second by default. Job details are cached for 24 hours and refreshed sooner if the listing's posting timestamp or name changes. This trades description freshness for fewer requests; use `--cache-hours 0` with the standalone adapter to disable caching. Search listings are fetched on every run, so cached jobs are only reused while they appear in the current selected results.

A 429 writes a cooldown deadline to `data/microsoft_browser_state.json`. A subsequent run stops before browser launch while the deadline is active. Numeric and HTTP-date Retry-After values are supported. Missing/invalid values use a 60-second fallback. Default immediate 429 retries: zero. The standalone script allows `--max-retries` with a short `--max-retry-wait` budget; a longer server cooldown is persisted, never shortened to fit the budget. A Microsoft-specific file lock prevents simultaneous adapter executions. The collection runner still needs general overlap and unattended process-cleanup integration before scheduler installation.

```sh
.venv/bin/python local_career_portals/run.py microsoft --max-jobs 50
```

Live headless tests on 31 October 2026 returned HTTP 200. A two-job cold-cache test made three API requests; repeating it made one search request and reused both cached descriptions. This demonstrates request reduction, not immunity from 429 responses. Unit tests cover cooldown persistence, next-run suppression, Retry-After dates, retry budgets, cache expiry, and exact URL filters.

Full-result validation returned 32 jobs with complete descriptions. The subsequent cache-warm run fetched four search pages, reused all 32 descriptions, and made only four API requests. No HTTP 429 was observed in these live checks.

## Third batch: ten additional companies

| Company | Integration | Filters and validation |
| --- | --- | --- |
| Adobe | Reused parser with filtered local wrapper | India/engineering listing checks and posting-date ordering before detail hydration; latest sample partial due listing-count mismatch. |
| Harness | Reused shared Greenhouse adapter | Exact Engineering department and India substring before the limit. |
| Nutanix | Reused Playwright adapter, repaired | Native India/Engineering URL; headless first, single minimized-headed fallback after HTTP 403. Structured locations and dates preserved. First listing page only. |
| PhonePe | New direct adapter | Official Apollo feed, PUBLIC status, exact Engineering department, India city/country checks, full descriptions from the linked SmartRecruiters tenant. |
| Razorpay | New shared Greenhouse adapter | Supplied department ID 4024806005 (Engineering), including descendant departments, and India locations. |
| Fivetran | New shared Greenhouse adapter | Exact Engineering Department, Employee Type Regular, OR of all three supplied locations. Bangalore/Bengaluru aliases and trailing APAC labels are normalized. |
| Cockroach Labs | New shared Greenhouse adapter | Exact Engineering department and India locations. |
| Palo Alto Networks | Reused dedicated HTTP adapter, parser corrected | Software Engineer search; structured India-country check and engineering-title output guard. Latest sample fetched 7 roles. |
| ServiceNow | New public SmartRecruiters adapter | Software Engineer keyword, native Engineering function, country IN, supplied Bangalore/Hyderabad/Mumbai/Gurgaon city alternatives. Bangalore/Bengaluru and Gurgaon/Gurugram aliases are equivalent. |
| Eightfold AI | Reused dedicated tenant API adapter | Software Engineer query, India location, timestamp order, existing seniority preferences, conservative title/location guard. API name and location-list fallbacks are now preserved. |

One-job live smoke tests passed for all five new adapters, including full descriptions. These are smoke tests, not complete-result-count assertions. Cached full-board inspection matched 4 Razorpay, 16 Fivetran, and 1 Cockroach Labs roles; PhonePe's public feed contained 17 Engineering candidates in recognized Indian locations before detail validation. ServiceNow's main website returned a security challenge in headless mode; the separate public SmartRecruiters feed worked without browser retries or challenge interaction.

The new Greenhouse adapters fetch full descriptions in one board request and sort first-publication dates before limiting. PhonePe initially orders candidates by feed update time, then sorts hydrated descriptions by publication date; with a job cap this does not guarantee the globally newest original publication dates. ServiceNow retrieves and filters listing pages before limiting and hydrating descriptions, and sorts by releasedDate.

```sh
.venv/bin/python local_career_portals/run.py phonepe razorpay fivetran cockroach_labs servicenow --max-jobs 50
.venv/bin/python local_career_portals/run.py adobe harness nutanix palo_alto eightfold --max-jobs 50
```

There are now 28 configured runnable companies among the intended 30. Snowflake remains missing and Confluent deferred. The accidental IBM entry remains unconfirmed and excluded. No scheduler was installed.

Nutanix validation found that its site rejects headless Chromium with HTTP 403. A headed session minimized through CDP before navigation returned HTTP 200 and job links. The adapter now tries headless first and makes one minimized-headed attempt only after 403; it does not retry HTTP 429 or interact with verification challenges. If the headed attempt also fails, the source stops and retains the previous snapshot. Window minimization occurs before navigation but cannot guarantee no brief window visibility during Chromium startup. Harness and Eightfold AI also passed one-job live tests in this batch.

The repaired Nutanix adapter passed a full-description one-job smoke test via its minimized-headed fallback. Tests verify that repeated 403 stops after that one fallback and HTTP 429 never triggers it.

## Full sample on 1 November 2026

Run `sample_all.py` to collect isolated samples without replacing normal per-company snapshots:

```sh
.venv/bin/python local_career_portals/sample_all.py --max-jobs 50 --workers 3 --source-timeout 180
```

The completed sample is under `data/samples/20261101_085753/`: `all_companies_top50.json` contains 405 jobs across 26 companies, full descriptions, per-company status, filters, ordering caveats, and earlier attempt results for repaired sources. `summary.json` contains counts and a short preview. All 28 configured sources were attempted. Uber was blocked by verification, LinkedIn returned zero, and Adobe returned 5 partial results after its 78 unique listing candidates did not reconcile with 96 advertised. Nutanix covers the first listing page. Databricks, Atlassian, Glean and Harness dates are updates rather than original publication dates; the audited combined file labels them accordingly. Google preserves its native date ordering without emitting dates, while Rippling's order has no date guarantee.

This run recovered Airbnb through its public board feed (5 jobs), corrected Palo Alto's premature JSON entity decoding (7 jobs), and changed Adobe to filter and sort candidates before requesting full descriptions. Display-date parsing now handles Amazon month names and Atlassian AM/PM dates. PhonePe city labels were filled from its current public feed without downloading descriptions again. No stale result snapshots were substituted for failures; Microsoft retains its normal detail-cache policy.

## Uber local headed mode

The Uber entry now passes `--headed --minimized` to the existing adapter. Both the local runner and new sample runs use headed Chromium directly. Its dedicated window is minimized through CDP before navigation, with a startup minimize hint as well; a brief window appearance during launch is still possible. No personal browser profile is used. Verification challenges still stop the fetch. The separate `automation/run_uber.py` installation is unchanged.

```sh
.venv/bin/python local_career_portals/run.py uber --max-jobs 50
```

## Fourth batch: CrowdStrike, NVIDIA, Apple and finance/AI companies

Official career-page discovery and full up-to-50 validation were completed on 1 November 2026. All ten integrations are wired into `companies.json`, bringing the runnable collection to 38 companies (Snowflake missing, Confluent deferred; accidental IBM entry remains excluded).

| Company | Official career entry | Transport and filtering | Latest sample |
| --- | --- | --- | --- |
| CrowdStrike | https://www.crowdstrike.com/en-us/careers/ | Reuses existing Workday transport; country India, conservative engineering titles before hydration; verifies detail country and uses startDate | 12 |
| NVIDIA | https://jobs.nvidia.com/careers | Public PCSx API; Software Engineer query, verified jobCategory=engineering facet, India, timestamp order | 50 |
| Apple | https://jobs.apple.com/en-in/search | Reuses existing hydration adapter; India URL, conservative role guard; dates within a bounded candidate subset | 45 |
| Coinbase | https://www.coinbase.com/careers/positions | Public linked Greenhouse board; Engineering taxonomy plus engineering-title fallback for ML/security/enterprise-app roles, India | 8 |
| D. E. Shaw | https://www.deshawindia.com/careers | Public embedded Next.js regularJobs with full sections; Core Tech/Front Office Tech/Quality and Test Engineering/Systems; active India records, excluding exploratory applications | 30 |
| Squarepoint Capital | https://www.squarepoint-capital.com/open-opportunities | Public linked Greenhouse board; Technology plus conservative engineering/developer titles, India | 7 |
| Tower Research | https://tower-research.com/roles/ | Public board; engineering taxonomy and title fallback for quant-development roles, India including Gurgaon and Gift City | 9 |
| Millennium Management | https://www.mlp.com/careers/ | Official link resolves to career.mlp.com; public apply/v2/jobs API, India and engineering-title guard; t_update ordering | 13 |
| Moloco | https://www.moloco.com/company/careers | Official page explicitly uses boardToken=moloco; Engineering hierarchy and India guard | 0 |
| Arcesium | https://www.arcesium.com/careers | Linked public board arcesiumllc; Technology plus engineering-title guard, India | 3 |

The primary Arcesium page returned HTTP 429 and was not retried; its separate public linked board worked. Coinbase and Tower marketing pages also rejected direct HTTP, while their public linked feeds worked. Millennium's legacy PCSx endpoint returned a disabled-endpoint error, including in browser sessions; the adapter instead uses the actual v2 API observed from the browser's Show More Positions action. All production fetchers in this batch can use direct HTTP; no browser window is needed for their normal runs.

The isolated result is `data/samples/batch4_20261101_100810/batch4_top50.json` (177 jobs with full descriptions), with `summary.json` alongside it. Moloco's zero is a valid current India result, not a transport failure. D. E. Shaw has no publication dates, so source order is preserved. Millennium exposes update timestamps rather than posting timestamps. Apple retained 45 engineering matches from a 50-candidate subset, so this is not a guarantee of a global top 50. The public-board adapters sort first-publication timestamps before their local caps. The official career URL, adapter, filters, and validation result are recorded per company in the inventory.

```sh
.venv/bin/python local_career_portals/run.py crowdstrike nvidia apple coinbase de_shaw squarepoint tower_research millennium moloco arcesium --max-jobs 50
```

Tests cover source-native department mapping, quant developers outside engineering departments, India locations, D. E. Shaw exploratory/inactive exclusions and complete description sections, NVIDIA's actual camel-case jobCategory confirmation, Millennium update-date semantics, and existing Apple hydration. D. E. Shaw's canonical lowercase role URL was also checked against its official page.

## Fifth batch: Adyen, Canva, Notion, Anyscale, ElevenLabs, Samsara, Wiz, CyberArk, Okta, Snyk

Official-site discovery and fresh up-to-50 validation were completed on 3 November 2026. All ten integrations are configured; normal fetching requires no browser launch. The collection now has 48 runnable entries. Dates come from Greenhouse first_published (updated_at fallback), Ashby publishedAt, SmartRecruiters releasedDate, or successor JobPosting datePosted, sorted before local limits.

| Company | Official entry | Fetcher | Engineering/India results |
| --- | --- | --- | --- |
| Adyen | https://careers.adyen.com/vacancies | Public Greenhouse adyen board | 0 |
| Canva | https://www.lifeatcanva.com/en/jobs/ | Current public SmartRecruiters Canva board | 0 |
| Notion | https://www.notion.com/careers | Public Ashby Notion board | 1 |
| Anyscale | https://www.anyscale.com/careers | Official linked Ashby anyscale board | 5 |
| ElevenLabs | https://elevenlabs.io/careers | Public Ashby ElevenLabs board | 0 |
| Samsara | https://www.samsara.com/company/careers | Public Greenhouse samsara board | 3 |
| Wiz | https://www.wiz.io/careers | Public Greenhouse wizinc board | 0 |
| CyberArk | https://www.cyberark.com/careers/ | Brand-scoped direct successor-portal HTML/JobPosting adapter | 0 |
| Okta | https://www.okta.com/company/careers/job-listing/ | Public Greenhouse okta board | 50 |
| Snyk | https://snyk.io/careers/all-jobs/ | Official linked Ashby Snyk board | 0 |

Adyen, Samsara, Wiz, and Okta have several technical department labels, so their adapters use conservative engineering titles and explicitly exclude sales/support departments before imposing the cap. Ashby adapters require isListed=true and explicit India eligibility in the main or secondary location/address; isRemote and description mentions alone never establish India eligibility. A US/Europe remote role is not silently treated as India eligible. Mixed Engineering & Product departments do not qualify non-engineering titles automatically. Canva's India-empty result is verified against an active global board, and its official current country selector also showed no India openings during browser inspection. Snyk's current public board exposes no India locations. Empty results do not mean there are no jobs globally; Adyen and ElevenLabs, for example, have India roles outside these conservative engineering-title filters.

CyberArk's old career URL currently redirects to Palo Alto Networks' Idira product page; the earlier official careers content directs applicants to Palo Alto Networks. The former CyberArk SmartRecruiters tenant is globally empty. The replacement adapter therefore searches the successor portal with the CyberArk keyword, requires a literal CyberArk/Idira description reference, engineering title and structured India country, and preserves the actual hiring employer. This is a brand/keyword-scoped successor integration, not an assertion that every result is a separately labeled CyberArk legal-entity vacancy. Unrelated Palo Alto jobs are not relabeled. Evidence excerpts and the employer transition are included in the output.

The isolated sample is `data/samples/batch5_20261103_141702/batch5_top50.json` with 59 full-description jobs across four companies; `summary.json` records all ten statuses. All ten completed without fetch failures (four nonempty, six valid empty filtered results). Browser verification was used for discovery where useful; production fetching uses direct feeds/HTML.

```sh
.venv/bin/python local_career_portals/run.py adyen canva notion anyscale elevenlabs samsara wiz cyberark okta snyk --max-jobs 50
```

Tests cover secondary-location eligibility, remote-scope exclusions, listed-only filtering, publication-date ordering, descriptions, nonstandard technical department labels, sales/support exclusions, Canva country and role checks, and rejection of unbranded Palo Alto descriptions from the CyberArk scope. Existing source-family tests and CLI argument checks pass as well. No scheduler was installed.

## Sixth batch: storage and enterprise companies

Nine integrations were discovered, implemented/reused, and live-validated on 3 November 2026. The collection now has 57 configured runnable companies. All nine production fetchers use direct public APIs; browser use was limited to discovering Cohesity's current source after its marketing-site feed rejected direct HTTP.

| Company | Official career entry | Integration | Sample jobs |
| --- | --- | --- | --- |
| JFrog | https://join.jfrog.com/positions/ | Public Greenhouse jfrog board | 0 |
| Netskope | https://www.netskope.com/company/careers/open-positions | Public Greenhouse netskope board | 15 |
| SentinelOne | https://www.sentinelone.com/careers/ | Public sentinellabs board, with SentinelOne canonical job links | 9 |
| Pure Storage / Everpure | https://www.everpuredata.com/company/careers.html | Public purestorage board; requested name and current employer preserved | 40 |
| Arista Networks | https://www.arista.com/en/careers | Public AristaNetworks SmartRecruiters feed and full description/qualification sections | 20 |
| Cohesity | https://www.cohesity.com/careers/open-positions/ | Public Cohesity Workday tenant (Cohesity_Careers); replaces the old direct marketing-feed path in the local collection | 6 |
| Broadcom | https://www.broadcom.com/company/careers | Public Broadcom Workday External_Career tenant | 50 |
| Workday | https://www.workday.com/en-us/company/careers/overview.html | Public workday Workday tenant | 1 |
| Docusign | https://careers.docusign.com/careers-home/jobs | Public careers JSON API with full description, qualifications and responsibilities | 29 |

The isolated sample is `data/samples/batch6_20261103_153907/batch6_top50.json`: 170 jobs across eight companies, with all nine sources completing successfully. `summary.json` records each status. JFrog's current India roles are support, finance and product roles, so zero passed the engineering filter. This is a filtered empty result, not a transport failure. The India/technical-title filters are applied before local caps where the source adapter controls candidate selection. Member of Technical Staff roles are now recognized as technical titles; sales/support exclusions still apply.

The original Pure Storage site redirects to Everpure's official careers page, and the existing purestorage board reports employer_name=Everpure. The company is therefore displayed as Pure Storage (Everpure), with original source employer metadata preserved. SentinelOne's marketing jobs page returned HTTP 429 and was not retried; its separate public board worked.

The new shared `fetch_workday_india_jobs.py` reuses the existing Workday transport but discovers tenant-specific geographic and engineering facets from the live response. Workday uses `Location_Country` (case sensitive); blindly supplying `locationCountry` caused a 400. Broadcom does not expose a country facet and silently ignored the assumed country filter, so the adapter selects all discovered India location IDs instead. Cohesity uses the conventional locationCountry facet. R&D/Engineering job-family IDs are selected from actual labels where available. Every hydrated role is checked for India again, and startDate ordering is applied before the cap. Relative strings such as Posted Yesterday are not presented as exact dates. The old generic source scripts and application `.env` switches remain unchanged.

Docusign's source can assign a Marketing category to an actual Software Engineer role. The adapter therefore preserves categories as evidence, filters by verified country and technical title, and reads full description fields rather than using the short metadata summary. Pagination was verified as one-based with limit=100. Date parsing now supports offsets such as +0000 without fractional seconds.

```sh
.venv/bin/python local_career_portals/run.py jfrog netskope sentinelone pure_storage arista cohesity broadcom workday docusign --max-jobs 50
```

Tests cover case-sensitive country facets, nested Broadcom location facets and Indiana exclusion, Workday detail-country validation, canonical Workday URLs, Member of Technical Staff roles, Docusign category inconsistencies and timezone formats, and Arista country/title checks. Source-family regression tests and CLI construction checks pass. No scheduler was installed.

## Seventh batch: observability, payments, infrastructure and remote companies

Ten more integrations were added on 3 November 2026, bringing the runnable
collection to 67 companies. Production fetching uses public HTTP APIs or embedded
portal data for all ten; browser inspection helped identify the current sources.

| Company | Career portal / feed | Engineering and India selection |
| --- | --- | --- |
| Dynatrace | [Official careers](https://www.dynatrace.com/careers/jobs/), native Coveo search | Native `country=India` and `team=Engineering`; full JobPosting description and datePosted. An active global index and Engineering taxonomy are checked before accepting a filtered empty result. Search index timestamps are not posting dates. |
| PayPal | [Workday jobs](https://paypal.wd1.myworkdayjobs.com/jobs) | Discovered India city/virtual-location IDs and technical job families; no keyword restriction; technical titles and hydrated country checked. |
| eBay | [Official jobs](https://jobs.ebayinc.com/us/en/search-results), linked [Workday apply tenant](https://ebay.wd5.myworkdayjobs.com/apply) | Native India country and Engineering job family, technical/MTS titles and hydrated India geography. |
| Commvault | [Official careers](https://www.commvault.com/careers/jobs), `commvault` Greenhouse | India locations/offices and technical titles; source departments retained; sales, support, consulting and professional-services departments excluded. |
| Veeam Software | [Official careers](https://careers.veeam.com/search-jobs), `veeamsoftware` Greenhouse | India locations/offices and technical titles. The EU job-board links work through the standard public Greenhouse board API. |
| Red Hat | [Official careers](https://www.redhat.com/en/jobs), [Workday jobs](https://redhat.wd5.myworkdayjobs.com/jobs) | Country and Job Function facets discovered by their labels, including opaque `a` and `d` parameter keys; India, Engineering and technical titles checked. |
| GitLab | [Official careers](https://about.gitlab.com/jobs/all-jobs/), `gitlab` Greenhouse | Explicit India primary/secondary locations or offices and technical titles. Unspecified Remote and foreign remote locations are excluded. |
| Automattic | [Official job listings](https://automattic.com/work-with-us/jobs/) | Embedded `ghJobsData`, Engineering/Infrastructure categories and technical titles. Requires an explicit India location or a role-specific worldwide hiring statement, saved as `location_evidence`. A narrower foreign location takes precedence. Generic remote-company or global-salary statements do not qualify. |
| Grafana Labs | [Official careers](https://grafana.com/careers/), `grafanalabs` Greenhouse | Explicit India locations/offices and technical titles; foreign remote roles are excluded. |
| Elastic | [Official job portal](https://jobs.elastic.co/), `elastic` Greenhouse | Explicit India locations/offices and technical titles; consulting and partner sales architect departments are excluded; original departments and canonical portal links are retained. |

Engineering-title policies are conservative approximations where an exact portal
Engineering grouping is unavailable; IT/data/security engineering can qualify.
They do not label all product, marketing or business roles as engineering merely
because they share a department. Greenhouse snapshots include full descriptions
and `first_published`, separately from `updated_at`. Workday snapshots use full
`startDate` values. Automattic currently provides no job publication date, so that
field remains null; WordPress article dates are not used as a substitute.

Workday pagination preserves the first page's total: eBay returns `total=0` on
later pages while still returning live jobs. All matching pages are collected and
all selected details hydrated before sorting publication dates and taking the
50-job cap. Page limits are reported as incomplete rather than successful empty
results. MTS technical titles are recognized alongside Member of Technical Staff.

The isolated live sample is
`data/samples/batch7_20261103_183101/batch7_top50.json`; `summary.json` records
statuses and timings. The sample contains 99 full-description jobs: PayPal 9,
eBay 50, Commvault 9, Veeam 6, Red Hat 1, GitLab 20, Automattic 1 and Elastic 3.
All 98 records outside Automattic have source publication dates. Dynatrace and Grafana Labs returned valid empty filtered
results, not access failures. The new job-feed requests encountered no HTTP 429
responses during validation. This is a point-in-time observation, not a guarantee
against future rate limits. PayPal's marketing landing page returned 403 during
discovery; the separate public Workday feed worked.

```sh
.venv/bin/python local_career_portals/run.py dynatrace paypal ebay commvault veeam red_hat gitlab automattic grafana_labs elastic --max-jobs 50
```

Fifty source-family regression tests pass, covering opaque Workday facets,
later-page zero totals, explicit India eligibility, remote exclusions, consulting
and sales departments, worldwide hiring evidence and its precedence rules,
publication-date handling and full descriptions. No scheduler was installed.

## Eighth batch: database and AI companies

Ten sources were configured on 3 November 2026. Nine are live-validated and
runnable; Instabase is explicitly `source_unavailable`. The default collection now
runs 76 companies.

| Company | Current source | Engineering/India sample |
| --- | --- | ---: |
| Yugabyte | `yugabyte` public Greenhouse board; [official careers](https://www.yugabyte.com/careers/) | 2 |
| Redis | `Redis` public Ashby feed; [current openings](https://redis.io/company/careers/current-job-openings/) | 0 |
| SingleStore | `singlestore` public Greenhouse board; [official jobs](https://www.singlestore.com/careers/jobs/) | 6 |
| StarTree | [Native Greenhouse board](https://job-boards.greenhouse.io/startree) | 3 |
| ThoughtSpot | [Official careers](https://www.thoughtspot.com/careers) `api/getCareersListing`, with linked Rippling job details | 7 |
| Instabase | [Official jobs](https://www.instabase.com/careers/jobs), embedded `instabase` Greenhouse source | Unavailable: HTTP 404 |
| Prophecy AI | `prophecysimpledatalabs` public Greenhouse board linked from [current official careers](https://www.prophecy.ai/careers) | 0 |
| DevRev | [Native Greenhouse board](https://job-boards.greenhouse.io/devrev) | 9 |
| Ema | `Ema` public Ashby feed; [official jobs](https://www.ema.ai/careers/jobs) | 9 |
| Endor Labs | `endorlabs` public Greenhouse board linked from [official careers](https://www.endorlabs.com/careers) | 8 |

The isolated sample is
`data/samples/batch8_20261103_184255/batch8_top50.json`, with 44 full-description
jobs and all ten statuses; `summary.json` records timings and source metadata.
Thirty-seven records have explicit publication dates. ThoughtSpot's seven records
currently expose only a Rippling `createdOn` value, which is retained as
`source_created_date`; `posted_date` stays null rather than treating creation as
publication. If Rippling supplies explicit publication metadata later, the adapter
will retain it. Dated results are sorted before limiting to 50; undated results
preserve the source order.

StarTree and Endor Labs use their native Engineering department and descendants;
Endor's security researchers therefore qualify even without Engineer in the
title. DevRev uses Engineering, Engineering - Applied AI Engineering, and R&D.
Yugabyte and SingleStore use technical-title checks because development teams can
be labeled Technology, Engine, Internal Services, and Cloud Operation. Sales, SE,
support and consulting departments are excluded by those title-based adapters.
Talent communities/pools, general applications and expressions of interest are
excluded from this batch rather than presented as open vacancies. Prophecy's
India engineering talent-community listing is excluded on that basis.

Redis and Ema require the Ashby Engineering department, a technical title, and
explicit India eligibility from primary/secondary locations or structured country
metadata. The 39 public Ema feed IDs were checked against all 39 jobs on its
native page. Generic Remote does not establish India eligibility. Redis currently
has three India roles, all outside Engineering; its empty sample is verified
against an active global feed. Its old `redislabs` Greenhouse board returns 404 and
is not used.

ThoughtSpot's old Greenhouse source is unavailable. The replacement reads all 60
records returned by the same listing API used by the current official UI, then
hydrates selected Rippling pages. It validates the company and job UUID, rejects
unlisted detail records, and retains the full company and role descriptions. Its
mixed Engineering and Product Management department is filtered by technical/MTS
or technical-lead titles; product/program managers are not included solely for
department membership. An actual AI application engineer in Core Operation is
included, while sales and customer-engagement departments are excluded. Location
eligibility uses structured country metadata; Trivandrum qualifies without
requiring a literal India suffix in the city label.

Instabase's own JavaScript calls the public `instabase` Greenhouse board, which
returns HTTP 404 for both the board and jobs endpoints. Browser inspection
confirmed the same failed request; the UI's No jobs available text follows that
error. This is an unavailable source, not a verified empty result. Its adapter
configuration remains available for a direct recheck, but default/manual runner
selection excludes it until a working source is verified. Old static job links
and third-party copies were not substituted for a live portal feed.

All nine working production fetchers use direct public HTTP feeds or detail HTML.
During discovery, Yugabyte and StarTree marketing pages returned 403, and DevRev's
marketing page returned 429; their separate public job boards worked. No working
job feed returned 429 in the sample run. Instabase's 404 is not a rate-limit or
headless-browser failure.

```sh
.venv/bin/python local_career_portals/run.py yugabyte redis singlestore startree thoughtspot prophecy devrev ema endor_labs --max-jobs 50
```

Fifty-seven adapter/filter regression tests pass, including native department
hierarchies, security researcher coverage, talent-pool exclusions, nonstandard
SingleStore team names, sales/SE exclusions, Ashby department and country checks,
ThoughtSpot mixed departments and technical leads, full descriptions, job
identity, and separation of creation/publication timestamps. No scheduler was
installed or database jobs imported.

## Ninth batch: platform, commerce and fintech companies

Nine adapters were configured on 3 November 2026, bringing the collection to 85
runnable configurations. Zeta means the banking/fintech company at zeta.tech,
confirmed by the user; Zeta Global is not included.

**The initial local validation failed; the later headless retest passed.** Direct HTTP, IPv4 curl and
isolated Playwright request contexts timed out across unrelated marketing sites
and job API hosts, including previously reachable source families. The Playwright
browser tool also encountered an existing-profile launch conflict. Source
identities were checked through web browsing, and local fixture/regression tests
pass. Neither issue is evidence of a company rate limit or an empty job board. The completed retest and corrected Kong mapping are documented below.

| Company | Configured source | Engineering and India selection |
| --- | --- | --- |
| Kong | `kong` Ashby board; [official careers](https://careers.konghq.com/) | Native team `ENG` under department `All Cost Center`, technical titles, and explicit India primary/secondary locations or structured country. Its old Lever board returns 404 and is not used. |
| Docker | `docker` Ashby board; [official openings](https://www.docker.com/career-openings/) | Listed Engineering roles and technical titles; explicit India eligibility, not generic Remote. |
| ClickHouse | `clickhouse` Ashby board; [official careers](https://clickhouse.com/company/careers) | Engineering department and technical titles, explicit India eligibility; Support Services consulting roles excluded. Its old Greenhouse board returns 404 and is not used. |
| Miro | `realtimeboardglobal` public Greenhouse source; [official openings](https://miro.com/careers/open-positions/) | Technical titles and India location/offices, with sales/support/consulting exclusions. The hosted board redirects to Miro's own careers site. |
| Bloomreach | `bloomreach` public Greenhouse board; [official careers](https://www.bloomreach.com/en/careers) | Native Engineering department/descendants and India locations/offices. |
| Apollo.io | `apolloio` public Greenhouse board; [official careers](https://www.apollo.io/careers) | Verified sales-intelligence company; native Engineering department and India/Bangalore locations/offices. |
| Flexport | `flexport` public Greenhouse board; [official careers](https://www.flexport.com/careers/) | Technical titles and India locations/offices; sales/support/consulting and talent-community listings excluded. |
| BitGo | `bitgo` public Greenhouse board; [official careers](https://www.bitgo.com/company/careers) | Native Engineering department/descendants and India locations/offices; Operations support roles excluded. |
| Zeta | `zeta` public Lever feed; [official fintech careers](https://www.zeta.tech/in/careers/work-with-us) | Exact Engineering team, technical titles and India primary/secondary locations; excludes Solution Engineering and technical support. |

The new local `fetch_lever_india_jobs.py` reuses the existing generic Lever HTTP
transport. It supplements the older Zeta script's behavior with India filtering
before the cap, all-location handling, paginated listing collection, repeated-page
detection, and complete descriptions including responsibility/qualification lists
and additional sections. The original standalone scripts remain available.

Greenhouse records retain `first_published` and separate update timestamps; Ashby
records retain `publishedAt`. Zeta retains explicit feed publication fields or
JobPosting JSON-LD `datePosted` from public detail pages when available. Its Lever
`createdAt` is stored separately as `source_created_date`, never silently promoted
to a publication date. If optional Zeta detail-date retrieval fails, valid full
feed descriptions remain available and lookup errors are recorded; a 429 stops
further optional date lookups. Dated records are sorted before taking the 50-job
cap, and undated records preserve source order.

The bounded local check report is
`data/samples/batch9_20261103_190906/batch9_top50.json`, with a `summary.json`
alongside it. Failed requests are recorded as failures, not verified empty
results; a report with zero fetched jobs does not mean these companies have no
matching jobs. Previous successful snapshots are preserved by the normal runner.

To fetch the batch once local connectivity is available:

```sh
.venv/bin/python local_career_portals/run.py kong docker clickhouse miro bloomreach apollo flexport bitgo zeta --max-jobs 50
```

Sixty-five adapter/filter regression tests pass. New coverage checks Zeta team and
country boundaries, secondary locations, full descriptions, job identity,
creation/publication date separation, JSON-LD graphs and encoded quotes, Lever
pagination and repeated-page detection, native Greenhouse departments,
sales/consulting/talent-pool exclusions and Ashby country/department requirements.
All nine CLI commands also construct successfully. No scheduler was installed and
no jobs were imported into the database.

## Tenth batch: commerce, enterprise and AI companies

Twelve sources were configured on 3 November 2026. Eleven are runnable; Walmart
Global Tech is temporarily `source_unavailable` because its tenant redirects to
Workday's HTTP 500 service-interruption page. This brings the runnable collection
to 96 configurations. The prior ninth batch was subsequently validated in the headless retest below.

| Company | Current source and filtering |
| --- | --- |
| Quince | Official `quince` Greenhouse board, not the separate quince-careers board. Engineering-named department branches and descendants plus India locations/offices; includes native engineering data-science and leadership roles. |
| CRED | Public `cred` Lever board; India and technical titles across security/enterprise IT, with sales/support exclusions. |
| Groww | Official careers View openings link points to the EU `groww` Greenhouse board. Its nine current roles include no matching engineering vacancies. Unrelated Growwh/referral boards are not used. |
| Meesho | Public `meesho` Lever board; India locations and technical titles across Tech, security and platform teams; complete description sections. |
| Flipkart | The Jobs navigation on flipkartcareers.com links to the current TurboHire tenant. Native Technology/CL-Engg and India addresses; public response contains full descriptions and PublishedDate. |
| Walmart Global Tech | Shared Workday adapter configured for WalmartExternal with native India/engineering facets, technical titles and required Walmart Global Tech brand evidence in hydrated details. Currently unavailable due to the tenant's service interruption. |
| Visa | Current `visa.wd5.myworkdayjobs.com/Visa` Workday source. India country and Engineering job-family facets discovered from actual labels, with detail-country/title checks. The old SmartRecruiters tenant is globally empty and is not treated as Visa's live source. |
| OpenAI | Public `openai` Ashby feed; listed technical roles with explicit India primary/secondary locations or structured country. Original departments retained, including technical deployment/architecture roles in Go To Market. Generic foreign Remote is excluded. |
| Anthropic | Public `anthropic` Greenhouse board; India and technical titles across Applied AI and engineering, excluding sales/support roles. |
| HashiCorp | Its official careers page now links to IBM's `q=hashicorp` search. Reuses the IBM search/schema utilities with native Software Engineering/India facets, detail geography and literal HashiCorp evidence. Actual hiring employer is retained; unrelated IBM vacancies are excluded. |
| Cisco | Current Cisco_Careers Workday tenant; discovers all India location IDs and Engineering job-family IDs rather than assuming a country parameter; detail geography and technical titles checked. |
| DigitalOcean | Current `digitalocean98` Greenhouse source; India and technical titles across cloud, security and platform teams, with sales/support/consulting exclusions. |

### Explicit headless transport

Direct HTTP from this Mac timed out across unrelated sources while a headless
Chrome navigation to the same API worked. `portal_http.py` now supports an
explicit per-company `transport: browser` setting, selected for this batch. The
runner and sampler pass this only to that company's subprocess using
`CAREER_PORTAL_TRANSPORT=browser`. Existing sources without the setting keep their
HTTP transport. This uses installed Chrome with a fresh headless context, not the
user's browser profile. The browser is reused within one adapter process and
closed on exit; source timeouts retain the sampler's process-tree cleanup.

GETs use Chrome's network stack. POSTs execute browser fetch from an established
portal origin, because Playwright APIRequestContext shares the direct-network
problem on this machine. Legitimate IBM API-to-website redirects are allowed;
Workday redirects to its separate maintenance host fail explicitly. Large JSON
responses have an increased protocol buffer and a DOM fallback if a response body
is evicted. No CAPTCHA is solved, security setting changed, or user login used.

This transport is also available when running a shared adapter directly:

```sh
CAREER_PORTAL_TRANSPORT=browser .venv/bin/python local_career_portals/fetch_additional_board_jobs.py https://www.anthropic.com/careers --source anthropic --max-jobs 50 --output /tmp/anthropic_jobs.json
```

Flipkart's legacy jobslist shows a different static listing and its Show More
handler only raises an alert. The new adapter follows the official current Jobs
link instead. It captures TurboHire's own public full-description response while
the site handles its anonymous session. It requires Result count to equal Total
rather than silently accepting pagination. The canonical `/job/publicjobs/` URL
and its already encoded JobIdObfuscated token were verified by opening a real
SDE vacancy; tokens are not re-encoded. TurboHire's seven-digit fractional timestamps are normalized to six-digit datetime precision, with the raw value retained as source_posted_date. Recruiter names, email fields, tax settings
and other unrelated fields in the response are excluded from normalized jobs.

HashiCorp is a keyword-scoped IBM integration, not a claim of a separate hiring
legal entity. `brand_evidence` records the description's HashiCorp reference and
`employer_name` retains the actual employer. Its search honors the query rather
than accidentally querying all IBM jobs. Search index dates are not publication
dates. The existing IBM integration stays excluded as unconfirmed; this new
HashiCorp entry is independently scoped.

Publication fields remain distinct: Greenhouse first_published, Ashby publishedAt,
TurboHire PublishedDate, Workday startDate, and JobPosting.datePosted where
available. Lever descriptions retain responsibility/qualification lists and
additional sections; optional detail lookup enriches explicit publication dates.
A failed optional lookup preserves valid full descriptions, records the error,
and stops further date lookups on HTTP 429. Creation/update dates are not silently
promoted to publication dates.

The isolated live report is
`data/samples/batch10_20261103_211801/batch10_top50.json`; `summary.json` records
per-source statuses, timings, and source/filter metadata. The final sample contains 143 full-description jobs, all with explicit posting dates: Quince 8, CRED 2, Meesho 7, Flipkart 4, Visa 48, OpenAI 3, Anthropic 3, HashiCorp 1, Cisco 50 and DigitalOcean 17. Groww has a verified empty filtered result. Walmart's failed tenant
is an unavailable result, not zero matching jobs. The other live counts are
recorded in that report. No scheduler was installed or database jobs imported.

```sh
.venv/bin/python local_career_portals/run.py quince cred groww meesho flipkart visa openai anthropic hashicorp cisco digitalocean --max-jobs 50
```

Seventy-six adapter/filter regression tests pass. New coverage includes per-company
transport isolation, browser HTTP errors, large JSON handling, IBM keyword/country
filters and legitimate redirects, Workday maintenance rejection, Walmart Global
Tech evidence, Flipkart publication/canonical-ID semantics, native Quince branches,
and CRED/Meesho security-engineering roles.


## Completed retest of the nine previously unsuccessful sources

On 3 November 2026 all nine completed successfully through isolated headless
Chrome. Their registry entries now persist `transport: browser`, and the old
failed validation records have been replaced by the new checked results.

| Company | Engineering/India jobs |
| --- | ---: |
| Kong | 5 |
| Docker | 0 |
| ClickHouse | 2 |
| Miro | 0 |
| Bloomreach | 4 |
| Apollo.io | 3 |
| Flexport | 0 |
| BitGo | 4 |
| Zeta fintech | 3 |

The fresh isolated sample is
`data/samples/batch9_retest_20261103_214920/batch9_retest_top50.json`, with
`summary.json` alongside it. All 21 jobs have full descriptions, explicit
publication dates that parse through the database importer, unique source IDs,
Engineering/India eligibility and descending publication-date order. No jobs were
imported into the database, and previous snapshots were retained separately.

The initial successful transport check exposed a false empty result for Kong:
its feed reports department `All Cost Center` and native team `ENG`, rather than
an Engineering department. The adapter now requires `team=ENG`, technical titles
and explicit India eligibility, while retaining the actual source department and
team. A fresh live rerun returned five jobs. A regression test rejects GTM team
roles and foreign locations under the same generic cost center.

The three zero counts were verified against active global boards. Docker has
52 global listings and no explicit India locations; Miro has 19 global listings
and no India locations. Flexport has 190 global listings and four India jobs,
all in ocean operations or sales, so none pass the engineering filter. These are
valid filtered empty results, not failed fetches. The nine-source report contains
no source failures. Seventy-seven adapter/filter regression tests pass.
