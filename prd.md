# Atlas Product Requirements Document

**Document type:** Product Requirements Document (PRD)  
**Product:** Atlas  
**Status:** Draft for requirements review and OpenSpec decomposition  
**Version:** 0.1.0  
**Prepared:** 2026-07-11  
**Primary operator:** Single-user, self-hosted deployment  
**Target host:** 16 GB ARM64 Raspberry Pi with 256 GB NVMe storage  

---

## 1. Document purpose

This document defines the product requirements, constraints, validation gates, delivery phases, and acceptance criteria for Atlas.

Atlas is a self-hosted Hermes-based agent that must:

1. remember durable details from prior interactions;
2. answer Bittensor questions using a validated local knowledge base;
3. track the official Bittensor mainnet source repository for changes;
4. retrieve current Bittensor data from TaoStats and TaoSwap on demand;
5. fail closed when current data cannot be verified;
6. expose health, freshness, and integration status for monitoring;
7. support Telegram communication and later alerting;
8. remain permanently incapable of trading, signing, or accessing wallet secrets.

This PRD is intended to be provided to OpenSpec and decomposed into small, reviewable change proposals. It is not permission to implement unresolved decisions. Every item marked **TBD**, **unverified**, or **decision required** must be resolved or explicitly deferred before the affected phase begins.

---

## 2. Requirement language and evidence states

The terms **SHALL**, **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are normative.

Atlas shall use the following evidence states:

- **Confirmed:** Directly validated against an authoritative source or successful live contract test.
- **Confirmed historical:** Valid for a stated historical date, block, release, or commit.
- **Superseded:** Previously valid but replaced by newer confirmed information.
- **Conflicting:** Two or more sources disagree and the conflict has not been resolved.
- **Unverified:** Plausible information that has not passed validation.
- **Unavailable:** Required evidence or live data could not be obtained.
- **Inference:** A conclusion derived from confirmed facts, clearly distinguished from those facts.
- **Web lead:** Information found through general web research. It is not a fact and has the lowest trust level.

Atlas MUST NOT convert an unverified statement, inference, or web lead into a confirmed fact without validation.

---

## 3. Product summary

Atlas will run locally on the existing Raspberry Pi and use Hermes Agent as the conversational and orchestration layer.

Atlas will provide Hermes with a narrow local tool interface for:

- validated Bittensor knowledge retrieval;
- exact source and provenance retrieval;
- official mainnet repository status and change summaries;
- authenticated TaoStats and TaoSwap queries;
- service and device health;
- later, view-only portfolio observations and notification rules.

The initial product is not an investment system. The initial product is an accurate Bittensor knowledge and data agent. Investment analysis, watchlists, portfolio views, and alerts are deferred until the knowledge, provenance, freshness, and operational foundations are proven.

---

## 4. Problem statement

A general-purpose LLM cannot be trusted to maintain current and precise knowledge of Bittensor from model weights or unrestricted web search. Bittensor protocol behavior, subnet data, runtime logic, repository state, and third-party API schemas can change.

Atlas must solve four separate problems:

1. **Durable personal recall:** Hermes must remember useful details and retrieve prior conversations without treating every past statement as permanently correct.
2. **Validated domain grounding:** Bittensor knowledge supplied as of July 2026 must be checked, classified, indexed, and made retrievable with provenance.
3. **Change awareness:** The official mainnet source repository must be fully cloned and monitored so Atlas can identify changes after the initial knowledge snapshot.
4. **Truthful current data:** TaoStats and TaoSwap must be queried when current data is requested. Failed, stale, malformed, or schema-incompatible data must never be presented as live.

---

## 5. Non-negotiable product principles

### 5.1 Validate before building

Atlas MUST NOT implement TaoStats or TaoSwap integrations from documentation assumptions alone.

Before adapter implementation, the project MUST perform authenticated test calls, capture actual responses, confirm authentication behavior, validate timestamp semantics, observe errors, and compare observed structures to published documentation or OpenAPI definitions.

### 5.2 Fail closed for live data

When the user asks for current, live, latest, real-time, or now data:

- Atlas MUST attempt a fresh provider call.
- Atlas MUST validate the response.
- Atlas MUST disclose the retrieval time and upstream time or block when available.
- Atlas MUST return **live data unavailable** if the call fails, times out, exceeds the rate limit, returns an invalid response, or cannot establish freshness.
- Atlas MUST NOT silently use cached data.
- Atlas MUST NOT label cached data as live.

### 5.3 No autonomous financial execution

Atlas MUST NOT:

- execute trades;
- submit swaps;
- sign transactions;
- hold, request, import, or store wallet mnemonics, seeds, private keys, signing devices, or keystore passwords;
- expose wallet write operations through Hermes, MCP, Telegram, a frontend, scripts, or internal APIs;
- propose an implementation path that introduces transaction signing as a future phase.

View-only portfolio tracking may later use public addresses only.

### 5.4 Web information is not authoritative

General web search MAY be used to locate possible sources or identify subjects requiring further validation.

Web results MUST:

- be labelled as web leads;
- receive the lowest trust level;
- remain outside the confirmed knowledge base;
- never be presented as fact unless separately confirmed by an authoritative source;
- never override confirmed repository, supplied-corpus, or validated API evidence.

### 5.5 No hidden assumptions

Unknown values MUST remain explicit. The implementation MUST NOT invent API URLs, field names, refresh intervals, retention periods, model providers, credentials, network exposure rules, or data semantics.

### 5.6 Keep the architecture proportionate

Atlas is a single-user system on one device. The initial implementation SHOULD prefer the fewest components that satisfy correctness and recoverability.

A distributed system, message broker, Kubernetes cluster, multi-node database, event-sourcing platform, or separate microservice per capability is out of scope unless later evidence proves it necessary.

---

## 6. Product goals

### 6.1 Primary goals

1. Install and operate a supported Hermes Agent deployment on the Pi.
2. Provide reliable cross-session recall using Hermes memory and session history.
3. Ingest a user-supplied July 2026 Bittensor knowledge corpus only after validation.
4. Answer Bittensor questions from validated local knowledge with source provenance.
5. Maintain a non-shallow local clone of the confirmed official mainnet repository.
6. Detect, record, and summarize repository changes without claiming semantic impact that has not been verified.
7. Validate TaoStats and TaoSwap contracts using real authenticated calls before implementing adapters.
8. Retrieve and clearly report current data on demand.
9. Refuse to present stale or unvalidated data as current.
10. Provide operational status for the Pi, Hermes, Atlas, repository tracking, knowledge ingestion, and external APIs.
11. Support Telegram as a controlled communication and notification channel.
12. Deliver through small, gated phases with documented acceptance evidence.

### 6.2 Secondary goals

1. Support manual review of memory candidates and knowledge conflicts.
2. Maintain a reproducible record of where each answer came from.
3. Support later view-only portfolio tracking using public wallet addresses.
4. Support later Bittensor watchlists and alert rules.
5. Support later investment research outputs without autonomous action.

---

## 7. Non-goals

The following are explicitly out of scope:

- Hosting a Bittensor lite node, archive node, validator, miner, subnet node, or any other Bittensor node.
- Compiling or executing Subtensor as a node requirement.
- Autonomous trading, transaction submission, swapping, staking, unstaking, transfers, registration, voting, or signing.
- Storing wallet secrets in any form.
- Treating a model response as evidence.
- Treating general web search as factual grounding.
- Automatically trusting the supplied July 2026 corpus.
- Building investment scoring before core knowledge and live-data accuracy are accepted.
- Building the frontend before core services expose stable health and status contracts.
- Supporting multiple users, organizations, tenants, or role hierarchies in the initial system.
- High availability across multiple machines.
- Public internet exposure by default.
- Replacing all human judgement with automatic confidence scores.

