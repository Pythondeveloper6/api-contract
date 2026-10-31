"""The example project runs end to end."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "orders-contract"


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_example_runs(monkeypatch):
    bin_dir = Path(sys.executable).parent
    monkeypatch.setenv("PATH", f"{bin_dir}:{__import__('os').environ['PATH']}")
    result = subprocess.run(
        ["bash", str(EXAMPLE / "run.sh")], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "example OK" in result.stdout
