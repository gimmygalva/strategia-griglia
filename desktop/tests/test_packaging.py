from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from scripts.build_backend import build_command, native_target
from scripts.validate_desktop_config import validate
from scripts.write_build_manifest import frontend_summary, junit_summary

ROOT = Path(__file__).resolve().parents[2]


def test_native_macos_only_no_disguised_linux_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="native macOS"):
        native_target()


@pytest.mark.parametrize(
    "machine,target", [("arm64", "aarch64-apple-darwin"), ("x86_64", "x86_64-apple-darwin")]
)
def test_architecture_is_explicit(
    monkeypatch: pytest.MonkeyPatch, machine: str, target: str
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: machine)
    assert native_target() == target


def test_frozen_command_bundles_real_runtime_static_assets_and_migrations() -> None:
    command = build_command(ROOT, "x86_64-apple-darwin", "-")
    assert "--onefile" in command
    assert "PyInstaller" in command
    assert command[-1] == str(ROOT / "backend" / "entrypoint.py")
    assert f"{ROOT / 'frontend' / 'dist'}:frontend/dist" in command
    assert any(value.endswith(":gridbot/migrations") for value in command)
    assert "--codesign-identity" in command
    assert "aiosqlite" in command
    assert "greenlet" in command
    assert not any("testnet" in value.lower() for value in command)


def test_unsupported_freeze_target_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_command(ROOT, "x86_64-unknown-linux-gnu")


def test_icon_has_real_icns_container_and_expected_png_dimensions() -> None:
    icns = ROOT / "desktop" / "icons" / "icon.icns"
    assert icns.read_bytes()[:4] == b"icns"
    with Image.open(icns) as source:
        source.load()
        assert source.size == (1024, 1024)
    with Image.open(ROOT / "desktop" / "icons" / "icon.png") as source:
        assert source.size == (1024, 1024)
        assert source.mode == "RGBA"


def test_native_config_does_not_allow_remote_commands_or_shell_execution() -> None:
    config = json.loads((ROOT / "desktop" / "tauri.conf.json").read_text())
    capability = json.loads((ROOT / "desktop" / "capabilities" / "main.json").read_text())
    assert config["app"]["windows"][0]["visible"] is False
    assert "remote" not in capability
    assert not any("shell:" in permission for permission in capability["permissions"])
    assert config["bundle"]["macOS"]["hardenedRuntime"] is True
    assert config["bundle"]["externalBin"] == ["binaries/gridbot-backend"]
    assert "http://127.0.0.1:*" in config["app"]["security"]["csp"]


def test_desktop_config_matches_the_actual_pinned_official_schema() -> None:
    validate(ROOT)


def test_failed_backend_evidence_cannot_be_promoted(tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    report.write_text('<testsuite tests="4" failures="1" errors="0" skipped="0"/>')
    with pytest.raises(RuntimeError, match="failed tests"):
        junit_summary(report)
    report.write_text('<testsuite tests="4" failures="0" errors="0" skipped="1"/>')
    with pytest.raises(RuntimeError, match="unexpected skipped"):
        junit_summary(report)
    report.write_text(
        '<testsuite tests="4" failures="0" errors="0" skipped="1">'
        '<testcase name="test_linux_build_explicitly_refuses_to_make_a_fake_dmg">'
        '<skipped message="This check specifically verifies the Linux build refusal"/>'
        "</testcase></testsuite>"
    )
    assert junit_summary(report)["tests"] == 4


def test_failed_frontend_evidence_cannot_be_promoted(tmp_path: Path) -> None:
    report = tmp_path / "frontend.json"
    report.write_text(json.dumps({"success": False, "numPassedTests": 8, "numFailedTests": 1}))
    with pytest.raises(RuntimeError, match="did not pass"):
        frontend_summary(report)
    report.write_text(
        json.dumps(
            {"success": True, "numPassedTests": 8, "numFailedTests": 0, "numPendingTests": 1}
        )
    )
    with pytest.raises(RuntimeError, match="did not pass"):
        frontend_summary(report)


@pytest.mark.skipif(
    platform.system() == "Darwin", reason="This check specifically verifies the Linux build refusal"
)
def test_linux_build_explicitly_refuses_to_make_a_fake_dmg(tmp_path: Path) -> None:
    result = subprocess.run(
        ["/bin/bash", str(ROOT / "scripts" / "build-macos.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "NON VERIFICATO" in result.stderr
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_macos_package.py"),
            str(tmp_path / "missing.dmg"),
            "--report",
            str(tmp_path / "report.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert not (tmp_path / "report.json").exists()