---

## 8. User and operating context

### 8.1 Primary user

Atlas has one operator and one intended user.

The primary user needs to:

- ask Bittensor questions conversationally;
- receive answers tied to confirmed sources;
- request current subnet and market information;
- understand when current data is unavailable;
- see what Atlas remembers;
- review proposed memories and knowledge conflicts;
- inspect repository freshness;
- receive Telegram notifications;
- monitor Pi and service health;
- later monitor public-address portfolio data and investment alerts.

### 8.2 Administrator

The same person acts as administrator and must be able to:

- inspect the current Pi state;
- approve removal of stale software and data;
- configure secrets outside source control;
- trigger ingestion and re-indexing;
- approve deletion of the original bulk knowledge file;
- view audit records;
- restore from backup;
- disable integrations independently;
- update Hermes and Atlas through documented procedures.

---

## 9. Confirmed external facts and current verification status

This section records facts verified while preparing this PRD. These facts must be rechecked during Phase 0 because external systems can change.

### 9.1 OpenSpec

Confirmed on 2026-07-11:

- OpenSpec is a lightweight spec-driven framework.
- Its current workflow creates proposal, specification, design, and task artifacts.
- Requirements are expressed with normative statements and scenarios.
- The official repository documents `openspec init` and `/opsx:propose` as the current bootstrap path.

References:

- https://openspec.dev/
- https://github.com/Fission-AI/OpenSpec/

### 9.2 Hermes Agent

Confirmed on 2026-07-11 from official Hermes documentation:

- Linux aarch64 is listed as Tier 1 support.
- Docker aarch64 is also listed as Tier 1.
- Hermes persistent memory consists of bounded `MEMORY.md` and `USER.md` files.
- Hermes stores session history in SQLite with FTS5 session search.
- Hermes can require approval for memory and skill writes.
- Hermes supports local stdio and remote HTTP MCP servers.
- Hermes supports per-server tool filtering.

References:

- https://hermes-agent.nousresearch.com/docs/getting-started/platform-support
- https://hermes-agent.nousresearch.com/docs/getting-started/installation
- https://hermes-agent.nousresearch.com/docs/user-guide/features/memory
- https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp

### 9.3 Bittensor mainnet repository

Confirmed on 2026-07-11 through GitHub repository metadata:

- Repository: `RaoFoundation/subtensor`
- Clone URL: `https://github.com/RaoFoundation/subtensor.git`
- Default branch: `main`
- Repository is public and not archived.

This identity MUST be revalidated during Phase 0 before cloning. Atlas MUST NOT hard-code a repository identity solely because it appears in this PRD.

Reference:

- https://github.com/RaoFoundation/subtensor

### 9.4 TaoStats

Confirmed from public TaoStats documentation:

- TaoStats provides Bittensor ecosystem data.
- An API key is required.
- Its documentation advertises an agent-readable index and OpenAPI endpoint descriptions.

Not yet confirmed:

- the user account's actual base URL and authentication behavior;
- the exact rate-limit response headers;
- the reported limit of 5 calls per minute and 10,000 calls per month;
- endpoint schemas required by Atlas;
- timestamp and block semantics;
- pagination behavior;
- error response schemas.

These remain unverified until authenticated calls are made with the user's key.

Reference:

- https://docs.taostats.io/reference/welcome-to-the-taostats-api

### 9.5 TaoSwap

No TaoSwap API base URL, official documentation URL, OpenAPI document, or credentials were provided with this PRD request.

The reported properties of a free API key and no rate limits remain unverified. No implementation requirement may assume them.

---

## 10. High-level product boundary

Atlas consists of the following logical components:

1. **Hermes Agent** — conversation, model interaction, personal memory, session recall, Telegram connection, and tool orchestration.
2. **Atlas local service** — validated Bittensor search, source retrieval, repository status, API adapters, and system health.
3. **Atlas knowledge store** — validated documents, source metadata, fact status, conflicts, and retrieval index.
4. **Subtensor repository clone** — complete local Git history and tracked main branch.
5. **Integration adapters** — TaoStats and TaoSwap, implemented only after contract validation.
6. **Operational storage** — configuration, logs, audit records, API response metadata, and backups.
7. **Frontend** — deferred monitoring interface built after stable backend status contracts exist.

The initial deployment SHOULD be a monolithic local Atlas application plus Hermes and a local database. Internal modules may be separated in code without being deployed as separate services.

---

## 11. Source authority and response rules

### 11.1 Source categories

Atlas shall classify sources by category rather than assign false-precision numeric confidence.

#### A. Validated live provider response

Used for current values supplied by TaoStats or TaoSwap after successful schema and freshness validation.

#### B. Official repository evidence

Used for source code, commit history, tags, releases, and repository changes.

#### C. Validated supplied corpus

Used for Bittensor concepts and information confirmed during ingestion.

#### D. Official documentation

Used when the document is confirmed official, versioned where possible, and not contradicted by newer repository or live evidence.

#### E. Unverified external material

Includes general web results, social posts, articles, community pages, and unsupported claims. These are web leads only.

### 11.2 Precedence

Precedence depends on the claim type:

- Current numerical value: validated live provider response.
- Current source implementation: current official repository commit.
- Historical source behavior: repository state at the relevant commit.
- General explanatory knowledge: validated corpus and official documentation with dates.
- Unresolved or emerging subject: clearly labelled web leads and request for confirmation.

Atlas MUST NOT apply a universal source order where a source is inappropriate for the claim type.

### 11.3 Mandatory answer metadata

Every Bittensor answer based on Atlas knowledge SHALL be capable of returning:

- answer text;
- evidence state;
- source title or identifier;
- source type;
- source date, commit, block, or retrieval time when available;
- a direct evidence excerpt or structured value when permitted;
- whether the answer includes an inference;
- whether conflicting evidence exists.

The normal conversational answer may be concise, but the provenance must be retrievable on request and included automatically for high-impact or time-sensitive claims.

### 11.4 Prohibited answer behavior

Atlas MUST NOT:

- use phrases such as “live,” “current,” or “latest” without a successful freshness check;
- hide provider failure behind a generic answer;
- merge conflicting claims into a single synthetic fact;
- cite a source that does not support the claim;
- treat a repository change summary generated by an LLM as proof of runtime effect;
- answer from model memory when Atlas has relevant authoritative data available;
- fabricate missing units, timestamps, decimals, field meanings, or block numbers.

---

### 12. Functional requirements

### 12.1 Phase 0 environment discovery and reset

### ATLAS-ENV-001 — Device inventory

The system SHALL produce a pre-change inventory of the Pi containing:

- hardware model and architecture;
- CPU, RAM, NVMe capacity, partitions, and filesystem usage;
- operating system and kernel versions;
- configured users and service accounts;
- installed packages relevant to Atlas;
- containers and images;
- systemd services;
- listening ports;
- scheduled jobs and timers;
- existing Hermes files and version, if present;
- existing repositories and application directories;
- environment files and secret locations without printing secret values;
- backup configuration;
- firewall status;
- remote access configuration;
- temperature and NVMe health where supported.

#### Scenario: Existing state is stale

- GIVEN the Pi contains existing Hermes or Bittensor-related software
- WHEN the inventory completes
- THEN Atlas planning SHALL classify each item as preserve, migrate, remove, or decision required
- AND no item SHALL be deleted automatically
- AND the user SHALL receive a removal plan before destructive action.

### ATLAS-ENV-002 — Clean baseline

The implementation SHALL support removing stale Atlas-related software and data after explicit approval.

The removal process SHALL:

- identify exact paths and services;
- distinguish generated data from user-owned data;
- back up required state before deletion;
- stop services cleanly;
- verify removal;
- produce an audit record.

### ATLAS-ENV-003 — Hardening assessment

