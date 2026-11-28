from velora.ops_console import collect_metrics, prometheus_text


def _snapshot():
    return {"health": {"sites": {"count": 3}, "applications": {"registered": ["a", "b"]},
                       "storage": {"total_bytes": 1000, "used_bytes": 600, "free_bytes": 400, "free_percent": 40},
                       "logs": {"recent_error_lines": 2}},
            "databases": {"checked": 4, "healthy": 3},
            "recovery": {"estimated_rpo_hours": 2, "backup_file_count": 5}}


def test_metrics_collect_counts_and_storage():
    metrics = collect_metrics(None, snapshot=_snapshot())
    assert metrics["velora_sites_total"] == 3
    assert metrics["velora_database_failures"] == 1
    assert metrics["velora_disk_free_bytes"] == 400


def test_prometheus_export_is_valid_text_shape():
    rendered = prometheus_text(collect_metrics(None, snapshot=_snapshot()))
    assert "# TYPE velora_platform_up gauge" in rendered
    assert "velora_platform_up 1" in rendered
    assert "velora_sites_total 3" in rendered
    assert rendered.endswith("\n")


def test_metrics_names_are_sanitized():
    rendered = prometheus_text({"bad metric/name": 1.5})
    assert "bad_metric_name 1.5" in rendered
