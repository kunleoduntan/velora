from velora import get_doc, get_list, new_doc

SEED_DATA = {
    "Governance Entity Type": ("type_name", ["Company", "Subsidiary", "Holding Company", "Public Institution", "NGO", "Association", "Cooperative", "Trust", "Foundation", "Other"]),
    "Board Type": ("board_type_name", ["Board of Directors", "Governing Council", "Trustees", "Management Board", "Advisory Board", "Other"]),
    "Board Appointment Type": ("appointment_type_name", ["Executive Director", "Non-Executive Director", "Independent Non-Executive Director", "Nominee Director", "Alternate Director", "Chairman", "Vice Chairman", "Trustee", "Council Member", "Advisory Member", "Other"]),
    "Director Classification": ("classification_name", ["Executive", "Non-Executive", "Independent Non-Executive", "Nominee", "Alternate", "Trustee", "Council", "Advisory", "Other"]),
    "Director Independence Status": ("independence_status_name", ["Independent", "Non-Independent", "Not Applicable", "Pending Assessment"]),
    "Governance Skill Category": ("category_name", ["Finance", "Accounting", "Audit", "Risk Management", "Legal", "Corporate Governance", "Strategy", "Technology", "Cybersecurity", "Human Resources", "Operations", "Industry Knowledge", "Sustainability", "Climate", "Investment", "Insurance", "Regulatory", "International Business", "Other"]),
    "Governance Skill Level": ("level_name", ["Basic Awareness", "Working Knowledge", "Experienced", "Expert"]),
    "Governance Event Type": ("event_type_name", ["Board Meeting", "Committee Meeting", "Annual General Meeting", "Annual Board Evaluation", "Director Appointment Expiry", "Director Reappointment", "Governance Policy Review", "Statutory Filing", "Annual Return", "Conflict Declaration Renewal", "Sustainability Reporting Deadline", "Governance Training", "Corporate Event", "Compliance Obligation Due", "Corporate Filing Due", "Annual Return Due", "Statutory Register Review", "Regulatory Correspondence Due", "Policy Review", "Governance Control Testing", "Board Evaluation Due", "Succession Plan Review", "Other"]),
    "Board Committee Type": ("committee_type_name", ["Audit", "Risk", "Finance", "Remuneration", "Nomination and Governance", "Investment", "Sustainability", "Technology", "Other"]),
    "Governance Meeting Type": ("meeting_type_name", ["Board Meeting", "Committee Meeting", "Annual General Meeting", "Special Meeting", "Circular Resolution Meeting", "Ad Hoc Meeting", "Other"]),
    "Board Agenda Category": ("category_name", ["Approval", "Information", "Discussion", "Strategy", "Risk", "Finance", "Compliance", "Sustainability", "Human Resources", "Operations", "Other"]),
    "Board Paper Type": ("paper_type_name", ["Financial", "Risk", "Compliance", "Strategy", "Investment", "Sustainability", "Human Resources", "Operations", "Other"]),
    "Board Resolution Type": ("resolution_type_name", ["Simple Majority", "Two Thirds Majority", "Three Quarters Majority", "Unanimous", "Other"]),
    "Meeting Decision Type": ("decision_type_name", ["Decision", "Resolution", "Action", "Noted", "Recommendation", "Deferred", "Other"]),
    "Board Action Type": ("action_type_name", ["Board Decision", "Resolution Implementation", "Committee Action", "Compliance Action", "Other"]),
    "Regulatory Authority": ("authority_name", ["Corporate Affairs Commission (CAC)", "Securities and Exchange Commission (SEC)", "Financial Reporting Council (FRC)", "National Insurance Commission (NAICOM)", "Central Bank of Nigeria (CBN)", "National Information Technology Development Agency (NITDA)", "Other"]),
    "Statutory Register Type": ("register_type_name", ["Directors", "Company Secretaries", "Shareholders", "Beneficial Owners", "Share Capital", "Charges", "Related Parties", "Directors' Interests in Shares and Debentures", "Debenture Holders", "Persons with Significant Control", "Minutes of General Meetings", "Minutes of Board Meetings", "Other"]),
    "Corporate Event Type": ("event_type_name", ["Director Appointment", "Director Resignation", "Secretary Appointment", "Secretary Resignation", "Share Issue", "Share Transfer", "Share Capital Change", "Registered Office Change", "Company Name Change", "Beneficial Ownership Change", "Merger", "Acquisition", "Dissolution", "Other"]),
    "Share Class": ("share_class_name", ["Ordinary", "Preference", "Deferred", "Other"]),
    "Governance Policy Type": ("policy_type_name", ["Code of Conduct", "Corporate Governance", "Risk Management", "Conflict of Interest", "Related Party Transactions", "Whistleblowing", "Anti-Bribery and Corruption", "Sustainability", "Data Protection", "Other"]),
    "Sustainability Disclosure Type": ("disclosure_type_name", ["Governance", "Strategy", "Risk Management", "Metrics and Targets", "Environmental", "Social", "Climate", "Other"]),
    "Sustainability Topic": ("topic_name", ["Climate Change", "Energy", "Emissions", "Water", "Waste", "Biodiversity", "Own Workforce", "Value Chain Workers", "Communities", "Human Rights", "Health and Safety", "Diversity and Inclusion", "Business Conduct", "Governance", "Data Privacy", "Other"]),
    "Sustainability Metric Category": ("category_name", ["Environmental", "Social", "Governance", "Climate", "Economic", "Other"]),
    "Stakeholder Type": ("stakeholder_type_name", ["Employees", "Customers", "Suppliers", "Investors", "Communities", "Regulators", "Board", "NGO", "Other"]),
    "Sustainability Initiative Category": ("initiative_category_name", ["Energy Efficiency", "Emissions Reduction", "Waste Reduction", "Water", "Social Impact", "Human Capital", "Governance", "Climate Adaptation", "Other"]),
    "Sustainability Risk Category": ("risk_category_name", ["Physical Climate", "Transition Climate", "Environmental", "Social", "Governance", "Supply Chain", "Human Capital", "Other"]),
    "Sustainability Opportunity Category": ("opportunity_category_name", ["Energy Efficiency", "Renewable Energy", "Product Innovation", "Market Access", "Resource Efficiency", "Human Capital", "Other"]),
    "Emission Source Category": ("source_category_name", ["Stationary Combustion", "Mobile Combustion", "Process Emissions", "Fugitive Emissions", "Purchased Electricity", "Purchased Heat/Steam", "Business Travel", "Employee Commuting", "Purchased Goods and Services", "Other Scope 3"]),
    "Sustainability Unit": ("unit_name", ["kg", "tonne", "tCO2e", "kWh", "MWh", "litre", "m3", "km", "miles", "number", "percent", "hours", "currency", "other"]),
    "Sustainability Data Quality": ("quality_name", ["High", "Medium", "Low", "Estimated", "Unverified"]),
}


