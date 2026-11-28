"""IFRS S1 and IFRS S2 disclosure requirements, one row per requirement paragraph.

Paragraph numbers were checked against the published standards (IFRS S1 and S2, June 2023, with the December 2025 amendments
to S2 applying from annual periods beginning 1 January 2027). The requirement text is a paraphrase written for preparers: it is
a checklist aid, not the standard. Always read the standard text before asserting compliance (S1 para 72 allows an
unreserved statement of compliance only when every requirement is met).

Row: (code, standard, pillar, title, requirement, link, kind)
  link  = what the system can evidence by itself (see issb_checklist.system_signals); "" means preparer-supplied narrative.
  kind  = "narrative" or "quantitative".
"""

S1, S2 = "IFRS-S1", "IFRS-S2"

REQUIREMENTS = [
 # ------------------------------------------------------------------ IFRS S2 governance
 ("S2.6(a)", S2, "Governance", "Oversight body or individual", "Identify the body or individual responsible for oversight of climate-related risks and opportunities.", "", "narrative"),
 ("S2.6(a)(i)", S2, "Governance", "Responsibilities in mandates", "How climate responsibilities are reflected in terms of reference, mandates, role descriptions and policies.", "", "narrative"),
 ("S2.6(a)(ii)", S2, "Governance", "Skills and competencies", "How the body determines it has, or will develop, the skills and competencies to oversee strategies for climate-related risks and opportunities.", "", "narrative"),
 ("S2.6(a)(iii)", S2, "Governance", "How and how often informed", "How and how often the body is informed about climate-related risks and opportunities.", "", "narrative"),
 ("S2.6(a)(iv)", S2, "Governance", "Integration into strategy and decisions", "How the body takes climate-related risks and opportunities into account in strategy, major transactions and risk management, including trade-offs.", "", "narrative"),
 ("S2.6(a)(v)", S2, "Governance", "Targets and remuneration", "How the body oversees target setting and progress, including whether and how related performance metrics feed into remuneration.", "targets", "narrative"),
 ("S2.6(b)", S2, "Governance", "Management's role", "Management's role in the governance processes, controls and procedures used to monitor and manage climate-related risks and opportunities.", "", "narrative"),
 ("S2.6(b)(i)", S2, "Governance", "Delegation to management", "Whether the role is delegated to a specific management-level position or committee, and how oversight of it is exercised.", "", "narrative"),
 ("S2.6(b)(ii)", S2, "Governance", "Controls and procedures", "Whether management uses controls and procedures to support oversight and, if so, how they are integrated with other internal functions.", "", "narrative"),
 # ------------------------------------------------------------------ IFRS S2 strategy
 ("S2.10(a)", S2, "Strategy", "Climate-related risks and opportunities", "Describe the climate-related risks and opportunities that could reasonably be expected to affect prospects.", "materiality", "narrative"),
 ("S2.10(b)", S2, "Strategy", "Physical or transition", "For each climate-related risk, state whether it is a physical risk or a transition risk.", "", "narrative"),
 ("S2.10(c)", S2, "Strategy", "Time horizons of effects", "For each risk and opportunity, the short-, medium- or long-term horizon over which the effects are expected.", "", "narrative"),
 ("S2.10(d)", S2, "Strategy", "Definition of horizons", "How short, medium and long term are defined and how they link to strategic planning and capital allocation horizons.", "", "narrative"),
 ("S2.13(a)", S2, "Strategy", "Effects on business model and value chain", "Current and anticipated effects of climate-related risks and opportunities on the business model and value chain.", "", "narrative"),
 ("S2.13(b)", S2, "Strategy", "Concentration in the value chain", "Where in the business model and value chain climate-related risks and opportunities are concentrated.", "", "narrative"),
 ("S2.14(a)(i)", S2, "Strategy", "Changes to business model and resource allocation", "How the entity has responded, and plans to respond, through changes to its business model, including resource allocation.", "", "narrative"),
 ("S2.14(a)(ii)", S2, "Strategy", "Direct mitigation and adaptation", "Current and anticipated direct mitigation and adaptation efforts (for example production processes, facilities, procurement).", "", "narrative"),
 ("S2.14(a)(iii)", S2, "Strategy", "Indirect mitigation and adaptation", "Current and anticipated indirect mitigation and adaptation efforts (for example working with customers and supply chains).", "", "narrative"),
 ("S2.14(a)(iv)", S2, "Strategy", "Transition plan", "Any climate-related transition plan, including key assumptions and dependencies; if there is none, say so.", "", "narrative"),
 ("S2.14(a)(v)", S2, "Strategy", "How targets will be achieved", "How the entity plans to achieve its climate-related targets, including greenhouse gas emissions targets.", "targets", "narrative"),
 ("S2.14(b)", S2, "Strategy", "Resourcing of the response", "How the activities in 14(a) are being, and will be, resourced.", "", "narrative"),
 ("S2.14(c)", S2, "Strategy", "Progress against prior plans", "Quantitative and qualitative progress against plans disclosed in earlier reporting periods.", "", "narrative"),
 ("S2.15(a)", S2, "Strategy", "Current financial effects", "Current financial effects of climate-related risks and opportunities on financial position, performance and cash flows.", "", "quantitative"),
 ("S2.15(b)", S2, "Strategy", "Anticipated financial effects", "Anticipated financial effects over the short, medium and long term, including how they are included in financial planning.", "scenario", "quantitative"),
 ("S2.16(a)", S2, "Strategy", "Effect in the reporting period", "How climate-related risks and opportunities affected financial position, performance and cash flows in the reporting period.", "", "quantitative"),
 ("S2.16(b)", S2, "Strategy", "Risk of material adjustment", "Risks and opportunities with a significant risk of material adjustment to carrying amounts of assets and liabilities in the next annual period.", "", "quantitative"),
 ("S2.16(c)", S2, "Strategy", "Expected change in financial position", "Expected changes to financial position over the short, medium and long term, including investment and disposal plans and planned funding sources.", "", "quantitative"),
 ("S2.16(d)", S2, "Strategy", "Expected change in performance and cash flows", "Expected changes to financial performance and cash flows over the short, medium and long term.", "", "quantitative"),
 ("S2.21", S2, "Strategy", "Where quantitative effects are omitted", "If quantitative information is omitted under the exemptions, explain why, give qualitative information (affected line items) and quantify combined effects unless not useful.", "", "narrative"),
 ("S2.22(a)(i)", S2, "Strategy", "Resilience: implications for strategy", "Climate resilience of strategy and business model at the reporting date, including how scenario results lead to changes in response.", "scenario", "narrative"),
 ("S2.22(a)(ii)", S2, "Strategy", "Resilience: significant uncertainties", "Significant areas of uncertainty considered in the resilience assessment.", "scenario", "narrative"),
 ("S2.22(a)(iii)", S2, "Strategy", "Resilience: capacity to adjust", "Capacity to adjust: availability and flexibility of financial resources, ability to redeploy or retire assets, effect of current and planned investments.", "scenario", "narrative"),
 ("S2.22(b)(i)", S2, "Strategy", "Scenario analysis: scenarios and approach", "Scenarios used and their sources, whether a diverse range was used, whether transition and/or physical risks were covered, whether a scenario aligned with the latest international climate agreement was used, why they are relevant, time horizons, and scope of operations.", "scenario", "narrative"),
 ("S2.22(b)(ii)", S2, "Strategy", "Scenario analysis: key assumptions", "Key assumptions: climate policies, macroeconomic trends, national or regional variables, energy usage and mix, and technology developments.", "scenario", "narrative"),
 ("S2.22(b)(iii)", S2, "Strategy", "Scenario analysis: reporting period", "The reporting period in which the scenario analysis was carried out.", "scenario", "narrative"),
 # ------------------------------------------------------------------ IFRS S2 risk management
 ("S2.25(a)(i)", S2, "Risk Management", "Inputs and parameters", "Inputs and parameters used to identify, assess, prioritise and monitor climate-related risks (data sources, scope of operations).", "", "narrative"),
 ("S2.25(a)(ii)", S2, "Risk Management", "Scenario analysis in risk identification", "Whether and how climate-related scenario analysis is used to inform identification of risks.", "scenario", "narrative"),
 ("S2.25(a)(iii)", S2, "Risk Management", "Assessing nature, likelihood and magnitude", "How the nature, likelihood and magnitude of the effects of those risks are assessed.", "", "narrative"),
 ("S2.25(a)(iv)", S2, "Risk Management", "Prioritisation against other risks", "Whether and how climate-related risks are prioritised relative to other types of risk.", "", "narrative"),
 ("S2.25(a)(v)", S2, "Risk Management", "Monitoring", "How climate-related risks are monitored.", "", "narrative"),
 ("S2.25(a)(vi)", S2, "Risk Management", "Changes in process", "Whether and how the risk processes have changed compared with the previous reporting period.", "", "narrative"),
 ("S2.25(b)", S2, "Risk Management", "Opportunity processes", "Processes used to identify, assess, prioritise and monitor climate-related opportunities, including whether scenario analysis is used.", "", "narrative"),
 ("S2.25(c)", S2, "Risk Management", "Integration into overall risk management", "The extent to which, and how, the climate-related risk and opportunity processes are integrated into overall risk management.", "", "narrative"),
 # ------------------------------------------------------------------ IFRS S2 metrics and targets
 ("S2.29(a)(i)-1", S2, "Metrics and Targets", "Scope 1 emissions", "Absolute gross Scope 1 greenhouse gas emissions for the period, in tonnes of CO2 equivalent.", "ghg_scope1", "quantitative"),
 ("S2.29(a)(i)-2", S2, "Metrics and Targets", "Scope 2 emissions", "Absolute gross Scope 2 greenhouse gas emissions for the period, in tonnes of CO2 equivalent.", "ghg_scope2", "quantitative"),
 ("S2.29(a)(i)-3", S2, "Metrics and Targets", "Scope 3 emissions", "Absolute gross Scope 3 greenhouse gas emissions for the period, in tonnes of CO2 equivalent.", "ghg_scope3", "quantitative"),
 ("S2.29(a)(ii)", S2, "Metrics and Targets", "Measurement method", "Greenhouse gas emissions measured under the GHG Protocol Corporate Standard (2004), unless a jurisdictional authority or exchange requires another method (for all or part of the entity, from the 2025 amendments).", "ghg_method", "narrative"),
 ("S2.29(a)(iii)", S2, "Metrics and Targets", "Approach, inputs and assumptions", "The measurement approach, inputs and assumptions used, why they were chosen, and any change made in the period and why.", "ghg_method", "narrative"),
 ("S2.29(a)(iv)", S2, "Metrics and Targets", "Consolidated group and other investees", "Scope 1 and Scope 2 emissions disaggregated between the consolidated accounting group and other investees.", "ghg_boundary", "quantitative"),
 ("S2.29(a)(v)", S2, "Metrics and Targets", "Location-based Scope 2 and instruments", "Location-based Scope 2 emissions, and information about any contractual instruments needed to understand the entity's Scope 2 position.", "ghg_location", "quantitative"),
 ("S2.29(a)(vi)", S2, "Metrics and Targets", "Scope 3 categories included", "The Scope 3 categories included in the measurement and, for asset management, commercial banking and insurance, additional financed-emissions information (Category 15, see paragraphs 29A-29C as amended).", "ghg_scope3_cats", "narrative"),
 ("S2.29(b)", S2, "Metrics and Targets", "Assets exposed to transition risks", "Amount and percentage of assets or business activities vulnerable to climate-related transition risks.", "", "quantitative"),
 ("S2.29(c)", S2, "Metrics and Targets", "Assets exposed to physical risks", "Amount and percentage of assets or business activities vulnerable to climate-related physical risks.", "", "quantitative"),
 ("S2.29(d)", S2, "Metrics and Targets", "Assets aligned with opportunities", "Amount and percentage of assets or business activities aligned with climate-related opportunities.", "", "quantitative"),
 ("S2.29(e)", S2, "Metrics and Targets", "Capital deployment", "Amount of capital expenditure, financing or investment deployed towards climate-related risks and opportunities.", "", "quantitative"),
 ("S2.29(f)", S2, "Metrics and Targets", "Internal carbon price", "Whether and how an internal carbon price is applied in decision-making, and the price per tonne of greenhouse gas emissions.", "", "quantitative"),
 ("S2.29(g)", S2, "Metrics and Targets", "Remuneration", "Whether and how climate-related considerations are factored into executive remuneration, and the percentage of executive remuneration linked to them.", "targets", "quantitative"),
 ("S2.32", S2, "Metrics and Targets", "Industry-based metrics", "Industry-based metrics associated with the business model and activities (consider the Industry-based Guidance on implementing IFRS S2).", "sasb", "quantitative"),
 ("S2.33", S2, "Metrics and Targets", "Climate-related targets", "For each target: the metric, objective, part of the entity covered, period, base period, milestones and interim targets, absolute or intensity, and how the latest international climate agreement informed it.", "targets", "narrative"),
 ("S2.34", S2, "Metrics and Targets", "Approach to setting and reviewing targets", "How targets are set and reviewed and progress monitored: third-party validation, review process, progress metrics, and revisions with reasons.", "targets", "narrative"),
 ("S2.35", S2, "Metrics and Targets", "Performance against targets", "Performance against each target, with analysis of trends or changes.", "targets", "quantitative"),
 ("S2.36", S2, "Metrics and Targets", "Greenhouse gas emissions targets", "For emissions targets: gases and scopes covered, gross or net (and the gross target if net), whether a sectoral decarbonisation approach was used, and planned use of carbon credits.", "targets", "narrative"),
 # ------------------------------------------------------------------ IFRS S1 governance
 ("S1.27(a)", S1, "Governance", "Oversight body or individual", "Identify the body or individual overseeing sustainability-related risks and opportunities, and how responsibilities, skills, information flow, strategy integration and target oversight work.", "", "narrative"),
 ("S1.27(b)", S1, "Governance", "Management's role", "Management's role in the governance processes, including delegation and the controls and procedures used.", "", "narrative"),
 # ------------------------------------------------------------------ IFRS S1 strategy
 ("S1.30(a)", S1, "Strategy", "Risks and opportunities", "Describe the sustainability-related risks and opportunities that could reasonably be expected to affect prospects.", "materiality", "narrative"),
 ("S1.30(b)", S1, "Strategy", "Time horizons of effects", "For each risk and opportunity, the short-, medium- or long-term horizon over which its effects could occur.", "", "narrative"),
 ("S1.30(c)", S1, "Strategy", "Definition of horizons", "How short, medium and long term are defined and how they link to strategic planning horizons.", "", "narrative"),
 ("S1.32", S1, "Strategy", "Business model and value chain", "Current and anticipated effects on the business model and value chain, and where they are concentrated.", "", "narrative"),
 ("S1.33", S1, "Strategy", "Strategy and decision-making", "How the entity has responded, and plans to respond, in strategy and decision-making; progress against prior plans; trade-offs considered.", "", "narrative"),
 ("S1.34", S1, "Strategy", "Current and anticipated financial effects", "Effects on financial position, performance and cash flows in the period, and anticipated effects over the short, medium and long term.", "", "quantitative"),
 ("S1.35", S1, "Strategy", "Detailed financial effects", "Effect in the period, risk of material adjustment next year, expected changes in financial position, performance and cash flows.", "", "quantitative"),
 ("S1.41", S1, "Strategy", "Resilience", "Qualitative and, where applicable, quantitative assessment of the resilience of strategy and business model, with method and time horizon.", "scenario", "narrative"),
 # ------------------------------------------------------------------ IFRS S1 risk management
 ("S1.44(a)", S1, "Risk Management", "Risk identification and prioritisation", "Processes and policies to identify, assess, prioritise and monitor risks: inputs, scenario analysis, nature/likelihood/magnitude, prioritisation, monitoring, change from last period.", "", "narrative"),
 ("S1.44(b)", S1, "Risk Management", "Opportunity processes", "Processes to identify, assess, prioritise and monitor opportunities.", "", "narrative"),
 ("S1.44(c)", S1, "Risk Management", "Integration into overall risk management", "The extent to which and how these processes are integrated into, and inform, overall risk management.", "", "narrative"),
 # ------------------------------------------------------------------ IFRS S1 metrics and targets
 ("S1.46", S1, "Metrics and Targets", "Metrics", "Metrics required by an applicable standard for each material risk or opportunity, and the metrics used to measure and monitor each and performance against it.", "materiality", "quantitative"),
 ("S1.49-50", S1, "Metrics and Targets", "Metric sources and definitions", "For metrics from outside the ISSB Standards: name the source. For entity-developed metrics: definition, absolute/relative/qualitative, third-party validation, calculation method and limitations.", "", "narrative"),
 ("S1.51", S1, "Metrics and Targets", "Targets", "For each target: metric, quantitative or qualitative target, period, base period, milestones, performance with trend analysis, and revisions with reasons.", "targets", "narrative"),
 ("S1.52", S1, "Metrics and Targets", "Consistency over time", "Metric definitions and calculations are consistent over time; if redefined or replaced, apply paragraph B52 (comparatives, explanation).", "", "narrative"),
 # ------------------------------------------------------------------ IFRS S1 general requirements
 ("S1.21", S1, "General", "Connected information", "Show the connections between related items, and between sustainability disclosures and other general purpose financial reports.", "", "narrative"),
 ("S1.22-24", S1, "General", "Link to the financial statements", "Identify the related financial statements; use data and assumptions consistent with them, as far as possible; use the financial statements' presentation currency.", "", "narrative"),
 ("S1.72", S1, "General", "Statement of compliance", "Make an explicit and unreserved statement of compliance only if every requirement of the ISSB Standards is met.", "", "narrative"),
]


def codes():
    return [r[0] for r in REQUIREMENTS]
