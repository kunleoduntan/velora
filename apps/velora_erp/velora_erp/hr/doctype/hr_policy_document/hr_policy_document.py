"""Policy register integrity checks; historical versions remain attached."""
from velora import Document, throw

class HRPolicyDocument(Document):
    def validate(self):
        code=str(getattr(self,"policy_code","") or "").strip()
        title=str(getattr(self,"policy_title","") or "").strip()
        if not code or not title: throw("Policy Code and Policy Title are required.")
        versions=list(getattr(self,"versions",None) or [])
        seen=set()
        old_versions={}
        if getattr(self,"name",None):
            try:
                from velora import get_doc
                previous=get_doc("HR Policy Document",self.name,ignore_permissions=True)
                old_versions={str(getattr(v,"version_number","")):v for v in list(getattr(previous,"versions",None) or [])}
            except Exception:
                old_versions={}
        for version in versions:
            number=str(getattr(version,"version_number","") or "").strip()
            if not number: throw("Every policy version requires a Version Number.")
            if number in seen: throw("Policy Version Numbers must be unique within a policy.")
            seen.add(number)
            if getattr(version,"version_status",None) in {"Approved","Published","Superseded"} and not getattr(version,"approved_by",None):
                throw("Approved, Published and Superseded versions must retain approval evidence.")
            if getattr(version,"version_status",None) == "Published" and not getattr(version,"published_on",None):
                throw("A Published policy version must retain its publication timestamp.")
            previous=old_versions.get(number)
            if previous and getattr(previous,"version_status",None) in {"Approved","Published","Superseded"}:
                for key in ("version_title","version_content","attachment","change_summary","effective_from","supersedes_version"):
                    if getattr(previous,key,None) != getattr(version,key,None):
                        throw(f"Approved policy version {number} is immutable; create a new version instead.")
                old_status=getattr(previous,"version_status",None); new_status=getattr(version,"version_status",None)
                if old_status in {"Published","Superseded"} and new_status not in {"Published","Superseded"}:
                    throw(f"Published policy version {number} cannot be reopened or withdrawn.")
        if old_versions and not set(old_versions).issubset(seen):
            throw("Historical policy versions cannot be deleted; create a new version to replace policy content.")
        if int(getattr(self,"review_cycle_months",12) or 0) < 1:
            throw("Review Cycle must be at least one month.")
        current=str(getattr(self,"current_version","") or "")
        if current and not any(str(getattr(v,"version_number",""))==current and getattr(v,"version_status",None) in {"Published","Superseded"} for v in versions):
            throw("Current Version must refer to a published policy version.")