GOVERNANCE_ROLES = {
    "Governance Administrator": "Full governance application configuration and administration.",
    "Company Secretary": "Corporate secretarial operations, board administration and governance records.",
    "Governance Officer": "Assigned governance operations and register maintenance.",
    "Board Member": "Board-facing access role reserved for the secure Board Portal release.",
    "Compliance Officer": "Governance and regulatory compliance operations.",
    "Sustainability Officer": "Sustainability data collection, metrics and disclosure preparation.",
    "Internal Auditor": "Read-only governance assurance access, subject to scope controls.",
    "Committee Chair": "Committee-facing access role reserved for committee portal functionality.",
    "Committee Member": "Committee-facing access role reserved for committee portal functionality.",
}

def ensure_governance_roles():
    """Create the application's company-local roles through the native Role Administration service."""
    from velora import db
    from velora.permissions import get_session
    from velora.controlplane.role_admin import RoleAdministration
    actor = get_session()
    service = RoleAdministration(db.get_engine())
    existing = {row["name"] for row in service.list_roles(actor)}
    created = []
    for name, description in GOVERNANCE_ROLES.items():
        if name not in existing:
            service.create_role(actor, name, description)
            created.append(name)
    return created

SKILL_LEVEL_ORDER = {"Basic Awareness": 1, "Working Knowledge": 2, "Experienced": 3, "Expert": 4}
EVENT_REMINDERS = {"Board Meeting": 14, "Committee Meeting": 14, "Annual General Meeting": 30, "Annual Board Evaluation": 30, "Director Appointment Expiry": 180, "Director Reappointment": 90, "Governance Policy Review": 30, "Statutory Filing": 30, "Annual Return": 30, "Conflict Declaration Renewal": 30, "Sustainability Reporting Deadline": 60, "Governance Training": 14, "Corporate Event": 30, "Compliance Obligation Due": 30, "Corporate Filing Due": 30, "Annual Return Due": 30, "Statutory Register Review": 30, "Regulatory Correspondence Due": 7, "Policy Review": 30, "Governance Control Testing": 30, "Board Evaluation Due": 30, "Succession Plan Review": 30, "Other": 7}


def seed_reference_data():
    """Idempotently seed starter configuration masters; users can edit/deactivate them."""
    created = 0
    for doctype, (field, values) in SEED_DATA.items():
        existing = {str(row.get(field) or "") for row in get_list(doctype, fields=[field], limit=1000, ignore_permissions=True)}
        for value in values:
            if value in existing:
                continue
            payload = {field: value, "active": 1}
            if doctype == "Governance Skill Level":
                payload["level_order"] = SKILL_LEVEL_ORDER[value]
            if doctype == "Governance Event Type":
                payload["default_reminder_days"] = EVENT_REMINDERS.get(value, 7)
            if doctype == "Board Resolution Type":
                payload["approval_threshold_percent"] = {"Simple Majority":51,"Two Thirds Majority":67,"Three Quarters Majority":75,"Unanimous":100,"Other":50}.get(value,51)
            if doctype == "Board Action Type":
                payload["default_due_days"] = 14
            new_doc(doctype, **payload).insert(ignore_permissions=True)
            created += 1
    return created



def seed_gwp_sets():
    """Idempotently seed the IPCC AR5 and AR6 100-year GWP sets (editable data: verify against the edition your regulator requires)."""
    from velora_governance.governance.services.ghg_accounting import GWP_SETS
    existing = {r["set_name"] for r in get_list("GWP Set", fields=["set_name"], limit=100, ignore_permissions=True)}
    created = 0
    for name, values in GWP_SETS.items():
        if name in existing:
            continue
        new_doc("GWP Set", set_name=name, source_reference="IPCC Assessment Report, 100-year time horizon, without climate-carbon feedbacks", horizon_years=100, active=1,
                values=[{"gas": gas, "gwp": gwp} for gas, gwp in values.items()]).insert(ignore_permissions=True)
        created += 1
    return created


NCCG_2018 = [
    ("A. Board of Directors and Officers of the Board", ["Role of the Board", "Board Structure and Composition", "Chairman", "Managing Director/Chief Executive Officer", "Executive Directors", "Non-Executive Directors", "Independent Non-Executive Directors", "Company Secretary", "Access to Independent Advice", "Meetings of the Board", "Board Committees", "Appointment to the Board", "Induction and Continuing Education", "Board Evaluation", "Corporate Governance Evaluation", "Remuneration Governance"]),
    ("B. Assurance", ["Risk Management", "Internal Audit Function", "Whistle-blowing", "External Auditors"]),
    ("C. Relationship with Shareholders", ["General Meetings", "Shareholder Engagement", "Protection of Shareholder Rights"]),
    ("D. Business Conduct and Ethics", ["Business Conduct and Ethics", "Ethical Culture"]),
    ("E. Sustainability", ["Sustainability"]),
    ("F. Transparency", ["Stakeholder Communication", "Disclosures"]),
]


def seed_governance_codes():
    """Idempotently seed the Nigerian Code of Corporate Governance 2018 (FRC): its six parts and 28 principle titles, for apply-and-explain assessments."""
    from velora_governance.governance.services.nccg_practices import practices
    existing = get_list("Governance Code", filters=[["code_name", "=", "Nigerian Code of Corporate Governance 2018"]], fields=["name"], limit=1, ignore_permissions=True)
    prows = [{"principle_number": n, "reference": ref, "requirement": text} for n, ref, text in practices()]
    if existing:
        code = get_doc("Governance Code", existing[0]["name"], ignore_permissions=True)
        if (code.get("practices") or []):
            return 0
        code.set("practices", prows)
        code.save(ignore_permissions=True)
        return 1
    rows, n = [], 0
    for part, titles in NCCG_2018:
        for title in titles:
            n += 1
            rows.append({"principle_number": n, "part": part, "title": title})
    new_doc("Governance Code", code_name="Nigerian Code of Corporate Governance 2018", issuer="Financial Reporting Council of Nigeria", edition_year=2018,
            approach="Apply and explain", active=1, principles=rows, practices=prows,
            notes="Principles and recommended practices (paraphrased, with the Code's reference numbers). Read the published Code for the exact wording; sector codes and SEC guidelines add practices not listed here.").insert(ignore_permissions=True)
    return 1