The project SHALL assess, not assume, the current hardening state.

The assessment SHALL cover:

- unprivileged service execution;
- SSH authentication and exposed ports;
- firewall rules;
- unattended security updates or documented update process;
- secret file permissions;
- log permissions;
- backup encryption and destination;
- service restart policy;
- time synchronization;
- disk space thresholds;
- remote frontend exposure.

A hardening change SHALL be proposed only after current state is observed.

---

### 12.2 Hermes installation and baseline behavior

### ATLAS-HERMES-001 — Supported installation

Hermes SHALL be installed using a currently supported official method for Linux aarch64.

The selected method SHALL be recorded with:

- install source;
- installed version or commit;
- installation date;
- update method;
- rollback method;
- service user;
- data directory;
- configuration path.

### ATLAS-HERMES-002 — Unprivileged execution

Hermes SHOULD run as a dedicated unprivileged account unless Phase 0 establishes a documented reason not to.

Hermes MUST NOT require general sudo access during normal operation.

### ATLAS-HERMES-003 — Model provider validation

No LLM provider or model is selected by this PRD.

Before production use, the selected provider and model SHALL be validated for:

- Hermes compatibility;
- tool calling reliability;
- context window sufficiency;
- privacy implications;
- operating cost;
- latency;
- Bittensor retrieval benchmark performance;
- refusal to invent unavailable live data.

The model SHALL be replaceable through configuration without changing Atlas data contracts.

### ATLAS-HERMES-004 — Tool minimization

Hermes SHALL only receive the Atlas tools required for the current phase.

Mutating filesystem, arbitrary shell, generic database write, wallet, swap, and transaction tools MUST NOT be exposed for routine Atlas operation.

### ATLAS-HERMES-005 — Diagnostic baseline

A Hermes installation SHALL not be considered accepted until:

- official diagnostics pass or exceptions are documented;
- a basic chat succeeds;
- a local Atlas test tool can be discovered and called;
- memory and session search behavior are verified;
- restart behavior is verified;
- logs do not contain secrets.

---

### 12.3 Personal memory and conversation recall

### ATLAS-MEM-001 — Separation of personal memory and domain knowledge

Hermes built-in memory SHALL contain only compact durable information such as:

- user preferences;
- communication preferences;
- machine environment facts;
- recurring workflows;
- confirmed project conventions;
- durable corrections.

Hermes built-in memory MUST NOT contain the Bittensor corpus, API data dumps, repository contents, price history, or large summaries.

### ATLAS-MEM-002 — Session recall

Hermes session history SHALL remain searchable across sessions.

The system SHALL verify that a user can ask about a prior discussion and Hermes can locate the relevant session text.

### ATLAS-MEM-003 — Memory write review

Initial deployment SHALL enable approval for Hermes memory and skill writes.

The system SHALL:

- allow Hermes to propose a memory automatically;
- show the proposed content;
- allow approve or reject;
- record the decision;
- prevent rejected content from entering active memory.

Automatic unreviewed memory writes MAY be enabled later only by an explicit user decision after memory accuracy has been evaluated.

### ATLAS-MEM-004 — Correction handling

When the user corrects a remembered item:

- Hermes SHALL propose replacing or removing the old memory;
- the old and new values SHALL be visible during review;
- the correction SHALL not silently create two contradictory active memories.

### ATLAS-MEM-005 — No secret memory

Hermes and Atlas MUST reject memory candidates containing:

- API keys;
- Telegram bot tokens;
- passwords;
- private keys;
- seed phrases;
- authentication cookies;
- bearer tokens;
- secret environment values.

### ATLAS-MEM-006 — Memory evaluation

Before optional automatic writes are considered, memory behavior SHALL pass a defined test set covering:

- preference retention;
- correction replacement;
- stale-memory removal;
- duplicate prevention;
- prior-session lookup;
- secret rejection;
- separation of personal memory from Bittensor facts.

---

### 12.4 Bittensor corpus intake and validation

### ATLAS-KB-001 — Controlled corpus intake

The user will provide one or more large Markdown files representing Bittensor knowledge as of July 2026.

Atlas SHALL treat all supplied content as unverified input until validation completes.

The intake process SHALL record:

- filename;
- byte size;
- cryptographic hash;
- intake date;
- declared coverage date;
- declared source list, if present;
- parser version;
- validation run identifier.

### ATLAS-KB-002 — Structure discovery

Before chunking or indexing, Atlas SHALL analyze the corpus structure and report:

- headings and hierarchy;
- embedded source references;
- code blocks;
- tables;
- duplicated sections;
- likely unsupported claims;
- date-sensitive claims;
- statements that require API or repository validation;
- malformed or ambiguous sections.

### ATLAS-KB-003 — Claim classification

The validation process SHALL classify material into at least:

- concepts and definitions;
- current protocol behavior;
- historical protocol behavior;
- repository-derived implementation detail;
- subnet-specific information;
- numerical or market data;
- operational instructions;
- opinion or analysis;
- unsupported claim;
- duplicate;
- contradiction.

### ATLAS-KB-004 — Validation rules

A claim may be marked confirmed only when the validator records supporting evidence appropriate to the claim.

Examples:

- a source-code behavior requires a repository commit and file reference;
- a current API field requires a successful provider response and field semantics;
- an official process requires current official documentation;
- a historical fact requires a source tied to the relevant date or block;
- a general web article alone cannot confirm a claim.

### ATLAS-KB-005 — Validation output

The validation run SHALL produce a reviewable report containing:

- confirmed sections;
- confirmed historical sections;
- superseded statements;
- conflicting statements;
- unverified statements;
- web leads;
- parsing failures;
- missing source references;
- proposed exclusions;
- exact counts by classification.

### ATLAS-KB-006 — User approval before activation

Validated knowledge SHALL not become the active production knowledge base until the user approves the validation report or an approved subset.

### ATLAS-KB-007 — Original bulk file deletion gate

Atlas MUST NOT delete the original bulk Markdown automatically.

Deletion SHALL require all of the following:

1. intake hash recorded;
2. validation completed;
3. approved knowledge activated;
4. retrieval test suite passed;
5. export or backup of the resulting knowledge store completed;
6. deletion plan shown to the user;
7. explicit user approval;
8. deletion verified and audited.

Whether an encrypted archival copy is retained outside the Pi is a decision required from the user.

### ATLAS-KB-008 — Provenance-preserving storage

Each indexed knowledge unit SHALL preserve:

- source document identifier;
- source heading path;
- original text range or stable locator;
- validation status;
- supporting evidence references;
- coverage date;
- supersession links;
- ingestion and validator versions.

### ATLAS-KB-009 — No silent overwrite

When new information contradicts active knowledge, Atlas SHALL retain both records, mark the conflict, and prevent either from being returned as unqualified confirmed fact until resolved.

### ATLAS-KB-010 — Temporal knowledge

Atlas SHALL distinguish:

- “is true now”;
- “was true as of a date”;
- “was implemented at a commit”;
- “was observed at a block or API retrieval time.”

Retrieval SHALL not collapse these into one timeless statement.

---

### 12.5 Knowledge retrieval and answer generation

### ATLAS-RET-001 — Local retrieval first

For Bittensor questions, Hermes SHALL query Atlas before relying on model memory or web search.

### ATLAS-RET-002 — Minimal retrieval architecture

The initial retrieval implementation SHOULD use a local, inspectable database and full-text search.

Semantic/vector retrieval MAY be added only if a documented retrieval benchmark demonstrates that full-text and structured lookup are insufficient.

The choice of database and optional embedding model SHALL be confirmed in technical design after Phase 0 resource measurements.

### ATLAS-RET-003 — Source-bound answers

Atlas SHALL return evidence alongside retrieved content so Hermes can answer from sources rather than from an untraceable generated summary.

