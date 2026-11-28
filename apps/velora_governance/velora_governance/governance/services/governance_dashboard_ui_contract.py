"""v4.6 dashboard UI contract and safe display normalization."""
from collections import Counter


def build_dashboard_view_model(dashboard, *, visible_sections=None, max_attention_items=20):
    dashboard = dashboard or {}
    allowed = set(visible_sections or dashboard.keys())
    model = {key: value for key, value in dashboard.items() if key in allowed}
    attention = list(model.get("attention_items") or model.get("attention_queue") or [])
    model["attention_items"] = attention[:max(0, int(max_attention_items))]
    model["attention_truncated"] = len(attention) > len(model["attention_items"])
    model["section_counts"] = dict(Counter(model.keys()))
    model["view_contract_version"] = "4.6.0"
    return model