def seed_regulatory_defaults():
    """Idempotently seed starter Nigerian regulatory requirements and filing templates."""
    authorities = get_list("Regulatory Authority", fields=["name", "authority_name", "country"], limit=1000, ignore_permissions=True)
    authority_map = {row["authority_name"]: row["name"] for row in authorities}
    entity_types = get_list("Governance Entity Type", fields=["name", "type_name"], limit=1000, ignore_permissions=True)
    company_type = next((row["name"] for row in entity_types if row.get("type_name") == "Company"), None)
    requirements = [
        ("CAC-AR", "Annual Return", "Corporate Affairs Commission (CAC)", "Filing", "Annual"),
        ("CAC-DIR", "Director or Secretary Change", "Corporate Affairs Commission (CAC)", "Corporate Event", "Event-Based"),
        ("CAC-SHARE", "Share Capital or Shareholder Change", "Corporate Affairs Commission (CAC)", "Corporate Event", "Event-Based"),
        ("CAC-BO", "Beneficial Ownership Update", "Corporate Affairs Commission (CAC)", "Compliance", "Event-Based"),
        ("FRC-FS", "Annual Financial Statements Filing", "Financial Reporting Council (FRC)", "Filing", "Annual"),
        ("FRC-SRG1", "Sustainability Reporting Disclosure", "Financial Reporting Council (FRC)", "Disclosure", "Annual"),
        ("NAICOM-LR", "Insurance License Renewal", "National Insurance Commission (NAICOM)", "License", "Annual"),
        ("NAICOM-AR", "Insurance Regulatory Return", "National Insurance Commission (NAICOM)", "Filing", "Quarterly"),
        ("SEC-AR", "Securities Annual Compliance Report", "Securities and Exchange Commission (SEC)", "Filing", "Annual"),
        ("CBN-QR", "Quarterly Banking Regulatory Return", "Central Bank of Nigeria (CBN)", "Filing", "Quarterly"),
        ("NITDA-DP", "Data Protection Compliance", "National Information Technology Development Agency (NITDA)", "Compliance", "Annual"),
    ]
    existing_codes = {row["requirement_code"] for row in get_list("Regulatory Requirement", fields=["requirement_code"], limit=1000, ignore_permissions=True)}
    created = 0
    for code, title, authority_name, req_type, frequency in requirements:
        if code in existing_codes or authority_name not in authority_map:
            continue
        new_doc("Regulatory Requirement", requirement_code=code, requirement_title=title, authority=authority_map[authority_name],
            jurisdiction="NG", requirement_type=req_type, frequency=frequency, applicable_entity_type=company_type,
            description=f"Starter compliance requirement for Nigerian entities. Confirm applicability and deadlines with the relevant authority.", active=1).insert(ignore_permissions=True)
        created += 1
    filing_templates = [
        ("CAC Annual Return", "Corporate Affairs Commission (CAC)", "Annual", 30),
        ("CAC Director or Secretary Change", "Corporate Affairs Commission (CAC)", "Event-Based", 14),
        ("CAC Share Capital or Transfer Change", "Corporate Affairs Commission (CAC)", "Event-Based", 14),
        ("CAC Beneficial Ownership Change", "Corporate Affairs Commission (CAC)", "Event-Based", 14),
        ("FRC Financial Statements Filing", "Financial Reporting Council (FRC)", "Annual", 30),
        ("FRC Sustainability Reporting", "Financial Reporting Council (FRC)", "Annual", 60),
        ("NAICOM License Renewal", "National Insurance Commission (NAICOM)", "Annual", 90),
        ("NAICOM Regulatory Return", "National Insurance Commission (NAICOM)", "Quarterly", 30),
        ("SEC Annual Compliance", "Securities and Exchange Commission (SEC)", "Annual", 30),
        ("CBN Quarterly Return", "Central Bank of Nigeria (CBN)", "Quarterly", 30),
    ]
    existing_filing_names = {row["filing_requirement_name"] for row in get_list("Filing Requirement", fields=["filing_requirement_name"], limit=1000, ignore_permissions=True)}
    for title, authority_name, frequency, lead in filing_templates:
        if title in existing_filing_names or authority_name not in authority_map:
            continue
        new_doc("Filing Requirement", filing_requirement_name=title, authority=authority_map[authority_name], jurisdiction="NG",
            entity_type=company_type, frequency=frequency, default_lead_days=lead, description="Starter filing template; confirm current statutory due dates and applicability.", active=1).insert(ignore_permissions=True)
        created += 1
    return created


