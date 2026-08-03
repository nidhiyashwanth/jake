# Market landscape, August 2026

Everything here is sourced. Links at the bottom. Read §2 and §7 if you read nothing else.

---

## 1. Size and mood

- Worldwide AI spend projected at **$2.52T in 2026** (+44% YoY). AI infrastructure alone **$675B** (+63%).
- US AI consulting market **>$15B**. Top 10 firms hold ~56%; the rest is a long tail of boutiques — i.e. **fragmented and enterable**.
- Typical mid-market implementation project: **$30k–$100k**, with **$5k–$15k/month** support retainers. Deployly's $185K point build sits well above the market — they are selling certainty, not code.
- Gartner: **40% of enterprise applications will feature task-specific AI agents by end of 2026**, up from <5% in 2025.

And simultaneously: 95% of pilots produced no P&L impact (MIT), 42% of companies abandoned most AI projects (S&P), <20% of pilots reach scale (McKinsey), fewer than 1 in 10 enterprises can point to sustained measurable value.

**Read:** enormous spend, terrible conversion. The money is in conversion, not in more capability.

---

## 2. The event that reshapes this space: the deployment JVs

**4 May 2026.** Both frontier labs launched enterprise *deployment* businesses on the same day.

**OpenAI — "The Deployment Company"**
- $10B valuation, **$4B raised from 19 PE investors**
- Anchors: TPG, Brookfield, Bain Capital, Advent International, Dragoneer, SoftBank
- OpenAI **guarantees backers 17.5% annual return over 5 years**; in exchange the buyout firms open their portfolio companies as a captive customer base

**Anthropic — unnamed venture**
- **$1.5B committed**: $300M each from Anthropic, Blackstone, Hellman & Friedman; $150M Goldman Sachs
- Mandate: deploy Claude into **midsize companies' core operations**

Combined ~$14B aimed at exactly one thing: getting frontier models into the operational guts of PE-owned mid-market companies.

### What this means for you — four consequences

1. **The PE-portfolio wedge is now a bad place to build a startup.** You cannot outbid a fund's own AI JV for its own portfolio. Deployly's `/private-equity/` page is their best offer and their biggest exposure.
2. **But it validates the category enormously.** "Deployment is a distinct discipline requiring dedicated partners" is now a $14B institutional bet. Selling the *idea* just got much easier; your prospect's board has already read about this.
3. **They will create a partner ecosystem, and partners need tooling.** $14B of deployment capacity cannot be delivered by employees of two JVs. It will be delivered through certified implementation partners — hundreds to thousands of small shops with no engineering leverage. **That is a real, dated, addressable buyer for a delivery platform (Layer 3b in `00`).**
4. **They will go top-down and glamorous.** Big logos, big portfolios, big functions. They will not chase a 40-branch HVAC distributor's warranty-claim backlog. **That is where you go.**

---

## 3. Competitive map — know exactly who you are not

### 3.1 Services / implementation (Deployly's actual competitors)
- **Big:** Accenture, IBM Consulting, Bain/BCG/McKinsey AI arms, Slalom, EPAM. Enterprise, $1M+ engagements, slow.
- **The JVs:** OpenAI Deployment Company, Anthropic/Blackstone JV. New, huge, PE-channel.
- **Boutiques:** Deployly, LOW/CODE Agency (9 Claude-certified devs, 400+ projects), LeewayHertz, Codewave, 10Pearls, and hundreds of unbranded AI automation agencies.
- **Structural weakness of all of them:** revenue is linear in headcount, nothing compounds, and no one can prove outcomes.

### 3.2 Horizontal agent/workflow platforms (do NOT try to be one)
- **n8n** — open-source, node-based, 500+ integrations. The default for technical teams.
- **Zapier / Copilot Studio / Agentforce** — distribution-owned incumbents.
- **Lindy** (4,000+ tool connections, optimises for speed over depth), **Gumloop** (template-led), **Coworker**, **xpander**.
- **Relay.app is shutting down** — free access ends 15 Aug 2026, paid 14 Sep 2026, signups already closed. A funded, well-liked player in this exact lane died this year. Take the warning seriously.
- **Code-first:** LangGraph (production at Uber, JPMorgan, BlackRock, Cisco, LinkedIn, Klarna), CrewAI, OpenAI Agents SDK.

**Verdict:** the visual-builder-plus-connectors category is saturated, commoditised, and actively killing companies. Any plan whose differentiation is "our workflow builder" is dead on arrival.

### 3.3 Durable execution (your reliability layer, not your product)
- **Temporal** — 9.1T lifetime action executions, +380% YoY; OpenAI runs Temporal for Codex at millions of agent requests/day; official **Temporal LangGraph plugin** shipped; OpenAI Agents SDK + Temporal Python SDK GA since March 2026.
- Consensus pattern in 2026: **Temporal owns the durable outer loop, LangGraph owns the bounded inner loop.** Don't pick one; layer them.

