"""Governance time-series analytics and supplied benchmark comparisons."""
from collections import defaultdict


def build_governance_trends(records, *, date_field="date", metric_field="value", period="month", benchmarks=None):
    buckets = defaultdict(list)
    for row in records or []:
        raw = row.get(date_field)
        if not raw:
            continue
        text = str(raw)[:10]
        try:
            year, month, day = (int(x) for x in text.split("-"))
        except Exception:
            continue
        if period == "year":
            key = f"{year:04d}"
        elif period == "quarter":
            key = f"{year:04d}-Q{((month-1)//3)+1}"
        else:
            key = f"{year:04d}-{month:02d}"
        try:
            value = float(row.get(metric_field, 0) or 0)
        except (TypeError, ValueError):
            continue
        buckets[key].append(value)
    series = [{"period": k, "count": len(v), "total": round(sum(v), 4), "average": round(sum(v)/len(v), 4)} for k, v in sorted(buckets.items())]
    supplied = benchmarks or {}
    comparisons = []
    for name, benchmark in supplied.items():
        try:
            actual = series[-1]["total"] if series else 0
            target = float(benchmark)
            comparisons.append({"name": name, "actual": actual, "benchmark": target,
                               "variance": round(actual-target, 4), "variance_percent": round((actual-target)/target*100, 2) if target else None,
                               "source": "user_supplied"})
        except (TypeError, ValueError):
            comparisons.append({"name": name, "benchmark": benchmark, "source": "user_supplied", "status": "invalid_benchmark"})
    return {"period": period, "series": series, "benchmarks": comparisons,
            "benchmark_disclaimer": "Benchmarks are user-supplied; no external or peer benchmarking is implied."}