def seed_sustainability_defaults():
    """Idempotently seed reporting frameworks, standards, disclosure mappings and starter metrics."""
    framework_rows = [
        ("IFRS S1","IFRS-S1","2023","International"),("IFRS S2","IFRS-S2","2023","International"),
        ("GRI Standards","GRI","Current","International"),("SASB Standards","SASB","Current","International"),
        ("ESRS","ESRS","2023","European Union"),("GHG Protocol","GHG","Corporate Standard","International"),
        ("UN Sustainable Development Goals","SDG","2015","International"),("FRC Sustainability Reporting Guideline 1","FRC-SRG1","SRG 1","Nigeria"),
    ]
    existing={r["framework_name"]:r["name"] for r in get_list("Sustainability Framework",fields=["name","framework_name"],limit=1000,ignore_permissions=True)}
    for name,code,version,jurisdiction in framework_rows:
        if name in existing:continue
        new_doc("Sustainability Framework",framework_name=name,framework_code=code,version=version,jurisdiction=jurisdiction,mandatory=0,description="Configurable reporting framework. Confirm current applicability and requirements for the reporting entity.",active=1).insert(ignore_permissions=True)
    frameworks={r["framework_name"]:r["name"] for r in get_list("Sustainability Framework",fields=["name","framework_name"],limit=1000,ignore_permissions=True)}
    topics={r["topic_name"]:r["name"] for r in get_list("Sustainability Topic",fields=["name","topic_name"],limit=1000,ignore_permissions=True)}
    standards=[
        ("IFRS S1","IFRS-S1","General Requirements for Sustainability-related Financial Disclosures","2023","Governance"),
        ("IFRS S2","IFRS-S2","Climate-related Disclosures","2023","Climate Change"),
        ("GRI Standards","GRI-2","General Disclosures","2021","Governance"),("GRI Standards","GRI-3","Material Topics","2021","Governance"),
        ("GRI Standards","GRI-302","Energy","2016","Energy"),("GRI Standards","GRI-305","Emissions","2016","Emissions"),
        ("GRI Standards","GRI-306","Waste","2020","Waste"),("GRI Standards","GRI-401","Employment","2016","Own Workforce"),
        ("GRI Standards","GRI-403","Occupational Health and Safety","2018","Health and Safety"),("GRI Standards","GRI-404","Training and Education","2016","Own Workforce"),
        ("GRI Standards","GRI-405","Diversity and Equal Opportunity","2016","Diversity and Inclusion"),("GRI Standards","GRI-413","Local Communities","2016","Communities"),
        ("ESRS","ESRS-E1","Climate Change","2023","Climate Change"),("ESRS","ESRS-S1","Own Workforce","2023","Own Workforce"),
        ("ESRS","ESRS-S2","Workers in the Value Chain","2023","Value Chain Workers"),("ESRS","ESRS-G1","Business Conduct","2023","Business Conduct"),
        ("GHG Protocol","GHG-CORP","GHG Protocol Corporate Standard","Current","Emissions"),
        ("FRC Sustainability Reporting Guideline 1","FRC-SRG1","Sustainability Reporting Guideline 1","SRG 1","Governance"),
        ("SASB Standards","SASB-INDUSTRY","SASB Industry Standards","Current","Other"),("UN Sustainable Development Goals","SDG-GOALS","UN Sustainable Development Goals","2015","Other"),
    ]
    existing_codes={r["standard_code"] for r in get_list("Sustainability Standard",fields=["standard_code"],limit=1000,ignore_permissions=True)}
    standard_map={}
    for framework,code,title,version,topic in standards:
        if code in existing_codes:continue
        standard=new_doc("Sustainability Standard",framework=frameworks.get(framework),standard_code=code,standard_title=title,version=version,topic=topics.get(topic),description="Starter mapping; standards and disclosure requirements are configurable.",active=1)
        standard.insert(ignore_permissions=True)
        standard_map[code]=standard.name
    standard_map.update({r["standard_code"]:r["name"] for r in get_list("Sustainability Standard",fields=["name","standard_code"],limit=1000,ignore_permissions=True)})
    disclosure_types={r["disclosure_type_name"]:r["name"] for r in get_list("Sustainability Disclosure Type",fields=["name","disclosure_type_name"],limit=1000,ignore_permissions=True)}
    disclosures=[
        ("IFRS S1","IFRS-S1","S1-GOV","Governance Oversight","Governance","Governance","Board and management oversight of sustainability-related risks and opportunities."),
        ("IFRS S1","IFRS-S1","S1-STR","Strategy","Strategy","Governance","Sustainability-related risks and opportunities and their effects on strategy and financial planning."),
        ("IFRS S1","IFRS-S1","S1-RM","Risk Management","Risk Management","Governance","Processes for identifying, assessing, prioritizing and monitoring sustainability-related risks and opportunities."),
        ("IFRS S1","IFRS-S1","S1-MT","Metrics and Targets","Metrics and Targets","Governance","Metrics and targets used to assess sustainability-related risks and opportunities."),
        ("IFRS S2","IFRS-S2","S2-GOV","Climate Governance","Governance","Climate Change","Governance oversight of climate-related risks and opportunities."),
        ("IFRS S2","IFRS-S2","S2-STR","Climate Strategy","Strategy","Climate Change","Climate-related risks and opportunities and effects on strategy."),
        ("IFRS S2","IFRS-S2","S2-RM","Climate Risk Management","Risk Management","Climate Change","Processes for identifying, assessing and managing climate risks."),
        ("IFRS S2","IFRS-S2","S2-MT","Climate Metrics and Targets","Metrics and Targets","Climate Change","Climate-related metrics, targets and performance."),
        ("IFRS S2","IFRS-S2","S2-RES","Climate Resilience","Climate","Climate Change","Climate resilience and scenario analysis disclosures."),
        ("IFRS S2","IFRS-S2","S2-GHG","GHG Emissions","Environmental","Emissions","Scope 1, Scope 2 and Scope 3 greenhouse gas emissions disclosures."),
        ("FRC Sustainability Reporting Guideline 1","FRC-SRG1","SRG1-GOV","Governance","Governance","Governance","Sustainability governance oversight and accountability."),
        ("FRC Sustainability Reporting Guideline 1","FRC-SRG1","SRG1-STR","Strategy","Strategy","Governance","Sustainability strategy and impacts."),
        ("FRC Sustainability Reporting Guideline 1","FRC-SRG1","SRG1-RISK","Risk Management","Risk Management","Governance","Sustainability risk management."),
        ("FRC Sustainability Reporting Guideline 1","FRC-SRG1","SRG1-MET","Metrics and Targets","Metrics and Targets","Governance","Sustainability metrics, targets and performance."),
        ("GRI Standards","GRI-2","GRI-2-GENERAL","General Disclosures","Governance","Governance","General organizational disclosures."),
        ("GRI Standards","GRI-3","GRI-3-MATERIAL","Material Topics","Governance","Governance","Material topics and impact assessment."),
        ("GRI Standards","GRI-302","GRI-302-ENERGY","Energy","Environmental","Energy","Energy consumption, intensity and reduction initiatives."),
        ("GRI Standards","GRI-305","GRI-305-EMISSIONS","Emissions","Environmental","Emissions","Greenhouse gas emissions and intensity."),
        ("GRI Standards","GRI-306","GRI-306-WASTE","Waste","Environmental","Waste","Waste generation, diversion and disposal."),
        ("GRI Standards","GRI-401","GRI-401-EMPLOYMENT","Employment","Social","Own Workforce","Employment practices and workforce metrics."),
        ("GRI Standards","GRI-403","GRI-403-SAFETY","Occupational Health and Safety","Social","Health and Safety","Occupational health and safety management and metrics."),
        ("GRI Standards","GRI-404","GRI-404-TRAINING","Training and Education","Social","Own Workforce","Employee training and education."),
        ("GRI Standards","GRI-405","GRI-405-DIVERSITY","Diversity and Equal Opportunity","Social","Diversity and Inclusion","Diversity metrics and equal opportunity."),
        ("GRI Standards","GRI-413","GRI-413-COMMUNITY","Local Communities","Social","Communities","Community engagement and impacts."),
        ("ESRS","ESRS-E1","ESRS-E1-CLIMATE","Climate Change","Climate","Climate Change","Climate-related impacts, risks, opportunities, metrics and targets."),
        ("ESRS","ESRS-S1","ESRS-S1-WORKFORCE","Own Workforce","Social","Own Workforce","Own workforce impacts, policies, metrics and targets."),
        ("ESRS","ESRS-S2","ESRS-S2-VALUECHAIN","Workers in Value Chain","Social","Value Chain Workers","Value-chain worker impacts, policies, metrics and targets."),
        ("ESRS","ESRS-G1","ESRS-G1-CONDUCT","Business Conduct","Governance","Business Conduct","Business conduct policies, culture and controls."),
        ("GHG Protocol","GHG-CORP","GHG-SCOPE1","Scope 1 Emissions","Environmental","Emissions","Direct greenhouse gas emissions from owned or controlled sources."),
        ("GHG Protocol","GHG-CORP","GHG-SCOPE2","Scope 2 Emissions","Environmental","Emissions","Indirect emissions from purchased electricity, heat or steam."),
        ("GHG Protocol","GHG-CORP","GHG-SCOPE3","Scope 3 Emissions","Environmental","Emissions","Other indirect emissions across the value chain."),
        ("SASB Standards","SASB-INDUSTRY","SASB-INDUSTRY-MAPPING","Industry Disclosure Mapping","Other","Other","Configure industry-specific SASB disclosure topics and metrics."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-01","Goal 1: No Poverty","Social","Communities","Map initiatives and impacts to Sustainable Development Goal 1."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-02","Goal 2: Zero Hunger","Social","Communities","Map initiatives and impacts to Sustainable Development Goal 2."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-03","Goal 3: Good Health and Well-being","Social","Health and Safety","Map initiatives and impacts to Sustainable Development Goal 3."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-04","Goal 4: Quality Education","Social","Own Workforce","Map initiatives and impacts to Sustainable Development Goal 4."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-05","Goal 5: Gender Equality","Social","Diversity and Inclusion","Map initiatives and impacts to Sustainable Development Goal 5."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-06","Goal 6: Clean Water and Sanitation","Environmental","Water","Map initiatives and impacts to Sustainable Development Goal 6."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-07","Goal 7: Affordable and Clean Energy","Environmental","Energy","Map initiatives and impacts to Sustainable Development Goal 7."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-08","Goal 8: Decent Work and Economic Growth","Social","Own Workforce","Map initiatives and impacts to Sustainable Development Goal 8."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-09","Goal 9: Industry, Innovation and Infrastructure","Other","Other","Map initiatives and impacts to Sustainable Development Goal 9."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-10","Goal 10: Reduced Inequalities","Social","Diversity and Inclusion","Map initiatives and impacts to Sustainable Development Goal 10."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-11","Goal 11: Sustainable Cities and Communities","Social","Communities","Map initiatives and impacts to Sustainable Development Goal 11."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-12","Goal 12: Responsible Consumption and Production","Environmental","Waste","Map initiatives and impacts to Sustainable Development Goal 12."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-13","Goal 13: Climate Action","Climate","Climate Change","Map initiatives and impacts to Sustainable Development Goal 13."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-14","Goal 14: Life Below Water","Environmental","Biodiversity","Map initiatives and impacts to Sustainable Development Goal 14."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-15","Goal 15: Life on Land","Environmental","Biodiversity","Map initiatives and impacts to Sustainable Development Goal 15."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-16","Goal 16: Peace, Justice and Strong Institutions","Governance","Governance","Map initiatives and impacts to Sustainable Development Goal 16."),
        ("UN Sustainable Development Goals","SDG-GOALS","SDG-17","Goal 17: Partnerships for the Goals","Other","Other","Map initiatives and impacts to Sustainable Development Goal 17."),
    ]
    existing_disclosures={r["disclosure_code"] for r in get_list("Sustainability Disclosure",fields=["disclosure_code"],limit=1000,ignore_permissions=True)}
    for framework,standard_code,code,title,disclosure_type,topic,guidance in disclosures:
        if code in existing_disclosures:continue
        new_doc("Sustainability Disclosure",framework=frameworks.get(framework),standard=standard_map.get(standard_code),disclosure_code=code,disclosure_title=title,disclosure_type=disclosure_types.get(disclosure_type),topic=topics.get(topic),required_data="",guidance=guidance,active=1).insert(ignore_permissions=True)
    categories={r["category_name"]:r["name"] for r in get_list("Sustainability Metric Category",fields=["name","category_name"],limit=1000,ignore_permissions=True)}
    units={r["unit_name"]:r["name"] for r in get_list("Sustainability Unit",fields=["name","unit_name"],limit=1000,ignore_permissions=True)}
    metrics=[
        ("ENV-ENERGY","Energy Consumption","Environmental","kWh","Numeric","Annual"),("ENV-EMISSIONS","GHG Emissions","Climate","tCO2e","Numeric","Annual"),
        ("ENV-WATER","Water Consumption","Environmental","m3","Numeric","Annual"),("ENV-WASTE","Waste Generated","Environmental","tonne","Numeric","Annual"),
        ("SOC-TRAINING","Employee Training Hours","Social","hours","Numeric","Annual"),("SOC-DIVERSITY","Female Leadership Representation","Social","percent","Percentage","Annual"),
        ("SOC-SAFETY","Safety Incidents","Social","number","Numeric","Annual"),("GOV-BOARD","Board Governance Metrics","Governance","number","Numeric","Annual"),
    ]
    existing_metric_codes={r["metric_code"] for r in get_list("Sustainability Metric",fields=["metric_code"],limit=1000,ignore_permissions=True)}
    for code,name,category,unit,data_type,frequency in metrics:
        if code in existing_metric_codes or category not in categories or unit not in units:continue
        new_doc("Sustainability Metric",metric_code=code,metric_name=name,category=categories[category],default_unit=units[unit],data_type=data_type,frequency=frequency,description="Starter metric definition. Customize for entity and reporting framework.",active=1).insert(ignore_permissions=True)
    return len(framework_rows)+len(standards)+len(disclosures)+len(metrics)


