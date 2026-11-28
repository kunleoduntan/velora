def score_risk(probability, impact, scale=5):
    """Return configurable probability-impact score and severity band."""
    try: p, i, s = int(probability), int(impact), int(scale)
    except (TypeError, ValueError): raise ValueError("Probability, impact and scale must be integers.")
    if s < 2 or s > 10: raise ValueError("Scale must be between 2 and 10.")
    if not (1 <= p <= s and 1 <= i <= s): raise ValueError("Probability and impact must be within the configured scale.")
    score=p*i; maximum=s*s; ratio=score/maximum
    band="Low" if ratio < .20 else "Moderate" if ratio < .45 else "High" if ratio < .70 else "Critical"
    return {"probability":p,"impact":i,"scale":s,"score":score,"maximum_score":maximum,"severity":band}
