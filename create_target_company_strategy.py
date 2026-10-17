from pathlib import Path
from subprocess import run

rows = [
    ("NVIDIA", "Systems and accelerated computing", "High", "Platform, C++, distributed systems"), ("Qualcomm", "Core engineering and systems", "High", "Systems, platform, Java, C++"), ("Walmart Global Tech", "Large India product engineering", "High", "Backend, data, SRE"), ("ServiceNow", "Enterprise platform engineering", "High", "Backend, cloud, workflow platform"), ("SAP Labs", "Enterprise product and cloud", "High", "Backend, cloud, data"), ("PayPal", "Payments infrastructure", "High", "Java, distributed systems, reliability"), ("LinkedIn", "Product and infrastructure", "High", "Backend, data, infrastructure"), ("Booking.com", "Global consumer product", "High", "Backend, platform, experimentation"), ("PhonePe", "India payments at scale", "High", "Java, payments, distributed systems"), ("Razorpay", "Payments and fintech", "High", "Backend, APIs, platform"), ("Snowflake", "Data infrastructure", "Medium", "Data platform, storage"), ("Datadog", "Observability platform", "Medium", "Backend, infrastructure"), ("Cloudflare", "Networking and edge", "Medium", "Network systems, security"), ("Confluent", "Streaming data platform", "Medium", "Java, Kafka, cloud"), ("Rubrik", "Data security and cloud", "Medium", "Backend, cloud, storage"),
]
table = "".join(f"<tr><td>{a}</td><td>{b}</td><td>{c}</td><td>{d}</td></tr>" for a,b,c,d in rows)
html = f'''<!doctype html><html><head><meta charset="utf-8"><style>@page{{margin:.7in}}body{{font-family:Arial;font-size:10.5pt;line-height:1.35;color:#111}}h1{{text-align:center;font-size:24pt;margin:0 0 4pt}}h2{{font-size:15pt;margin:18pt 0 6pt}}.sub{{text-align:center;font-style:italic;color:#444;margin:0 0 16pt}}p{{margin:6pt 0}}ul{{margin:5pt 0 7pt 18pt;padding:0}}li{{margin:3pt 0}}table{{border-collapse:collapse;width:100%;margin:7pt 0 12pt}}th{{background:#1F4E78;color:#fff;text-align:left;padding:6pt;font-size:9pt}}td{{border:1px solid #D9D9D9;padding:5pt;vertical-align:top;font-size:9pt}}tr:nth-child(even) td{{background:#F3F7FA}}</style></head><body>
<h1>Target Company Strategy</h1><p class="sub">For an NITK graduate with two years of Oracle experience targeting high compensation software roles in India</p>
<p><b>Recommendation.</b> The current company list is a strong base. Add companies with mature India engineering teams, strong backend and platform work, and compensation potential aligned with a ₹35L+ total compensation goal. Prioritize role quality, interview probability, and fit over applying broadly to every open title.</p>
<h2>Positioning and search focus</h2><ul><li><b>Primary pitch:</b> Oracle experience building enterprise-grade systems, supported by strong fundamentals from NITK.</li><li><b>Best-fit titles:</b> Software Engineer II, Backend Engineer, Platform Engineer, Infrastructure Engineer, Distributed Systems Engineer, Data Engineer, and Site Reliability Engineer.</li><li>Prioritize Bengaluru and Hyderabad, then India-remote roles. Apply at the 1.5 to 3.5 years experience band when scope is appropriate.</li><li>Treat ₹35L+ as total compensation. Compare fixed pay, bonus, RSUs, joining bonus, and refreshers rather than fixed salary alone.</li></ul>
<h2>Priority additions to the matcher</h2><table><tr><th>Company</th><th>Why add it</th><th>Priority</th><th>Likely role themes</th></tr>{table}</table>
<h2>Strong secondary additions</h2><p><b>Enterprise and infrastructure.</b> Cisco, Broadcom, Dell Technologies, Intel, AMD, Red Hat, VMware by Broadcom, Palo Alto Networks, Okta, Elastic, MongoDB, F5, Dynatrace, New Relic, and GitHub.</p><p><b>Consumer and marketplace.</b> Swiggy, Zepto, Meesho, Flipkart, Myntra, Dream11, InMobi, Glance, ShareChat, and Expedia Group.</p><p><b>Fintech and payments.</b> CRED, Groww, Juspay, Fi Money, Navi, Cashfree, Pine Labs, and PhonePe group companies.</p><p><b>AI and developer tools.</b> Figma, Postman, Glean, Cohere, Scale AI, Hugging Face, Sentry, and Harness.</p><p><b>Global remote friendly.</b> GitLab, Automattic, Canonical, Grafana Labs, HashiCorp, and Vercel. Evaluate India employment eligibility role by role.</p>
<h2>Existing sources worth enabling first</h2><p>Enable high-fit adapters already available before adding every new source. This has a better near-term return than expansion without applications.</p><ul><li>Google, Microsoft, Amazon, Uber, Salesforce, Atlassian, Adobe, Databricks, Stripe, Airbnb, Coinbase, Mastercard, Goldman Sachs, American Express, Morgan Stanley, and Visa.</li><li>For India product roles: Postman, Meesho, slice, Glean, Harness, Target, Palo Alto Networks, Zeta, and Rippling.</li><li>Enable 8 to 12 sources at once; review relevance weekly and prune noisy feeds.</li></ul>
<h2>Application operating plan</h2><table><tr><th>Step</th><th>Action</th><th>Outcome</th></tr><tr><td>1</td><td>Build a focused target set</td><td>Start with the 10 priority additions plus 8 to 12 existing sources.</td></tr><tr><td>2</td><td>Tune search filters</td><td>Use Backend, Platform, Infrastructure, Distributed Systems, Cloud, and SRE terms.</td></tr><tr><td>3</td><td>Apply selectively</td><td>Prioritize roles close to two years experience and aligned to Oracle work.</td></tr><tr><td>4</td><td>Prepare interview signal</td><td>Pair DSA with LLD, HLD, databases, concurrency, APIs, and production-impact stories.</td></tr><tr><td>5</td><td>Measure weekly</td><td>Track sourced roles, applications, referrals, screens, interviews, and conversion.</td></tr></table>
<h2>Important caveats</h2><ul><li>Compensation varies by level, location, equity grant, market conditions, and interview performance. No company guarantees ₹35L+.</li><li>A source integration only discovers roles. Referrals, tailored resumes, strong project stories, and interview preparation drive the outcome.</li><li>Prefer public APIs and server-rendered careers data when adding fetchers. Do not use login-required or access-control-evasion approaches.</li></ul></body></html>'''
plain = """TARGET COMPANY STRATEGY
For an NITK graduate with two years of Oracle experience targeting high compensation software roles in India

RECOMMENDATION
The current company list is a strong base. Add companies with mature India engineering teams, strong backend and platform work, and compensation potential aligned with a ₹35L+ total compensation goal. Prioritize role quality, interview probability, and fit over applying broadly to every open title.

POSITIONING AND SEARCH FOCUS
• Primary pitch: Oracle experience building enterprise-grade systems, supported by strong fundamentals from NITK.
• Best-fit titles: Software Engineer II, Backend Engineer, Platform Engineer, Infrastructure Engineer, Distributed Systems Engineer, Data Engineer, and Site Reliability Engineer.
• Prioritize Bengaluru and Hyderabad, then India-remote roles. Apply at the 1.5 to 3.5 years experience band when scope is appropriate.
• Treat ₹35L+ as total compensation. Compare fixed pay, bonus, RSUs, joining bonus, and refreshers rather than fixed salary alone.

PRIORITY ADDITIONS TO THE MATCHER
Company | Why add it | Priority | Likely role themes
""" + "\n".join(" | ".join(row) for row in rows) + """

STRONG SECONDARY ADDITIONS
Enterprise and infrastructure: Cisco, Broadcom, Dell Technologies, Intel, AMD, Red Hat, VMware by Broadcom, Palo Alto Networks, Okta, Elastic, MongoDB, F5, Dynatrace, New Relic, and GitHub.
Consumer and marketplace: Swiggy, Zepto, Meesho, Flipkart, Myntra, Dream11, InMobi, Glance, ShareChat, and Expedia Group.
Fintech and payments: CRED, Groww, Juspay, Fi Money, Navi, Cashfree, Pine Labs, and PhonePe group companies.
AI and developer tools: Figma, Postman, Glean, Cohere, Scale AI, Hugging Face, Sentry, and Harness.
Global remote friendly: GitLab, Automattic, Canonical, Grafana Labs, HashiCorp, and Vercel. Evaluate India employment eligibility role by role.

EXISTING SOURCES WORTH ENABLING FIRST
Google, Microsoft, Amazon, Uber, Salesforce, Atlassian, Adobe, Databricks, Stripe, Airbnb, Coinbase, Mastercard, Goldman Sachs, American Express, Morgan Stanley, and Visa.
India product roles: Postman, Meesho, slice, Glean, Harness, Target, Palo Alto Networks, Zeta, and Rippling.
Enable 8 to 12 sources at once; review relevance weekly and prune noisy feeds.

APPLICATION OPERATING PLAN
1. Build a focused target set: Start with the 10 priority additions plus 8 to 12 existing sources.
2. Tune search filters: Use Backend, Platform, Infrastructure, Distributed Systems, Cloud, and SRE terms.
3. Apply selectively: Prioritize roles close to two years experience and aligned to Oracle work.
4. Prepare interview signal: Pair DSA with LLD, HLD, databases, concurrency, APIs, and production-impact stories.
5. Measure weekly: Track sourced roles, applications, referrals, screens, interviews, and conversion.

IMPORTANT CAVEATS
Compensation varies by level, location, equity grant, market conditions, and interview performance. No company guarantees ₹35L+.
A source integration only discovers roles. Referrals, tailored resumes, strong project stories, and interview preparation drive the outcome.
Prefer public APIs and server-rendered careers data when adding fetchers. Do not use login-required or access-control-evasion approaches.
"""
source=Path("/private/tmp/target_company_strategy.txt"); source.write_text(plain,encoding="utf-8")
out=Path("data/target_company_strategy.docx"); out.parent.mkdir(exist_ok=True)
run(["/usr/bin/textutil","-convert","docx",str(source),"-output",str(out)],check=True)
print(out)
