"""Regression tests for the documented Python module entry point."""
import subprocess
import sys
from pathlib import Path


def test_python_m_velora_invokes_cli_help():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-m", "velora", "--help"], cwd=root, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "maintenance" in result.stdout