### 3.4 Document AI / IDP (the incumbents in the wedge your note picked)
- **Rossum** — from **$18,000/yr** Starter (unlimited seats, Aurora engine, email/API/manual ingestion, validation screens, API); higher tiers add master-data matching, duplicate detection, ERP connectors for SAP, Coupa, Workday, Oracle, NetSuite, Dynamics.
- **Hyperscience, Instabase, ABBYY Vantage, Kofax TotalAgility, UiPath Document Understanding, Nanonets, WorkFusion.**
- Mid-market IDP pricing band: **$500–$5,000/month**.

### 3.5 The AP/finance lane (why I am telling you not to start here)
- **Ramp** — $44B valuation, $750M Series F (June 2026). Ships **four named AP agents**: GL auto-coding, fraud prevention, approval routing, payment-method optimisation, plus AI receipt chasers over email/SMS/Slack. Launched "Stack", an AI accounting OS for CPA firms, and Ramp Applied AI Solutions for custom enterprise agentic workflows.
- **Bill.com, Tipalti** (displacing Bill and Concur in mid-market on multi-entity), **Peakflo** (AI-native AP/AR with voice agents).
- **Conclusion:** invoice capture is a feature of a spend-management platform now, given away to win the payment flow. You cannot win it as a standalone product from a standing start.

### 3.6 Order-to-cash / sales order automation (an adjacent, better-defended-by-you lane)
- **Conexiom** — category leader for sales order automation; Ideal Order Platform (Feb 2025); trained on **1B+ purchase-order line items**; ingests email, PDF, spreadsheet, EDI 850, image, text → touchless orders into ERP.
- **Esker** — enterprise, 70+ prebuilt integrations, full O2C lifecycle.
- Market fact worth memorising: **60–70% of B2B orders still arrive as unstructured documents**; manual entry takes **10–30 min/order** at a **3–5% error rate**.
- **Gap:** both incumbents are enterprise-priced and ERP-integration-gated. Distributors and manufacturers under ~$150M revenue are underserved and still run this in a shared inbox.

### 3.7 Process intelligence / workflow discovery (your "Map" module's competitors)
- **Celonis** (category creator; launched Context Model; acquired Ikigai Labs), **Apromore** (folded into Salesforce Agentforce), **Skan**, **Soroco**, **KYP.ai**, IBM Process Mining, Signavio.
- The 2026 shift: process mining and agentic execution are **converging**. Mining tools are adding execution; agent platforms are adding discovery.
- Key insight from that literature, which you should build on: *agents need more than process steps — they need business rules, exception handling, success criteria and escalation procedures.* **Discovery platforms that cannot capture that structured context cannot enable reliable agent deployment.** Nobody has nailed this. It is the most interesting unclaimed territory in the map.

### 3.8 Evaluation & observability (buy, don't build)
- **LangSmith** (deepest LangChain/LangGraph integration, proprietary, volume-priced), **Arize AX** (enterprise monitoring, span+volume pricing), **Braintrust** (eval+observability unified; Pro from $249/mo; no self-hosting), **Langfuse** (self-hostable, OTel-native, ClickHouse-backed; unit pricing hard to forecast), MLflow, Confident AI.
- All of them track spans, quality, faithfulness, drift. **None of them track business outcome against a baseline.** That is the seam.

---

## 4. Interop: MCP is now infrastructure

- Donated by Anthropic to the **Agentic AI Foundation** (Linux Foundation directed fund) in **Dec 2025**; co-founded with Block and OpenAI; backed by Google, Microsoft, AWS, Cloudflare, Bloomberg.
- **~97M SDK downloads/month**, **10,000+ active public servers** (17,000+ in unofficial directories).
- Gartner: **75% of API gateway vendors will have MCP features by end of 2026**. CData: **30% of enterprise application vendors will launch MCP servers in 2026**.
- **Enterprise-Managed Authorization** extension is **stable** — central org-level authz for MCP servers, single sign-on across connected servers; adopted by Anthropic, Microsoft, Okta. Active proposals: DPoP, Workload Identity Federation.
- Production references: Block (company-wide via Goose, 98.7% token reduction), Bloomberg, Cisco, PayPal, Raiffeisen Bank.
- Security guidance now exists from NSA/CISA-adjacent bodies, Cloud Security Alliance, and the Coalition for Secure AI. **Read these before you expose MCP to customer systems** — prompt injection through tool descriptions and confused-deputy attacks are the live risks.

**Strategic implication:** connectors are no longer a moat and no longer a cost centre. Build an MCP gateway + credential vault, and spend the saved weeks on the ledger and the review desk.