def ensure_governance_workspace(role_visibility=True):
    """Create/extend the Governance workspace without replacing user customisations."""
    from velora.application_workspaces import listing, save
    current = next((row for row in listing() if row.get("scope") == "company" and row.get("name") == "Governance"), None)
    widgets = list((current or {}).get("layout") or [])
    shortcuts = [
        {"type": "shortcut", "title": "Governance Entities", "description": "Manage legal and organizational entities", "route": "#/app/Governance Entity", "width": 2},
        {"type": "shortcut", "title": "Boards", "description": "Manage boards and governing bodies", "route": "#/app/Board", "width": 2},
        {"type": "shortcut", "title": "Board Members", "description": "Maintain director and governing member profiles", "route": "#/app/Board Member", "width": 2},
        {"type": "shortcut", "title": "Appointments", "description": "Manage appointments, tenure and exit history", "route": "#/app/Board Appointment", "width": 2},
        {"type": "shortcut", "title": "Governance Skills", "description": "Maintain skills catalogue and categories", "route": "#/app/Governance Skill", "width": 2},
        {"type": "shortcut", "title": "Board Skills Matrix", "description": "Assess board skill coverage and gaps", "route": "#/app/Board Skills Matrix", "width": 2},
        {"type": "shortcut", "title": "Governance Calendar", "description": "Track board, compliance and governance events", "route": "#/app/Governance Calendar Event", "width": 2},
        {"type": "shortcut", "title": "Governance Settings", "description": "Configure governance reminders and features", "route": "#/app/Governance Settings", "width": 2},
        {"type": "shortcut", "title": "Committees", "description": "Manage board committees, members and terms", "route": "#/app/Board Committee", "width": 2},
        {"type": "shortcut", "title": "Committee Charters", "description": "Maintain controlled committee charters", "route": "#/app/Board Committee Charter", "width": 2},
        {"type": "shortcut", "title": "Board Meetings", "description": "Schedule meetings, agendas, attendance and quorum", "route": "#/app/Board Meeting", "width": 2},
        {"type": "shortcut", "title": "Board Papers", "description": "Manage paper submissions and circulation", "route": "#/app/Board Paper", "width": 2},
        {"type": "shortcut", "title": "Board Packs", "description": "Track board pack versions and circulation", "route": "#/app/Board Pack", "width": 2},
        {"type": "shortcut", "title": "Meeting Minutes", "description": "Record meeting outcomes and formal decisions", "route": "#/app/Board Meeting Minutes", "width": 2},
        {"type": "shortcut", "title": "Resolutions", "description": "Track resolutions and configurable voting thresholds", "route": "#/app/Board Resolution", "width": 2},
        {"type": "shortcut", "title": "Board Actions", "description": "Track action owners, due dates and progress", "route": "#/app/Board Action", "width": 2},
        {"type": "shortcut", "title": "Governance Exception Centre", "description": "Review, assign, resolve and monitor governance exceptions", "route": "#/governance/exceptions", "width": 2},
        {"type": "shortcut", "title": "Governance User Manual & Feature Notes", "description": "Installation commands, how-to guide, feature notes and DocType catalogue", "route": "#/governance/manual", "width": 2},
        {"type": "shortcut", "title": "Governance Report Centre", "description": "Run executive, board, compliance, risk, exception and sustainability reports", "route": "#/governance/reports", "width": 2},
        {"type": "shortcut", "title": "Governance Automation Monitor", "description": "Monitor queued, running, completed and failed governance automation; retry failed records", "route": "#/governance/automation", "width": 2},
        {"type": "shortcut", "title": "Governance Automation Executions", "description": "Open the persistent automation execution records", "route": "#/app/Governance Automation Execution", "width": 2},
        {"type": "shortcut", "title": "Governance Automation Configuration", "description": "Configure reminder rules, escalation days, retry limits and owner fallback routing", "route": "#/app/Governance Automation Configuration", "width": 2},
    ]
    titles = {w.get("title") for w in widgets}
    widgets.extend(w for w in shortcuts if w["title"] not in titles)
    kpis = [
        {"type": "number", "title": "Governance Entities", "doctype": "Governance Entity", "filters": {}, "width": 1},
        {"type": "number", "title": "Active Boards", "doctype": "Board", "filters": {"board_status": "Active"}, "width": 1},
        {"type": "number", "title": "Active Board Members", "doctype": "Board Member", "filters": {"profile_status": "Active"}, "width": 1},
        {"type": "number", "title": "Active Appointments", "doctype": "Board Appointment", "filters": {"appointment_status": "Active"}, "width": 1},
        {"type": "number", "title": "Open Governance Events", "doctype": "Governance Calendar Event", "filters": {"event_status": "Open"}, "width": 1},
        {"type": "number", "title": "Scheduled Meetings", "doctype": "Board Meeting", "filters": {"meeting_status": "Scheduled"}, "width": 1},
        {"type": "number", "title": "Draft Board Papers", "doctype": "Board Paper", "filters": {"paper_status": "Draft"}, "width": 1},
        {"type": "number", "title": "Open Board Actions", "doctype": "Board Action", "filters": {"action_status": "Open"}, "width": 1},
        {"type": "number", "title": "Adopted Resolutions", "doctype": "Board Resolution", "filters": {"resolution_status": "Adopted"}, "width": 1},
        {"type": "number", "title": "Queued Governance Automations", "doctype": "Governance Automation Execution", "filters": {"execution_status": "Queued"}, "width": 1},
        {"type": "activity", "title": "Recent Governance Activity", "width": 4},
    ]
    titles = {w.get("title") for w in widgets}
    widgets.extend(w for w in kpis if w["title"] not in titles)
    save({"id": (current or {}).get("id"), "name": "Governance", "description": "Corporate governance, boards, committees, meetings, papers, appointments, skills and governance calendar.", "visibility": "roles" if role_visibility else "company", "roles": ["Governance Administrator", "Company Secretary", "Governance Officer"] if role_visibility else [], "widgets": widgets[:30]}, "company")