### ATLAS-RET-004 — Insufficient evidence response

When confirmed evidence is insufficient, Atlas SHALL say so.

It SHALL NOT fill the gap with model knowledge.

### ATLAS-RET-005 — Conflicting evidence response

When evidence conflicts, Atlas SHALL:

- state that a conflict exists;
- identify the conflicting sources;
- state the relevant dates, commits, or blocks;
- avoid selecting a winner without a defined validation basis;
- allow the user to request deeper validation.

### ATLAS-RET-006 — Answer mode

Atlas SHALL support at least:

- concise answer;
- answer with sources;
- evidence detail;
- historical as-of query;
- repository implementation query;
- current-data query.

### ATLAS-RET-007 — Retrieval evaluation

The knowledge system SHALL be tested with a curated benchmark that includes:

- exact factual questions;
- synonyms and paraphrases;
- historical questions;
- conflicting claims;
- unsupported questions;
- questions requiring repository evidence;
- questions requiring live data;
- adversarial requests to treat stale data as live.

The benchmark and pass threshold are decisions required before Phase 2 acceptance.

---

### 12.6 Official mainnet repository clone and tracking

### ATLAS-REPO-001 — Repository identity validation

Before cloning, the project SHALL confirm:

- repository owner and name;
- canonical clone URL;
- default branch;
- whether the repository has moved or been archived;
- whether a different branch or release represents mainnet.

Any uncertainty SHALL block repository setup.

### ATLAS-REPO-002 — Full clone

Atlas SHALL maintain a non-shallow Git clone with complete reachable history for the tracked official repository.

Atlas will not host or run a Bittensor node.

### ATLAS-REPO-003 — Read-only agent access

Hermes SHALL access repository information through Atlas read-only tools.

Hermes MUST NOT receive permission to push, rewrite history, modify remotes, delete branches, or commit changes in the tracked repository.

### ATLAS-REPO-004 — Update process

The update process SHALL:

- verify network and remote identity;
- fetch remote changes and tags;
- record previous and new tracked commit SHAs;
- determine whether the tracked branch changed;
- preserve the last successful local state on failure;
- record fetch start, finish, status, and error;
- update the working tree only through a safe fast-forward or deterministic reset to the confirmed remote branch;
- never merge local changes into the tracked branch;
- detect unexpected local modifications.

The update interval remains TBD and SHALL be configurable rather than hard-coded.

### ATLAS-REPO-005 — Change record

For every tracked commit range, Atlas SHALL record:

- previous SHA;
- new SHA;
- commit list;
- changed file paths;
- additions and deletions where available;
- tags or releases encountered;
- retrieval timestamp;
- whether indexing succeeded;
- a machine-generated summary clearly labelled as a summary, not proof of effect.

### ATLAS-REPO-006 — Incremental indexing

Atlas SHOULD re-index changed files only, unless a schema or parser change requires a full rebuild.

### ATLAS-REPO-007 — Repository freshness response

Atlas SHALL be able to answer:

- local tracked SHA;
- remote tracked SHA from the last successful fetch;
- last fetch attempt;
- last successful fetch;
- last detected update;
- whether the working tree is clean;
- whether indexing matches the local SHA;
- whether repository status is stale based on the configured policy.

### ATLAS-REPO-008 — Repository failure behavior

If GitHub or the remote is unavailable, Atlas SHALL report repository status as unavailable or stale. It SHALL NOT claim the local clone is current.

### ATLAS-REPO-009 — No routine build requirement

Subtensor compilation is not required for normal Atlas operation.

A targeted build or test MAY be performed manually during a specific validation task if the Pi resources and source support are first confirmed. It SHALL not become a scheduled job without a separate approved specification.

---

### 12.7 API contract discovery and validation

### ATLAS-API-001 — Required user inputs

Before contract discovery, the user SHALL supply or approve access to:

- TaoStats API documentation or confirmed base URL;
- TaoStats API key;
- TaoSwap API documentation or confirmed base URL;
- TaoSwap API key;
- endpoints or data categories needed for the first release;
- permission to perform safe test calls.

Secrets SHALL be provided through a secure local process and MUST NOT be written into this PRD, source control, logs, screenshots, or chat history.

### ATLAS-API-002 — Real call requirement

No production adapter SHALL be built until a contract-validation script has made successful authenticated calls to the actual service.

### ATLAS-API-003 — Contract discovery report

For each provider, the project SHALL document:

- canonical base URL;
- TLS behavior;
- authentication header or parameter;
- required headers;
- relevant endpoints;
- request parameters and types;
- success status codes;
- error status codes;
- response content type;
- observed response schema;
- documented response schema;
- differences between observed and documented schema;
- nullability and optional fields;
- pagination;
- units and decimal precision;
- timestamps and timezone;
- block numbers or chain reference where provided;
- rate-limit headers and behavior;
- timeout behavior;
- malformed or partial-response behavior;
- terms affecting storage and caching.

### ATLAS-API-004 — Multiple sample validation

Schema confirmation SHALL use more than one valid response when the endpoint can return materially different shapes, empty lists, null values, pagination, or optional fields.

### ATLAS-API-005 — Safe negative tests

Contract discovery SHOULD test, where safe:

- missing authentication;
- invalid authentication;
- missing required parameter;
- invalid parameter value;
- nonexistent resource;
- empty result;
- timeout or connection failure through a controlled test path.

The project MUST NOT intentionally exhaust the user's monthly quota or trigger abuse protections.

### ATLAS-API-006 — Generated or typed validation

The adapter SHALL validate every production response against explicit typed models or JSON Schema derived from confirmed documentation and observed responses.

Schema validation MUST occur before values are exposed to Hermes.

### ATLAS-API-007 — Schema drift

If a provider response no longer validates:

- the request SHALL fail closed;
- the raw response metadata MAY be retained according to the retention policy;
- the response body SHALL not be exposed as trusted data;
- Atlas SHALL create an integration health event;
- Atlas SHALL report schema drift rather than guessing a mapping.

### ATLAS-API-008 — Secret handling

Provider keys SHALL:

- be stored outside source control;
- be readable only by the service account that needs them;
- be redacted from logs and errors;
- never be returned by an Atlas tool;
- never be stored in Hermes memory;
- be independently rotatable.

---

### 12.8 Live-data behavior

### ATLAS-LIVE-001 — Explicit live request

A request containing terms such as current, latest, live, real-time, now, present, or today SHALL be treated as requiring a fresh provider call unless the user explicitly requests a historical or cached snapshot.

### ATLAS-LIVE-002 — Freshness envelope

Each endpoint SHALL have a configured freshness policy based on confirmed provider semantics.

The policy SHALL define:

- whether each request must hit the provider;
- maximum accepted upstream timestamp age;
- maximum accepted local request age;
- required block information, if applicable;
- whether provider caching is documented;
- expected update frequency.

No freshness threshold shall be invented before the provider contract is understood.

### ATLAS-LIVE-003 — Required live response metadata

A successful live result SHALL include:

- provider;
- endpoint or logical operation;
- request completion time;
- upstream timestamp where available;
- block number or chain reference where available;
- units;
- validation status;
- freshness status.

### ATLAS-LIVE-004 — No stale substitution

If a live request fails, Atlas SHALL return an unavailable result.

It MAY separately state that a historical snapshot exists, but SHALL not include it unless clearly labelled and the user asks to see it.

### ATLAS-LIVE-005 — Provider disagreement

If TaoStats and TaoSwap provide comparable values and disagree beyond a configured or domain-defined tolerance:

- Atlas SHALL return both values with source metadata;
- mark the result conflicting;
- avoid selecting one as correct without a validation rule;
- log the discrepancy.

### ATLAS-LIVE-006 — TaoStats quota management

