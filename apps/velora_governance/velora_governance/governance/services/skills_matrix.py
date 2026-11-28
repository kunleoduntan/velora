"""Pure calculation helpers for Board Skills Matrix coverage."""


def calculate_matrix(requirements, member_skills, level_order):
    """Calculate distinct active-member coverage per required skill.

    `member_skills` is an iterable of {member, skill, skill_level}. Duplicate rows
    for the same member/skill are collapsed to that member's highest level.
    If no required skill level is specified, any recorded level qualifies.
    """
    member_skill_levels = {}
    for row in member_skills or []:
        member = str(row.get("member") or "")
        skill = str(row.get("skill") or "")
        level = str(row.get("skill_level") or "")
        if not member or not skill:
            continue
        key = (member, skill)
        rank = int(level_order.get(level, 0))
        member_skill_levels[key] = max(rank, member_skill_levels.get(key, 0))

    output = []
    for req in requirements or []:
        skill = str(req.get("skill") or "")
        required = max(0, int(req.get("minimum_coverage") or 0))
        required_level = str(req.get("required_skill_level") or "")
        threshold = int(level_order.get(required_level, 0)) if required_level else 0
        actual = sum(1 for (member, candidate), rank in member_skill_levels.items()
                    if candidate == skill and (not threshold or rank >= threshold))
        gap = max(0, required - actual)
        output.append({
            "skill": skill,
            "required_skill_level": required_level,
            "required_coverage": required,
            "actual_coverage": actual,
            "coverage_gap": gap,
            "coverage_status": "Met" if gap == 0 else "Gap",
            "critical": int(bool(req.get("critical"))),
            "notes": req.get("notes") or "",
        })
    return output