def ensure_governance_risk_workspace(role_visibility=True):
    from velora.application_workspaces import listing, save
    current=next((row for row in listing() if row.get("scope")=="company" and row.get("name")=="Governance & Risk"),None)
    widgets=list((current or {}).get("layout") or [])
    shortcuts=[
        {"type":"shortcut","title":"Governance Policies","description":"Maintain controlled governance policies and review history","route":"#/app/Governance Policy","width":2},
        {"type":"shortcut","title":"Conflict Declarations","description":"Record and review director conflict declarations","route":"#/app/Conflict of Interest Declaration","width":2},
        {"type":"shortcut","title":"Related Party Interests","description":"Maintain director related-party interest records","route":"#/app/Related Party Interest","width":2},
        {"type":"shortcut","title":"Governance Risks","description":"Assess governance risks and treatments","route":"#/app/Governance Risk","width":2},
        {"type":"shortcut","title":"Governance Controls","description":"Maintain and test governance controls","route":"#/app/Governance Control","width":2},
        {"type":"shortcut","title":"Board Evaluations","description":"Evaluate boards, committees and individual directors","route":"#/app/Board Evaluation","width":2},
        {"type":"shortcut","title":"Director Training","description":"Track governance training and CPD","route":"#/app/Director Training Record","width":2},
        {"type":"shortcut","title":"Succession Plans","description":"Plan board succession and candidate readiness","route":"#/app/Board Succession Plan","width":2},
    ]
    titles={w.get("title") for w in widgets}
    widgets.extend(w for w in shortcuts if w["title"] not in titles)
    kpis=[
        {"type":"number","title":"Active Policies","doctype":"Governance Policy","filters":{"policy_status":"Active"},"width":1},
        {"type":"number","title":"Open Conflict Declarations","doctype":"Conflict of Interest Declaration","filters":{"declaration_status":"Declared"},"width":1},
        {"type":"number","title":"Governance Risks","doctype":"Governance Risk","filters":{"risk_status":"Treating"},"width":1},
        {"type":"number","title":"Controls Due Review","doctype":"Governance Control","filters":{"control_status":"Review Due"},"width":1},
        {"type":"number","title":"Evaluations In Progress","doctype":"Board Evaluation","filters":{"evaluation_status":"In Progress"},"width":1},
        {"type":"number","title":"Training Expired","doctype":"Director Training Record","filters":{"training_status":"Expired"},"width":1},
        {"type":"activity","title":"Governance & Risk Activity","width":4},
    ]
    titles={w.get("title") for w in widgets}
    widgets.extend(w for w in kpis if w["title"] not in titles)
    save({"id":(current or {}).get("id"),"name":"Governance & Risk","description":"Policies, conflict declarations, related-party interests, governance risk, controls, board evaluation, training and succession.","visibility":"roles" if role_visibility else "company","roles":["Governance Administrator","Company Secretary","Governance Officer","Compliance Officer"] if role_visibility else [],"widgets":widgets[:30]},"company")