The TaoStats adapter SHALL enforce a local quota budget after the real limits are confirmed.

The budget SHALL:

- prevent exceeding confirmed per-minute and monthly limits;
- persist usage across restarts;
- reserve capacity for interactive user requests if the user approves such a policy;
- expose remaining known capacity;
- distinguish local estimates from provider-reported limits;
- fail visibly when capacity is unavailable.

The reported 5 calls per minute and 10,000 calls per month are requirements inputs, not confirmed facts, until tested.

### ATLAS-LIVE-007 — TaoSwap rate behavior

Atlas MUST NOT assume TaoSwap has no rate limit.

Rate behavior SHALL be documented from official terms, response headers, and safe observed calls before concurrency or polling is configured.

### ATLAS-LIVE-008 — Retry policy

Retries SHALL be bounded and endpoint-specific.

Atlas MUST NOT perform hidden retry storms or consume TaoStats quota excessively.

Retry attempts and final failure SHALL be observable.

### ATLAS-LIVE-009 — Raw response retention

Whether complete raw API response bodies are retained is TBD.

At minimum Atlas SHALL retain enough metadata to audit:

- provider;
- operation;
- request parameters after secret redaction;
- request and response times;
- status code;
- schema version;
- validation result;
- response hash;
- error category.

---

### 12.9 General web research

### ATLAS-WEB-001 — Disabled by default for factual answers

General web search SHALL not be required for normal Bittensor answers when validated local or live sources exist.

### ATLAS-WEB-002 — Web lead labelling

Any web-derived item SHALL be labelled “unverified web lead” and include retrieval date and source domain.

### ATLAS-WEB-003 — No automatic trusted ingestion

Web content SHALL not enter the confirmed knowledge base automatically.

### ATLAS-WEB-004 — Confirmation workflow

A web lead may become confirmed only after it is independently validated using an appropriate authoritative source and approved according to the knowledge workflow.

### ATLAS-WEB-005 — Prompt-injection resistance

Web pages and imported documents SHALL be treated as untrusted data, not instructions.

Atlas SHALL prevent text inside sources from changing system policy, tool permissions, or secret-handling behavior.

---

### 12.10 Atlas tool interface for Hermes

The exact protocol may be MCP or another Hermes-supported local tool interface, subject to Phase 0 validation. MCP is the preferred current path because official Hermes documentation supports local servers and tool filtering.

### ATLAS-TOOL-001 — Read-only initial tool set

The initial production tool set SHALL be read-only except for explicitly approved memory-review or administrative actions.

Candidate operations:

- `knowledge_search`
- `knowledge_get_evidence`
- `knowledge_get_conflicts`
- `repo_get_status`
- `repo_get_changes`
- `live_get_taostats`
- `live_get_taoswap`
- `system_get_health`
- `integration_get_status`

Names and schemas are design details and MUST be finalized through OpenSpec capability specifications.

### ATLAS-TOOL-002 — Structured errors

Every tool SHALL return structured errors including:

- error category;
- provider or component;
- whether retry is safe;
- whether data is unavailable, stale, invalid, or unauthorized;
- user-safe message;
- internal correlation identifier.

### ATLAS-TOOL-003 — No generic execution surface

Atlas SHALL not expose arbitrary SQL, shell commands, unrestricted file reads, HTTP requests, or Git mutation through its production Hermes tools.

### ATLAS-TOOL-004 — Auditability

Tool calls SHALL be auditable without logging secrets or unnecessary conversation content.

---

### 12.11 Telegram communication

### ATLAS-TG-001 — Telegram integration validation

Telegram integration SHALL use the supported Hermes gateway mechanism available at implementation time and be validated against current official Hermes documentation.

### ATLAS-TG-002 — Access restriction

The Telegram bot SHALL accept commands only from explicitly approved account or chat identifiers.

Unknown users SHALL receive no operational data.

### ATLAS-TG-003 — Supported initial use

Initial Telegram scope MAY include:

- conversation with Hermes;
- service failure notifications;
- repository update notifications;
- API schema-drift notifications;
- knowledge-ingestion completion or review-needed notifications.

Investment alerts are deferred.

### ATLAS-TG-004 — Sensitive output

Telegram messages MUST NOT contain:

- API keys;
- secret paths with values;
- environment dumps;
- private system diagnostics that exceed the approved exposure policy;
- wallet secrets, which Atlas must never possess.

### ATLAS-TG-005 — Delivery semantics

Notifications SHALL record:

- event identifier;
- creation time;
- attempted delivery time;
- delivery status;
- retry count;
- final failure.

The system MUST avoid duplicate alert floods.

### ATLAS-TG-006 — Command permissions

Telegram commands SHALL be explicitly allowlisted.

Destructive system administration over Telegram is out of scope for the initial release.

---

### 12.12 Operational monitoring and frontend

### ATLAS-OPS-001 — Machine-readable health contract

Before a frontend is built, Atlas SHALL expose a stable local health/status contract.

### ATLAS-OPS-002 — Device health

Health data SHOULD include, where supported and validated:

- uptime;
- CPU load;
- CPU temperature;
- memory use;
- swap use;
- disk capacity and free space;
- NVMe health;
- network connectivity;
- time synchronization.

### ATLAS-OPS-003 — Service health

Health data SHALL include:

- Hermes status and version;
- Atlas status and version;
- knowledge database status;
- last successful backup;
- current storage use;
- repository clone status;
- last repository fetch attempt and success;
- repository/index SHA alignment;
- TaoStats connectivity and quota state;
- TaoSwap connectivity and rate state;
- Telegram connectivity;
- unresolved schema drift;
- unresolved knowledge conflicts;
- pending memory reviews.

### ATLAS-OPS-004 — Status truthfulness

A green or healthy state SHALL only be shown when the relevant check has run successfully within its configured interval.

Unknown or overdue checks SHALL display unknown or stale, not healthy.

### ATLAS-OPS-005 — Initial frontend scope

The first frontend SHALL be monitoring-only.

It SHALL not include trading, signing, wallet import, swap execution, or investment recommendations.

### ATLAS-OPS-006 — Frontend exposure

Network exposure, authentication, TLS, and remote-access method are decisions required before frontend implementation.

The frontend MUST NOT be publicly exposed by default.

### ATLAS-OPS-007 — Responsive and low-overhead operation

The frontend and health collection SHALL not materially degrade Hermes responsiveness or exceed Pi resource budgets defined during Phase 0.

---

### 12.13 Backup, restore, and data lifecycle

### ATLAS-BACKUP-001 — Backup scope

Backups SHALL include, as applicable:

- Atlas source and configuration excluding recoverable dependencies;
- Hermes configuration and approved memories;
- Atlas knowledge store;
- validation reports;
- repository tracking metadata, but not necessarily the reproducible Git clone;
- audit data;
- Telegram and API configuration without exposing secrets in plaintext;
- secret files only through an approved encrypted method;
- frontend configuration.

### ATLAS-BACKUP-002 — External backup target

A backup stored only on the same NVMe is not sufficient.

The user must select an external or remote encrypted backup destination before production acceptance.

### ATLAS-BACKUP-003 — Restore test

A backup process is not accepted until a restore test succeeds into an isolated location and verifies:

- knowledge retrieval;
- configuration integrity;
- memory integrity;
- repository metadata;
- service startup.

### ATLAS-BACKUP-004 — Retention policy

Retention periods for logs, API metadata, raw API bodies, conversations, audit events, and backups remain TBD.

No component SHALL retain data indefinitely by accident.

### ATLAS-BACKUP-005 — Disk protection

Atlas SHALL monitor disk usage and prevent uncontrolled growth.

When storage thresholds are reached, Atlas SHALL stop nonessential ingestion or raw-response retention before endangering the operating system.

