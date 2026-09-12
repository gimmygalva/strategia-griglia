#!/usr/bin/env python3
"""Write a local candidate manifest only when actual build evidence passes."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def junit_summary(path: Path) -> dict[str, int]:
    document = ET.parse(path).getroot()
    suites = [document] if document.tag == "testsuite" else list(document.iter("testsuite"))
    result = {
        key: sum(int(suite.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    if not result["tests"] or result["failures"] or result["errors"]:
        raise RuntimeError(f"Backend release gate has no tests or failed tests: {path.name}")
    # The Linux-only fake-DMG refusal runs in Linux CI. It is the sole
    # non-applicable check on native Mac builds; any other skip blocks packaging.
    skipped = [case for case in document.iter("testcase") if case.find("skipped") is not None]
    if len(skipped) != result["skipped"] or any(
        case.get("name") != "test_linux_build_explicitly_refuses_to_make_a_fake_dmg"
        or "Linux build refusal" not in case.find("skipped").get("message", "")
        for case in skipped
    ):
        raise RuntimeError(f"Backend release gate has unexpected skipped tests: {path.name}")
    return result


def frontend_summary(path: Path) -> dict[str, int]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if (
        report.get("success") is not True
        or report.get("numFailedTests")
        or report.get("numPendingTests")
        or not report.get("numPassedTests")
    ):
        raise RuntimeError(f"Frontend release gate did not pass: {path.name}")
    return {
        key: report.get(key, 0) for key in ("numPassedTests", "numFailedTests", "numPendingTests")
    }


def evidence(root: Path) -> dict[str, Any]:
    directory = root / "build" / "reports"
    result: dict[str, Any] = {
        "backend": junit_summary(directory / "final-backend-tests.xml"),
        "frontend": frontend_summary(directory / "final-frontend-tests.json"),
    }
    for name in ("frozen-backend", "macos-package", "frontend-backend-e2e"):
        report = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
        if report.get("result") != "PASS" or not report.get("checks"):
            raise RuntimeError(f"Missing successful real {name} verification")
        result[name] = report
    return result


def main() -> None:
    if platform.system() != "Darwin":
        raise SystemExit("No macOS candidate manifest can be produced outside macOS")
    root = Path(__file__).resolve().parents[1]
    reports = evidence(root)
    dmg = root / "dist" / "Grid Hedge Bot.dmg"
    app = root / "dist" / "Grid Hedge Bot.app"
    if not dmg.is_file() or not app.is_dir():
        raise SystemExit("Real generated application and DMG are required")
    with dmg.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    version = json.loads((root / "desktop" / "package.json").read_text(encoding="utf-8"))["version"]
    manifest = {
        "version": version,
        "build": f"{timestamp}-{digest[:12]}",
        "classification": "LOCAL_CANDIDATE_REQUIRES_BYBIT_DEMO_ACCEPTANCE",
        "dmg_sha256": digest,
        "architecture": platform.machine(),
        "tests": reports,
        "external_tests_not_verified": [
            "Official Bybit Demo account/order acceptance not yet verified; remote REST/private WebSocket preflight blocked by HTTP 403",
            "Developer ID certificate and Apple notarization unless separately configured and verified",
            "Clean end-user Gatekeeper installation after browser download with quarantine",
        ],
        "mainnet_trading_during_build": False,
    }
    shutil.copytree(root / "build" / "reports", root / "dist" / "reports", dirs_exist_ok=True)
    (root / "dist" / "BUILD_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