---

## 5. Pricing environment

- **Outcome/per-resolution pricing is now mainstream** in agent products: Quickchat from $0.50/resolution, Intercom Fin $0.99, Zendesk ~$1.50, Salesforce Agentforce $2.00/conversation, HubSpot Customer Agent cut to $0.50 in April 2026 (from $1.00).
- Gartner: by 2030 **≥40% of enterprise SaaS spend** shifts to usage/agent/outcome pricing; seat-based revenue share falls 21% → 15%. IDC: **70% of vendors off pure per-seat by 2028**.
- Deloitte published accounting guidance for outcome-based pricing in agentic AI products (June 2026) — a sign this is now a real, audited commercial model, not a pricing experiment.

**Implication:** you can and should charge per successful outcome. But you can only do that credibly if you can *measure* the outcome and defend the count. Back to the ledger.

---

## 6. Regulatory environment

- **EU AI Act high-risk obligations were delayed.** Digital Omnibus on AI: political agreement 7 May 2026, European Parliament final approval 16 June 2026. Annex III (use-based high-risk) moves **2 Aug 2026 → 2 Dec 2027** (16 months). Annex I (product-regulated) moves **Aug 2027 → Aug 2028**.
- **But transparency, governance, national supervision, AI-literacy and GPAI obligations remain live in 2026.** "The high-risk deadline moved" is not "there is nothing to do."
- **ISO/IEC 42001 is becoming a procurement gate.** 83% of Fortune 500 procurement teams plan to require ISO 42001 alignment by 2027. Certified: Snowflake (Jun 2025), Salesforce (Oct 2025), ServiceNow (Dec 2025), BCG (Jan 2026, among first 100 globally). Consensus: **ISO 42001 + SOC 2 is the acceptable pair** for 2026 procurement; 42001 complements rather than replaces SOC 2.
- **9% of PE firms are confident they could pass an AI audit within 90 days** (Grant Thornton, n=950). That is a screaming product signal: audit-readiness as a feature sells itself to this buyer.

---

## 7. Where the white space actually is

Cross-referencing everything above, four claims:

**1. The runtime is commodity. The evidence is not.**
Every observability vendor tracks tokens, spans, latency, faithfulness. Not one produces a defensible, auditable statement of *"this workflow cost $X/month before, costs $Y now, here are the 4,312 runs that prove it, here is what a human touched and why."* Every buyer now demands exactly that. **Build the ledger.**

**2. Structured exception knowledge is unclaimed.**
Process mining gives you the happy path. Agents fail on exceptions. Nobody is systematically capturing *the exception taxonomy* — the 40 weird cases an ops person handles by instinct — as a structured, versioned, testable artifact. Your human review desk generates this as a byproduct if you design for it. **This is the compounding asset.**

**3. The under-$250M-revenue operating company is being abandoned.**
Too small for the JVs and Accenture, too messy for self-serve tools, burned by a failed pilot. Deployly's own industry list (industrial & manufacturing, field services, food & beverage, commerce & retail, logistics & distribution, healthcare) is the right list. They will drift upmarket to PE. Go down.

**4. There is a dated arbitrage on implementation-partner tooling.**
The JVs will certify a partner channel over the next 12–24 months. Those partners will be 5–30 person shops delivering fixed-fee builds with no platform. This is Layer 3b. Do not build for it yet — but architect so that multi-tenant, white-labelled delivery is a configuration change rather than a rewrite.

---

## Sources