def ensure_secretariat_workspace(role_visibility=True):
    from velora.application_workspaces import listing, save
    current = next((row for row in listing() if row.get("scope") == "company" and row.get("name") == "Secretariat & Compliance"), None)
    widgets = list((current or {}).get("layout") or [])
    shortcuts = [
        {"type":"shortcut","title":"Corporate Events","description":"Record corporate changes and event-triggered filings","route":"#/app/Corporate Event","width":2},
        {"type":"shortcut","title":"Corporate Filings","description":"Track regulatory submissions and deadlines","route":"#/app/Corporate Filing","width":2},
        {"type":"shortcut","title":"Governance Obligations","description":"Maintain regulatory and governance obligations","route":"#/app/Governance Obligation","width":2},
        {"type":"shortcut","title":"Compliance Assessments","description":"Assess compliance and record evidence","route":"#/app/Compliance Assessment","width":2},
        {"type":"shortcut","title":"Regulatory Correspondence","description":"Manage notices, inquiries and responses","route":"#/app/Regulatory Correspondence","width":2},
        {"type":"shortcut","title":"Statutory Registers","description":"Maintain statutory registers and entries","route":"#/app/Statutory Register","width":2},
        {"type":"shortcut","title":"Shareholder Register","description":"Maintain shareholder and shareholding records","route":"#/app/Shareholder Register","width":2},
        {"type":"shortcut","title":"Shareholders","description":"Maintain shareholder profiles","route":"#/app/Shareholder","width":2},
        {"type":"shortcut","title":"Annual Returns","description":"Prepare and track annual returns","route":"#/app/Annual Return","width":2},
        {"type":"shortcut","title":"Regulatory Requirements","description":"Configure obligations and compliance requirements","route":"#/app/Regulatory Requirement","width":2},
        {"type":"shortcut","title":"Filing Requirements","description":"Configure filing templates and lead times","route":"#/app/Filing Requirement","width":2},
    ]
    titles={w.get("title") for w in widgets}
    widgets.extend(w for w in shortcuts if w["title"] not in titles)
    kpis=[
        {"type":"number","title":"Overdue Obligations","doctype":"Governance Obligation","filters":{"obligation_status":"Overdue"},"width":1},
        {"type":"number","title":"Overdue Filings","doctype":"Corporate Filing","filters":{"filing_status":"Overdue"},"width":1},
        {"type":"number","title":"Open Correspondence","doctype":"Regulatory Correspondence","filters":{"correspondence_status":"Open"},"width":1},
        {"type":"number","title":"Registers Under Review","doctype":"Statutory Register","filters":{"register_status":"Under Review"},"width":1},
        {"type":"number","title":"Annual Returns Overdue","doctype":"Annual Return","filters":{"annual_return_status":"Overdue"},"width":1},
        {"type":"number","title":"Non-Compliant Assessments","doctype":"Compliance Assessment","filters":{"assessment_result":"Non-Compliant"},"width":1},
        {"type":"activity","title":"Recent Secretariat Activity","width":4},
    ]
    titles={w.get("title") for w in widgets}
    widgets.extend(w for w in kpis if w["title"] not in titles)
    save({"id":(current or {}).get("id"),"name":"Secretariat & Compliance","description":"Corporate secretarial registers, statutory filings, regulatory obligations, shareholder records and compliance.","visibility":"roles" if role_visibility else "company","roles":["Governance Administrator","Company Secretary","Governance Officer","Compliance Officer"] if role_visibility else [],"widgets":widgets[:30]},"company")



def ensure_sustainability_settings():
    rows=get_list("Sustainability Settings",fields=["name"],limit=20,ignore_permissions=True)
    if rows:return rows[0]["name"]
    settings=new_doc("Sustainability Settings",default_reporting_period="",enable_esg=1,enable_ghg=1,impact_materiality_threshold=3,financial_materiality_threshold=3,double_materiality_method="Maximum",scope2_methodology="Both",report_readiness_threshold=100)
    settings.insert(ignore_permissions=True)
    return settings.name