Thresholds SHALL be selected after Phase 0 measurements.

---

### 12.14 Security and privacy

### ATLAS-SEC-001 — Least privilege

Each service SHALL run with the least privileges required.

### ATLAS-SEC-002 — Secret isolation

Secrets SHALL be separated from code, PRD files, OpenSpec artifacts, logs, and knowledge content.

### ATLAS-SEC-003 — No wallet secret capability

The system SHALL include automated checks preventing fields or configuration names intended for wallet private keys, mnemonics, seeds, signing keys, or keystores.

Public wallet addresses MAY be supported in a later view-only phase.

### ATLAS-SEC-004 — Local binding

Atlas APIs and health endpoints SHOULD bind to localhost by default.

Any LAN or remote binding requires an explicit approved design.

### ATLAS-SEC-005 — Dependency provenance

Dependencies SHALL be pinned or locked and sourced from recorded official locations.

### ATLAS-SEC-006 — Update review

Hermes, Atlas, and dependency updates SHALL be tested before production rollout when practical.

Automatic unattended major-version updates are out of scope.

### ATLAS-SEC-007 — Log redaction

Logs SHALL redact:

- authorization headers;
- API keys;
- Telegram bot tokens;
- cookies;
- secret environment values;
- sensitive query parameters.

### ATLAS-SEC-008 — Audit events

Atlas SHALL audit:

- installation and removal actions;
- configuration changes;
- knowledge activation;
- source-file deletion;
- memory approvals and rejections;
- integration enable/disable;
- repository update results;
- schema drift;
- backup and restore results.

---

### 12.15 View-only portfolio and investment alerts — deferred

This capability MUST NOT begin until all earlier production gates pass.

### ATLAS-PORT-001 — Public addresses only

Portfolio tracking SHALL accept public addresses only.

### ATLAS-PORT-002 — No signing path

The portfolio subsystem SHALL contain no signing, transaction construction, swap submission, or wallet-unlock code.

### ATLAS-PORT-003 — Read-only holdings

The system MAY retrieve balances and positions through confirmed read-only sources.

### ATLAS-PORT-004 — Alert-only investment output

Investment-related functionality SHALL produce research, alerts, or notifications only.

### ATLAS-PORT-005 — Telegram alerts

Alerts MAY be delivered through Telegram after:

- rule evaluation is deterministic and tested;
- source freshness is confirmed;
- duplicate suppression exists;
- every alert states its data timestamp and source;
- no alert implies execution occurred.

### ATLAS-PORT-006 — No initial recommendation engine

A subnet investment scoring or recommendation engine is not part of the core Atlas release.

A separate future PRD or OpenSpec change SHALL define its metrics, evidence requirements, backtesting, risk disclosure, and acceptance criteria.

---

## 13. Conceptual data model

The exact schema is a technical-design decision. The product SHALL support the following concepts without requiring separate services for each.

### 13.1 Source

Represents an imported Markdown file, official document, repository file/commit, or validated API operation.

Required attributes:

- identifier;
- type;
- title;
- canonical location or repository locator;
- hash where applicable;
- retrieval or intake date;
- coverage date;
- authority category;
- validation status.

### 13.2 Knowledge unit

Represents a retrievable section, definition, claim, procedure, or code-derived observation.

Required attributes:

- content;
- source locator;
- evidence state;
- temporal scope;
- supporting references;
- conflict and supersession links.

### 13.3 Validation run

Represents a reproducible corpus or API validation process.

Required attributes:

- validator version;
- inputs and hashes;
- start and finish time;
- outcome;
- counts;
- errors;
- approval state.

### 13.4 Repository update

Represents a fetch and optional tracked-branch change.

Required attributes:

- remote identity;
- branch;
- prior and new SHA;
- status;
- commits and changed files;
- indexing status;
- timestamps.

### 13.5 Provider observation

Represents a validated API response or failure.

Required attributes:

- provider and operation;
- redacted parameters;
- request and response times;
- upstream time or block;
- status code;
- schema version;
- validation result;
- units;
- response hash;
- freshness result.

### 13.6 Health check

Represents a component check with status, time, latency, and failure details.

### 13.7 Audit event

Represents a security, administrative, approval, or lifecycle action.

---

### 14. Core user journeys

### 14.1 Ask a grounded Bittensor question

1. User asks Hermes a Bittensor question.
2. Hermes classifies whether the question needs local knowledge, repository evidence, live data, or multiple sources.
3. Hermes calls the appropriate Atlas tool.
4. Atlas returns confirmed evidence or an explicit insufficient/conflicting result.
5. Hermes answers using the returned evidence.
6. Sources and temporal context are included or available on request.

Success means the answer is grounded and no unsupported details are added.

### 14.2 Ask for live subnet data

1. User asks for current data.
2. Hermes calls the relevant live Atlas operation.
3. Atlas checks local rate policy and calls the provider.
4. Atlas validates status, schema, units, timestamp, and freshness.
5. Atlas returns the value and metadata.
6. If any step fails, Hermes reports live data unavailable.

Success means no stale fallback is presented as current.

### 14.3 Ingest the July 2026 knowledge corpus

1. User places the file in an approved intake location.
2. Atlas hashes and inventories the file.
3. Atlas analyzes structure and proposes a validation plan.
4. Validation runs against authoritative evidence.
5. Atlas generates a classification report.
6. User approves all or part of the corpus.
7. Atlas activates only approved knowledge.
8. Retrieval tests run.
9. Original-file deletion remains pending until explicit approval.

### 14.4 Detect a repository update

1. Scheduled or manual update begins.
2. Atlas validates the remote and fetches.
3. Atlas records the old and new SHAs.
4. Changed files are indexed.
5. Atlas generates a labelled summary.
6. Health status is updated.
7. Optional Telegram notification is sent.

### 14.5 Correct a remembered preference

1. User corrects Hermes.
2. Hermes proposes a memory replacement.
3. User reviews and approves or rejects it.
4. The active memory is updated without duplicate contradiction.

---

### 15. Non-functional requirements

### 15.1 Correctness

- Confirmed answers SHALL be traceable to evidence.
- Live values SHALL pass schema and freshness checks.
- Repository status SHALL include the commit SHA.
- Unknown values SHALL remain unknown.

### 15.2 Reliability

- A failure in TaoStats SHALL not prevent local knowledge retrieval.
- A failure in TaoSwap SHALL not prevent repository status retrieval.
- A repository fetch failure SHALL not corrupt the last successful clone state.
- A frontend failure SHALL not stop Hermes or Atlas core.

### 15.3 Performance

Specific service-level targets remain TBD until Phase 0 measures the Pi and selected model provider.

The project SHALL define targets for:

- local knowledge response time;
- health endpoint response time;
- repository status response time;
- Hermes tool-call overhead;
- memory and CPU use at idle and under load.

Live API latency is partly provider-dependent and SHALL be reported separately from Atlas processing time.

### 15.4 Resource use

Atlas SHALL operate within measured limits on the 16 GB Pi and 256 GB NVMe.

The design SHALL avoid unnecessary resident services and duplicate data stores.

### 15.5 Maintainability

- Configuration SHALL be documented.
- Database migrations SHALL be versioned.
- Adapter schemas SHALL be versioned.
- Installation and recovery SHALL be reproducible.
- Each OpenSpec change SHALL remain small enough to review and verify independently.

### 15.6 Observability

Every scheduled process and external integration SHALL expose last attempt, last success, current status, and last error.

### 15.7 Privacy

The LLM provider privacy boundary, conversation retention, and telemetry settings MUST be explicitly reviewed before production acceptance.

---

## 16. Delivery phases and gates

No phase may be considered complete based only on code completion. Each phase requires validation evidence and user acceptance.

### Phase 0 — Discovery, decisions, and contract validation