Deployment JVs: [Bloomberg](https://www.bloomberg.com/news/articles/2026-05-04/openai-finalizes-10-billion-joint-venture-with-pe-firms-to-deploy-ai), [TechCrunch](https://techcrunch.com/2026/05/04/anthropic-and-openai-are-both-launching-joint-ventures-for-enterprise-ai-services/), [Dealroom](https://app.dealroom.co/news/note/openai-and-anthropic-launch-rival-enterprise-ai-ventures-backed-by-wall-street-3), [TechFundingNews](https://techfundingnews.com/openai-bags-over-4b-to-build-deployment-company-with-tpg-brookfield-bain-for-enterprise-ai-rollout-report/), [Yahoo Finance](https://finance.yahoo.com/sectors/technology/articles/pe-firms-offer-ai-labs-133000826.html)

Consulting market: [Perceptive Analytics](https://www.perceptive-analytics.com/top-10-best-ai-consulting-firms-for-mid-market-companies-in-the-us-2026-guide/), [Mingma](https://mingma.io/journal/best-ai-automation-agencies-mid-market/), [Addepto](https://addepto.com/blog/16-top-ai-integration-companies-in-2026-comprehensive-guide-to-ai-implementation-strategies/)

Agent platforms: [Coworker](https://coworker.ai/blog/ai-agent-orchestration-platform), [xpander](https://xpander.ai/resources/best-n8n-alternatives-for-ai-agents-2026), [Lindy](https://www.lindy.ai/blog/best-ai-agent-builders), [Gumloop](https://www.gumloop.com/blog/lindy-ai-alternatives), [AI Tool Briefing](https://aitoolbriefing.com/guides/ai-agent-platforms-workflow-automation-2026/)

Durable execution: [Temporal LangGraph plugin](https://temporal.io/blog/temporal-langgraph-plugin-durable-execution), [AgentMarketCap](https://agentmarketcap.ai/blog/2026/04/10/durable-agent-execution-production-temporal-modal-event-sourced), [Zylos](https://zylos.ai/research/2026-04-24-durable-execution-agent-runtimes/), [AppScale](https://appscale.blog/en/blog/durable-execution-llm-agents-temporal-langgraph-checkpointing-2026)

IDP / AP: [IDP comparison](https://www.intelligentdocumentprocessing.co/compare), [Doxis](https://www.doxis.com/en/blog/best-idp-software), [Ramp AP agents](https://ramp.com/blog/agentic-ai/best-ai-agents-for-ap-automation), [Ramp $44B](https://industry-lens.com/reports/bill-ramp-hits-44-billion-june-2026), [Peakflo](https://peakflo.co/blog/billcom-alternatives-ai-finance-automation)

Order-to-cash: [Conexiom Ideal Order Platform](https://www.prnewswire.com/news-releases/conexiom-launches-ai-powered-ideal-order-platform-to-revolutionize-sales-order-automation-302386165.html), [Conexiom](https://conexiom.com/automated-order-entry-software/), [Esker](https://www.esker.com/solutions/order-management/), [Oro](https://oroinc.com/b2b-ecommerce/blog/sales-order-automation/)

Process intelligence: [Kai Waehner, Process Intelligence Landscape 2026](https://www.kai-waehner.de/blog/2026/07/22/process-intelligence-landscape-2026-mining-orchestration-and-the-agentic-ai-shift/), [KYP.ai](https://kyp.ai/automated-process-discovery-tools/), [Kognitos](https://www.kognitos.com/blog/process-mining-vs-agentic-ai-2026-guide/)

Observability: [LangSmith vs Arize vs Braintrust](https://anudeepsri.medium.com/langsmith-vs-arize-vs-braintrust-e397e4728a76), [Confident AI](https://www.confident-ai.com/knowledge-base/compare/top-7-llm-observability-tools), [Braintrust](https://www.braintrust.dev/articles/langfuse-alternatives-2026)

MCP: [MCP enterprise-managed auth](https://blog.modelcontextprotocol.io/posts/enterprise-managed-auth/), [InfoQ](https://www.infoq.com/news/2026/07/mcp-ema-enterprise-auth/), [Toloka MCP roadmap](https://toloka.ai/blog/the-future-of-mcp-enterprise-adoption/), [CSA MCP security](https://labs.cloudsecurityalliance.org/agentic/agentic-mcp-security-best-practices-v1/), [CoSAI MCP security PDF](https://www.coalitionforsecureai.org/wp-content/uploads/2026/03/model-context-protocol-security-1.pdf)

Pricing: [Quickchat](https://quickchat.ai/post/ai-agent-pricing-models), [Fin](https://fin.ai/learn/ai-customer-service-agent-pricing-comparison), [Deloitte accounting guidance](https://dart.deloitte.com/USDART/home/publications/deloitte/industry/technology/accounting-outcome-based-pricing-agentic-ai)

Regulation: [Gibson Dunn omnibus](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/), [Morgan Lewis](https://www.morganlewis.com/pubs/2026/06/eu-approves-delays-and-other-amendments-to-certain-eu-ai-act-obligations-what-businesses-should-know), [Jones Walker](https://www.joneswalker.com/en/insights/blogs/ai-law-blog/yes-august-2-still-matters-the-eu-approved-a-high-risk-ai-delay-but-most-trans.html), [ISO 42001 as vendor requirement](https://www.brightdefense.com/news/iso-42001-moves-from-ai-standard-to-vendor-requirement/), [ISO 42001 vs SOC 2](https://www.knowlee.ai/blog/iso-42001-vs-soc2-vs-iso-27001-comparison)

ROI evidence: [Heeya](https://heeya.fr/en/blog/generative-ai-enterprise-roi-use-cases-2026), [AI Monk case studies](https://aimonk.com/agentic-ai-examples-enterprise-roi-case-studies/), [Alphacorp](https://alphacorp.ai/blog/9-ai-agent-use-cases-that-actually-work-in-production-2026)