def ensure_sustainability_workspace(role_visibility=True):
    from velora.application_workspaces import listing, save
    current=next((row for row in listing() if row.get("scope")=="company" and row.get("name")=="Sustainability"),None)
    widgets=list((current or {}).get("layout") or [])
    shortcuts=[
        {"type":"shortcut","title":"Frameworks","description":"Configure sustainability reporting frameworks","route":"#/app/Sustainability Framework","width":2},
        {"type":"shortcut","title":"Disclosure Mapping","description":"Map standards and disclosure requirements","route":"#/app/Sustainability Disclosure","width":2},
        {"type":"shortcut","title":"Materiality Assessments","description":"Assess impact, financial and double materiality","route":"#/app/Materiality Assessment","width":2},
        {"type":"shortcut","title":"Stakeholders","description":"Maintain stakeholders and engagement records","route":"#/app/Stakeholder","width":2},
        {"type":"shortcut","title":"Metrics & Data","description":"Maintain metrics and sustainability data points","route":"#/app/Sustainability Metric","width":2},
        {"type":"shortcut","title":"Targets & Initiatives","description":"Manage sustainability targets and initiatives","route":"#/app/Sustainability Target","width":2},
        {"type":"shortcut","title":"GHG Accounting","description":"Manage emission sources, factors and calculations","route":"#/app/GHG Calculation","width":2},
        {"type":"shortcut","title":"Sustainability Reports","description":"Build disclosure-linked sustainability reports","route":"#/app/Sustainability Report","width":2},
        {"type":"shortcut","title":"Reporting Periods","description":"Manage annual, quarterly and custom sustainability reporting periods","route":"#/app/Sustainability Reporting Period","width":2},
        {"type":"shortcut","title":"Disclosure Assessments","description":"Track disclosure readiness and missing evidence","route":"#/app/Sustainability Disclosure Assessment","width":2},
        {"type":"shortcut","title":"Report Content Blocks","description":"Review generated sustainability content","route":"#/app/Sustainability Report Content Block","width":2},
        {"type":"shortcut","title":"Review Queue","description":"View assigned report reviews and review status","route":"#/app/Sustainability Report Review","width":2},
        {"type":"shortcut","title":"Review Issues","description":"Track report review findings, severity and resolution","route":"#/app/Sustainability Report Review Issue","width":2},
        {"type":"shortcut","title":"Report Revisions","description":"Review immutable report snapshots and change history","route":"#/app/Sustainability Report Revision","width":2},
        {"type":"shortcut","title":"Report Publications","description":"Publication register, versions, channels and release history","route":"#/app/Sustainability Report Publication","width":2},
        {"type":"shortcut","title":"Report Reviews","description":"Manage report review rounds and comments","route":"#/app/Sustainability Report Review","width":2},
        {"type":"shortcut","title":"Sustainability Settings","description":"Configure reporting thresholds and GHG methodology","route":"#/app/Sustainability Settings","width":2},
        {"type":"shortcut","title":"Executive Reporting Dashboard","description":"Reporting readiness, disclosure gaps, framework progress and task accountability","route":"#/app/sustainability-executive-dashboard","width":2},
        {"type":"shortcut","title":"Reporting Runs","description":"Monitor automated reporting orchestration and generation logs","route":"#/app/Sustainability Reporting Run","width":2},
        {"type":"shortcut","title":"Collection Task Accountability","description":"Review task owners, overdue work and data collection progress","route":"#/app/Sustainability Data Collection Task","width":2},
        {"type":"shortcut","title":"Disclosure Gap Analysis","description":"Prioritise incomplete disclosures, missing data and evidence","route":"#/app/Sustainability Disclosure Assessment","width":2},
    ]
    titles={w.get("title") for w in widgets};widgets.extend(w for w in shortcuts if w["title"] not in titles)
    kpis=[
        {"type":"number","title":"Open Data Collection Tasks","doctype":"Sustainability Data Collection Task","filters":{"task_status":"Open"},"width":1},
        {"type":"number","title":"Overdue Data Tasks","doctype":"Sustainability Data Collection Task","filters":{"task_status":"Overdue"},"width":1},
        {"type":"number","title":"Targets At Risk","doctype":"Sustainability Target","filters":{"target_status":"At Risk"},"width":1},
        {"type":"number","title":"Reports In Review","doctype":"Sustainability Report","filters":{"report_status":"In Review"},"width":1},
        {"type":"number","title":"Disclosure Assessments Open","doctype":"Sustainability Disclosure Assessment","filters":{"assessment_status":"In Progress"},"width":1},
        {"type":"number","title":"Reporting Periods Active","doctype":"Sustainability Reporting Period","filters":{"period_status":"Reporting"},"width":1},
        {"type":"number","title":"GHG Calculations","doctype":"GHG Calculation","width":1},
        {"type":"number","title":"Materiality In Progress","doctype":"Materiality Assessment","filters":{"assessment_status":"In Progress"},"width":1},
        {"type":"number","title":"Disclosure Assessments Ready","doctype":"Sustainability Disclosure Assessment","filters":{"assessment_status":"Ready"},"width":1},
        {"type":"number","title":"Disclosure Assessments Reviewed","doctype":"Sustainability Disclosure Assessment","filters":{"assessment_status":"Reviewed"},"width":1},
        {"type":"number","title":"Returned Reports","doctype":"Sustainability Report","filters":{"report_status":"Returned for Changes"},"width":1},
        {"type":"activity","title":"Sustainability Activity","width":4},
    ]
    titles={w.get("title") for w in widgets};widgets.extend(w for w in kpis if w["title"] not in titles)
    save({"id":(current or {}).get("id"),"name":"Sustainability","description":"ESG, materiality, disclosure mapping, metrics, targets, climate risk, GHG accounting and sustainability reporting.","visibility":"roles" if role_visibility else "company","roles":["Governance Administrator","Sustainability Officer","Company Secretary","Compliance Officer"] if role_visibility else [],"widgets":widgets[:30]},"company")


def ensure_governance_automation_configuration():
    """Seed one native automation configuration record; administrators can edit it later."""
    rows = get_list("Governance Automation Configuration", filters={"name": "GAC"}, fields=["name"], limit=1, ignore_permissions=True)
    if rows:
        return rows[0]["name"]
    doc = new_doc("Governance Automation Configuration", name="GAC", automation_enabled=1,
        reminder_days_before="30,14,7,3,1,0", escalation_days_overdue="1,7,14,30",
        terminal_statuses="Completed,Cancelled,Closed,Resolved", max_attempts=5, max_batch_size=100,
        retry_base_minutes=5, retry_max_hours=24, owner_field_mapping="{}", recipient_overrides="{}")
    doc.insert(ignore_permissions=True)
    return doc.name



def ensure_governance_exception_configuration():
    """Seed the singleton exception policy with safe escalation defaults."""
    from velora_governance.runtime import SINGLE_NAME
    rows=get_list("Governance Exception Configuration",filters=[["name","=",SINGLE_NAME]],fields=["name"],limit=1,ignore_permissions=True)
    if rows: return rows[0]["name"]
    doc=new_doc("Governance Exception Configuration",name=SINGLE_NAME,low_days=1,medium_days=7,high_days=14,critical_days=30,
        low_score=0,medium_score=40,high_score=65,critical_score=85,route_low="",route_medium="",route_high="",route_critical="",
        escalation_after_hours="24,72,168",escalation_targets="{}",evidence_required=1)
    doc.insert(ignore_permissions=True)
    return doc.name


def after_install():
    # App installation hooks run inside the framework install transaction. Seed through
    # the current document transaction, but defer Role Administration (which opens
    # its own engine transaction) until after_migrate to avoid nested SQLite locks.
    seed_reference_data()
    seed_gwp_sets()
    seed_governance_codes()
    seed_regulatory_defaults()
    seed_sustainability_defaults()
    from velora_governance.governance.services.issb_checklist import seed_issb_requirements
    seed_issb_requirements()
    from velora_governance.governance.services.ixbrl_export import seed_concept_map
    seed_concept_map()
    ensure_sustainability_settings()
    ensure_governance_automation_configuration()
    ensure_governance_exception_configuration()
    ensure_governance_workspace(role_visibility=False)
    ensure_secretariat_workspace(role_visibility=False)
    ensure_governance_risk_workspace(role_visibility=False)
    ensure_sustainability_workspace(role_visibility=False)


def after_migrate():
    ensure_governance_roles()
    seed_reference_data()
    seed_gwp_sets()
    seed_governance_codes()
    seed_regulatory_defaults()
    seed_sustainability_defaults()
    from velora_governance.governance.services.issb_checklist import seed_issb_requirements
    seed_issb_requirements()
    from velora_governance.governance.services.ixbrl_export import seed_concept_map
    seed_concept_map()
    ensure_sustainability_settings()
    ensure_governance_automation_configuration()
    ensure_governance_exception_configuration()
    ensure_governance_workspace(role_visibility=True)
    ensure_secretariat_workspace(role_visibility=True)
    ensure_governance_risk_workspace(role_visibility=True)
    ensure_sustainability_workspace(role_visibility=True)