### Scope

- Inventory the Pi.
- Identify data and services to preserve or remove.
- Confirm operating system support.
- Confirm Hermes installation path.
- Confirm model provider candidates.
- Confirm mainnet repository identity.
- Obtain API docs, URLs, and keys securely.
- Run TaoStats and TaoSwap contract discovery.
- Inspect the supplied corpus format and size when available.
- Decide backup target and network exposure.
- Record resource baseline.

### Exit criteria

- Device inventory approved.
- Removal plan approved.
- Repository identity confirmed.
- TaoStats contract report completed.
- TaoSwap contract report completed.
- No unresolved blocker for Hermes installation.
- Required decisions for Phase 1 are resolved.

### Phase 1 — Clean Pi baseline and Hermes

### Scope

- Remove approved stale components.
- Apply approved hardening changes.
- Install Hermes.
- Configure selected model provider.
- Configure memory approval.
- Verify session search.
- Establish Atlas project repository and OpenSpec structure.
- Implement a minimal local Atlas health tool.

### Exit criteria

- Hermes diagnostics pass.
- Hermes restarts cleanly.
- Personal memory proposal/approval works.
- Session recall test passes.
- Atlas health tool works through Hermes.
- No secrets appear in logs.
- Backup of baseline configuration succeeds.

### Phase 2 — Validated Bittensor knowledge

### Scope

- Build corpus intake.
- Build validation workflow.
- Produce validation report.
- Implement local knowledge store.
- Implement full-text and structured retrieval.
- Create retrieval benchmark.
- Expose knowledge tools to Hermes.

### Exit criteria

- User approves active knowledge subset.
- Benchmark meets agreed threshold.
- Unsupported questions fail safely.
- Historical and current claims are distinguished.
- Conflicts are surfaced.
- Original bulk file remains until deletion gate is separately approved.

### Phase 3 — Mainnet repository tracking

### Scope

- Create full clone.
- Implement manual fetch and status.
- Implement safe scheduled update after interval decision.
- Record change ranges.
- Index changed repository files.
- Add repository-related retrieval.

### Exit criteria

- Full clone verified non-shallow.
- Remote identity verified.
- Update succeeds in normal case.
- Failure preserves last good state.
- Local/remote/index SHAs are visible.
- Hermes can answer a repository evidence question with commit and file reference.

### Phase 4 — TaoStats and TaoSwap live data

### Scope

- Implement adapters from confirmed contracts.
- Add typed validation.
- Implement quota/rate controls.
- Implement freshness rules.
- Implement fail-closed behavior.
- Add integration health.

### Exit criteria

- Successful current queries return source and time metadata.
- Invalid schema fails closed.
- Provider outage fails closed.
- Cached data is never called live.
- TaoStats quota persists across restart.
- Rate behavior matches confirmed provider contracts.

### Phase 5 — Telegram

### Scope

- Configure Hermes Telegram gateway.
- Restrict approved user/chat.
- Add operational notifications.
- Add duplicate suppression and delivery status.

### Exit criteria

- Unauthorized account is rejected.
- Approved account can query Hermes.
- Test alerts deliver once.
- No secrets are exposed.
- Telegram failure does not affect core operation.

### Phase 6 — Monitoring frontend

### Scope

- Finalize local health API.
- Build monitoring-only UI.
- Show device, service, repository, knowledge, API, Telegram, and backup state.
- Implement approved authentication and network exposure.

### Exit criteria

- UI status matches backend health states.
- Unknown and stale states are distinct from healthy.
- No write or wallet operations exist.
- UI remains usable on expected client devices.
- UI load does not breach resource budget.

### Phase 7 — View-only portfolio and alert research

### Scope

- Public-address portfolio tracking.
- Watchlists.
- Deterministic alert rules.
- Telegram alert delivery.
- Optional research views.

### Exit criteria

- No wallet secrets or signing path exist.
- Holdings are source- and timestamp-labelled.
- Alerts are reproducible and deduplicated.
- Provider failures do not produce false alerts.

Investment scoring or recommendations require a separate approved specification.

---

### 17. Test and validation strategy

### 17.1 Unit tests

Required for:

- parsers;
- source classification;
- schema validation;
- freshness evaluation;
- rate budgeting;
- repository state transitions;
- redaction;
- health-state calculation;
- conflict and supersession logic.

### 17.2 Contract tests

Required for each TaoStats and TaoSwap operation.

Contract tests SHALL be separable into:

- offline tests using captured redacted fixtures;
- opt-in live tests using real credentials.

Live tests MUST respect provider quotas.

### 17.3 Integration tests

Required paths:

- Hermes to Atlas tool discovery;
- Hermes grounded answer;
- Hermes unavailable-live-data answer;
- repository fetch to index update;
- corpus activation to retrieval;
- health state to frontend;
- event to Telegram notification.

### 17.4 Retrieval benchmark

The benchmark SHALL include expected evidence, not only expected prose.

A response fails if it is linguistically correct but cites the wrong source, loses temporal context, invents details, or fails to disclose conflict.

### 17.5 Failure injection

Tests SHALL simulate:

- DNS failure;
- TLS failure;
- provider timeout;
- unauthorized response;
- rate limit;
- malformed JSON;
- valid JSON with schema drift;
- empty response;
- stale upstream timestamp;
- Git remote failure;
- local repository modification;
- disk nearly full;
- database unavailable;
- Telegram delivery failure;
- service restart during a job.

### 17.6 Security tests

Tests SHALL verify:

- secrets are redacted;
- unauthorized Telegram users are blocked;
- health endpoints are not publicly accessible by default;
- imported text cannot alter tool policy;
- wallet secret patterns are rejected;
- arbitrary shell and HTTP tools are unavailable to Hermes.

### 17.7 Recovery tests

Tests SHALL verify:

- configuration restore;
- knowledge database restore;
- memory restore;
- clone recreation from remote plus metadata restore;
- restart after interrupted ingestion;
- restart after interrupted repository fetch.

---

## 18. Product acceptance criteria

Atlas core is accepted only when all of the following are true:

1. Hermes runs reliably on the Pi using a supported aarch64 installation.
2. Personal memory and prior-session recall work and are reviewable.
3. The Bittensor corpus has a completed validation report.
4. Only approved knowledge is active.
5. Grounded answers return correct provenance.
6. Unsupported and conflicting questions are handled explicitly.
7. The official repository identity is confirmed and fully cloned.
8. Repository freshness and index alignment are visible.
9. TaoStats and TaoSwap contracts have been validated using real calls.
10. Live requests fail closed on provider, schema, freshness, or quota failure.
11. Cached information is never represented as live.
12. Web results remain unverified leads.
13. No wallet secret, transaction, signing, or trading capability exists.
14. Backups have passed a restore test.
15. Core health state is observable.
16. Required security and privacy decisions are documented.

---

## 19. Success metrics

Exact thresholds require user approval, but the product SHALL measure:

- percentage of benchmark questions answered with correct evidence;
- unsupported-claim rate;
- incorrect-live-data rate, with a target of zero;
- stale-as-live incidents, with a target of zero;
- schema-drift detection rate;
- repository update success rate;
- time from repository change detection to index alignment;
- TaoStats quota usage and prevented over-limit calls;
- memory correction success rate;
- health-check freshness;
- backup and restore success;
- Telegram duplicate-alert rate.

User satisfaction and usefulness may be recorded, but cannot replace correctness metrics.

---

## 20. Risks and required mitigations

### Risk: Supplied corpus contains outdated or incorrect information

Mitigation: Treat all input as unverified, maintain temporal scope, produce a validation report, activate only approved content.

### Risk: API documentation differs from production

Mitigation: Require authenticated contract discovery and multi-sample schema validation.

### Risk: Provider returns stale data with a successful status

