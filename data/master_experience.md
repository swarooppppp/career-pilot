# Master Experience Repository

> Initial version derived only from the current resume (`main.tex`).
> This is a starting source of truth, not a complete career history. Add or
> correct details before using generated content for real applications.

## Candidate

- Name: Swaroop Voonna
- Location: Hyderabad, India
- Current experience: Software Engineer at Oracle

## Oracle — Software Engineer

- Employer: Oracle
- Location: Hyderabad, India
- Dates: June 2024 — Present

### Workforce Compensation platform

- Migrated Workforce Compensation from ADF server-side rendering to a decoupled REST architecture.
- The migration enabled independent frontend deployments across more than 900 enterprise clients.
- Redesigned the WFC Worksheet from a session-based model to a stateless architecture.
- Used token-based context preservation and database-driven state management.
- Reduced server memory consumption by approximately 40% under peak concurrent load.
- Replaced in-place updates for hierarchical compensation aggregates with an append-only delta pattern.
- The delta pattern allows concurrent writes without blocking and computes real-time totals from base and diff rows.
- Built a Java-based SQL rewriter that translates dummy queries over a virtual schema into security-hardened production queries.
- Added row-level access controls at every subquery level across more than 30 tables.
- Decoupled LLM reasoning from backend architecture.

### AI agents and LLM systems

- Designed and shipped AI agents for managers.
- Agents generate spend summaries, detect promotion biases, and surface workforce insights.
- The agents were adopted by more than 120 client organizations within three months of launch.
- Implemented token optimization and context caching strategies for LLM inference pipelines.
- Reduced token usage by 75%.
- Reduced average response latency from approximately 15 seconds to approximately 5 seconds.

## Oracle — Project Intern

- Employer: Oracle
- Location: Hyderabad, India
- Dates: May 2023 — July 2023

- Built and optimized conversational workflows in Oracle Digital Assistant across more than 15 HR use cases.
- Improved bot resolution accuracy from 61% to 88% through intent-mapping refinements.
- Reduced manual operations by approximately 50% in initial deployments.

## Projects

### Distributed Rate Limiter as a Service

- Repository: https://github.com/swarooppppp/distributed-rate-limitter
- Technologies explicitly listed on the resume: Java, Spring Boot, Redis, Docker.
- Built a distributed rate-limiting service using Redis.
- Supported token bucket, sliding window, and fixed window algorithms.
- Handled approximately 1,000 requests per second under concurrent load.
- Implemented atomic request handling using Redis INCR and EXPIRE primitives.
- Maintained correctness under concurrent load with zero over-admission across more than 10,000 requests.

### Expense Splitter

- Repository: https://github.com/swarooppppp/onepoint
- Technologies explicitly listed on the resume: Spring Boot, React, PostgreSQL, Redis, Kafka, Docker.
- Designed a distributed expense-management platform with event-driven group synchronization using Kafka.
- Propagated expense changes to personal dashboards with end-to-end latency under 300 milliseconds across more than 5,000 concurrent users.
- Ensured consistency under concurrent updates using JPA optimistic locking.
- Eliminated race conditions across more than 100 simulated users.
- Integrated Redis caching and reduced database read load by approximately 60%.
- Implemented JWT authentication and CI/CD pipelines.
- Deployed in AWS cloud

## Education

- National Institute of Technology Karnataka, Surathkal
- Bachelor of Technology in Computer Science
- November 2020 — April 2024

## Skills explicitly present in the resume

- Languages: Java, Python, C/C++, SQL, PostgreSQL, MySQL, JavaScript, HTML/CSS.
- Frameworks/libraries: Spring Boot, React.js, Flask, Node.js, JUnit, JPA.
- Tools/platforms: Git, Docker, Kafka, Redis, CI/CD.
- Concepts: API design patterns, microservices, system design, distributed systems, LLM integration, data structures and algorithms, event-driven architecture, stateless architecture, OAuth2, concurrency and locking, database optimization.

## Facts requiring confirmation or enrichment

- Exact responsibilities and contributions for each project.
- Testing, deployment, cloud, observability, and ownership details not present in the resume.
- Specific database technologies used in each Oracle project.
- Exact LLM providers, model names, and infrastructure used for the AI agents.
- Team size, leadership, collaboration, and design-review responsibilities.
- Any additional projects, accomplishments, metrics, or technologies.
