"""Reproducible local quality gates with raw logs and explicit exit results."""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scope", choices=("backend", "frontend"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    reports = root / "build" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    if args.scope == "backend":
        commands = [
            ("python-dependencies", [sys.executable, "-m", "pip", "check"]),
            (
                "python-lint",
                [
                    sys.executable,
                    "-m",
                    "ruff",
                    "check",
                    "backend",
                    "tests",
                    "scripts",
                    "desktop/tests",
                ],
            ),
            (
                "python-format",
                [
                    sys.executable,
                    "-m",
                    "ruff",
                    "format",
                    "--check",
                    "backend",
                    "tests",
                    "scripts",
                    "desktop/tests",
                ],
            ),
            ("python-compile", [sys.executable, "-m", "compileall", "-q", "backend", "scripts"]),
            ("desktop-schema", [sys.executable, "scripts/validate_desktop_config.py"]),
            (
                "backend-tests",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests",
                    "desktop/tests",
                    "-q",
                    "--junitxml=build/reports/backend-tests.xml",
                    "--cov=gridbot",
                    "--cov-branch",
                    "--cov-report=json:build/reports/backend-coverage.json",
                    "--cov-report=term",
                ],
            ),
        ]
    else:
        # This fixed generated output is deliberately removed before the fresh build.
        shutil.rmtree(root / "frontend" / "dist", ignore_errors=True)
        commands = [
            ("frontend-install", ["npm", "--prefix", "frontend", "ci"]),
            ("frontend-lint", ["npm", "--prefix", "frontend", "run", "lint"]),
            ("frontend-format", ["npm", "--prefix", "frontend", "run", "format:check"]),
            (
                "frontend-tests",
                [
                    "npm",
                    "--prefix",
                    "frontend",
                    "test",
                    "--",
                    "--reporter=json",
                    "--outputFile=../build/reports/frontend-tests.json",
                ],
            ),
            ("frontend-build", ["npm", "--prefix", "frontend", "run", "build"]),
            (
                "frontend-e2e-types",
                [
                    "node",
                    str(root / "frontend" / "node_modules" / "typescript" / "bin" / "tsc"),
                    "--noEmit",
                    "-p",
                    str(root / "frontend" / "e2e" / "tsconfig.json"),
                ],
            ),
            (
                "frontend-local-e2e",
                [sys.executable, str(root / "scripts" / "run_frontend_backend_e2e.py")],
            ),
            ("frontend-dependency-audit", ["npm", "--prefix", "frontend", "audit", "--json"]),
            ("desktop-dependency-audit", ["npm", "--prefix", "desktop", "audit", "--json"]),
        ]
    results = []
    for name, command in commands:
        started = time.monotonic()
        log_path = reports / f"{name}.log"
        print(f"START {name}", flush=True)
        with log_path.open("w") as output:
            process = subprocess.run(command, cwd=root, stdout=output, stderr=subprocess.STDOUT)
        result = {
            "check": name,
            "result": "PASS" if process.returncode == 0 else "FAIL",
            "exit_code": process.returncode,
            "seconds": round(time.monotonic() - started, 2),
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "log": str(log_path.relative_to(root)),
        }
        results.append(result)
        (reports / f"{args.scope}-quality.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(result), flush=True)
        if process.returncode:
            print(log_path.read_text()[-5000:], flush=True)
            raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
