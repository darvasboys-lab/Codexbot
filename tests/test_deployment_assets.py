from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_auditbot_inspection_refuses_wrong_project_before_host_inspection(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text("#!/bin/sh\necho production-project\n", encoding="utf-8")
    fake_curl.chmod(0o700)
    environment = {"PATH": f"{fake_bin}:{os.environ['PATH']}"}

    result = subprocess.run(
        ["sh", str(ROOT / "deploy" / "inspect-auditbot.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 20
    assert result.stdout == ""
    assert result.stderr == "REFUSED: unexpected project: production-project\n"


def test_deployment_shell_scripts_are_executable_and_parseable() -> None:
    for name in ("inspect-auditbot.sh", "codexbot-healthcheck.sh"):
        path = ROOT / "deploy" / name
        assert path.stat().st_mode & 0o111
        subprocess.run(["sh", "-n", str(path)], check=True)