Mitigation: Validate upstream timestamps or blocks and define endpoint-specific freshness policies.

### Risk: TaoStats quota is consumed by retries or background jobs

Mitigation: Persist local budget, bound retries, prioritize interactive queries only after user approves a policy.

### Risk: TaoSwap has undocumented rate limits

Mitigation: Do not assume unlimited use; observe headers and failures, configure conservative behavior after validation.

### Risk: Hermes remembers an incorrect assumption

Mitigation: Approval-gated memory writes, correction workflow, no domain corpus in built-in memory.

### Risk: Repository summary overstates semantic impact

Mitigation: Label summaries, provide commit/file evidence, distinguish changed code from proven deployed runtime behavior.

### Risk: Pi storage is exhausted

Mitigation: Baseline storage, monitor thresholds, limit raw-response retention, avoid node data, avoid unnecessary build artifacts.

### Risk: External LLM provider sees sensitive conversations

Mitigation: Review provider privacy and retention before selection; avoid sending secrets; document boundary.

### Risk: Frontend creates an attack surface

Mitigation: Defer frontend, bind locally by default, require explicit exposure and authentication design.

### Risk: Feature creep turns Atlas into a trading system

Mitigation: Permanent non-goals, no signing dependencies, no wallet secret fields, separate future alert-only specifications.

---

## 21. Decisions and information required from the user

These items are intentionally unresolved. They must be answered before the relevant phase.

### Blocking Phase 0 or Phase 1

1. What Raspberry Pi model is in use?
2. What operating system, version, and kernel are currently installed?
3. Is anything on the Pi required to be preserved?
4. Is a clean OS reinstall permitted, or only in-place cleanup?
5. How is the Pi accessed today: local console, SSH, VPN, LAN, or public internet?
6. Should Atlas remain LAN/local only, or require remote access?
7. Which LLM provider and model candidates are acceptable?
8. What monthly LLM budget and latency are acceptable?
9. Are conversations allowed to leave the Pi for a hosted model?
10. What external backup target will be used?
11. What telemetry settings are acceptable for Hermes and OpenSpec?

### Blocking Phase 2

12. What is the expected size and file count of the July 2026 Bittensor corpus?
13. Does the corpus include source links, commit references, dates, and block numbers?
14. Which categories must “full Bittensor knowledge” include?
15. Are subnet-specific documents included, and if so, which subnets?
16. Should unsupported material be excluded entirely or retained in a quarantined review store?
17. Should an encrypted external archive of the original bulk Markdown be retained after local deletion?
18. What retrieval benchmark threshold is required before activation?
19. Should memory writes remain approval-gated permanently or be reconsidered after evaluation?

### Blocking Phase 3

20. What repository polling interval is desired?
21. Should every commit trigger a notification, or only selected paths/tags/releases?
22. Which repository paths or protocol areas are highest priority for change detection?
23. Is GitHub access anonymous, or will a read-only token be supplied?

### Blocking Phase 4

24. What are the confirmed TaoStats documentation URL, API base URL, and key provisioning method?
25. Which TaoStats endpoints are required first?
26. What are the confirmed TaoSwap documentation URL, API base URL, and key provisioning method?
27. Which TaoSwap endpoints are required first?
28. May contract tests store redacted response fixtures locally?
29. May Atlas retain raw response bodies, or metadata and hashes only?
30. Which current values require cross-provider comparison?
31. What should happen when a provider reports no upstream timestamp or block?

### Blocking Phase 5

32. Is Telegram intended only for alerts, or also full Hermes conversation?
33. Which Telegram account or chat identifiers are allowed?
34. Which alert classes should be enabled initially?
35. What quiet hours, batching, or severity rules are required?

### Blocking Phase 6

36. Where will the frontend be accessed from?
37. What authentication method is required?
38. Is HTTPS required on the LAN, and how will certificates be managed?
39. Which device-health and service-health fields are mandatory on the first screen?
40. What log and metrics retention periods are desired?

### Blocking Phase 7

41. Which public wallet addresses, if any, may be monitored?
42. Which chains or Bittensor account types are in scope for view-only tracking?
43. Which watchlist and alert conditions are desired?
44. What wording and disclaimers are required for investment research alerts?

---

## 22. Recommended OpenSpec decomposition

Do not ask OpenSpec to implement the entire PRD as one change.

Initialize the Atlas repository and create one change proposal per phase or narrowly scoped capability.

Recommended sequence:

1. `atlas-phase-0-device-inventory`
2. `atlas-phase-0-provider-contract-discovery`
3. `atlas-phase-1-hermes-baseline`
4. `atlas-phase-1-memory-and-session-recall`
5. `atlas-phase-2-corpus-intake`
6. `atlas-phase-2-knowledge-validation`
7. `atlas-phase-2-grounded-retrieval`
8. `atlas-phase-3-subtensor-repository-tracking`
9. `atlas-phase-4-taostats-adapter`
10. `atlas-phase-4-taoswap-adapter`
11. `atlas-phase-4-live-data-fail-closed-policy`
12. `atlas-phase-5-telegram-integration`
13. `atlas-phase-6-health-api`
14. `atlas-phase-6-monitoring-frontend`
15. `atlas-phase-7-view-only-portfolio`
16. `atlas-phase-7-alert-rules`

**Sequence amendment (2026-08-07, change `mining-triage`).** Items 13 and 14
(Phase 6) no longer come next. `mining-triage` was sequenced ahead of them
by operator decision: Phase 6 is a health UI for a single-user LAN system
whose health is already readable from the CLI and Telegram, while mining
triage is the first capability in Atlas with a direct financial payoff, and
its inputs were verified as computable at zero provider cost. Phase 6 keeps
its scope and its blocking questions (§21 Q36-Q40); it simply follows rather
than precedes. Nothing in §7 is relaxed: mining triage runs no miner, holds
no key, and submits no transaction.

Each proposal SHOULD include:

- exact scope;
- explicit non-goals;
- resolved decisions;
- requirements and GIVEN/WHEN/THEN scenarios;
- design choices supported by validation evidence;
- implementation tasks;
- test plan;
- rollback plan;
- phase exit evidence.

### Suggested first OpenSpec prompt

```text
/opsx:propose atlas-phase-0-device-inventory

Use atlas_prd.md as the governing product requirements document.
Create only the Phase 0 device inventory capability. Do not install, remove,
or modify software. Preserve all unknowns as explicit decisions. Include a
read-only inventory script, redaction requirements, output schema, tests, and
acceptance criteria. Do not implement later phases.
```

---

## 23. Definition of done for every OpenSpec change

A change is done only when:

- the approved scope is implemented;
- all normative scenarios pass;
- tests pass on the Pi or an explicitly approved equivalent environment;
- secrets are absent from logs and artifacts;
- documentation is updated;
- health and failure behavior are observable;
- rollback is documented and tested when applicable;
- the user reviews the evidence;
- unresolved assumptions are not hidden in code.

---

## 24. Final constraints summary

Atlas is a local, single-user Hermes-based Bittensor knowledge and live-data agent.

It SHALL be built methodically and in phases.

It SHALL validate the current Pi before changing it.

It SHALL validate the supplied Bittensor corpus before trusting it.

It SHALL track a confirmed official mainnet repository through a full local clone.

It SHALL validate TaoStats and TaoSwap using actual authenticated calls before adapter implementation.

It SHALL fail closed rather than present stale or invalid information as live.

It SHALL treat general web results as unverified leads only.

It SHALL use Hermes memory for compact personal and operational recall, not as the Bittensor knowledge database.

It SHALL not host a Bittensor node.

It SHALL never trade, sign, hold wallet secrets, or expose wallet write capability.

Investment functionality, if later approved, SHALL remain view-only and alert-based.
