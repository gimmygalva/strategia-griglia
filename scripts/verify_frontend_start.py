"""Start Vite and fetch real modules; this does not claim browser-rendering QA."""

import json
import os
import signal
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    checks = []
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", "5173", "--strictPort"],
            cwd=root / "frontend",
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    with urllib.request.urlopen("http://127.0.0.1:5173/", timeout=2) as response:
                        html = response.read()
                    assert b'id="root"' in html
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError(
                            "The actual Vite frontend failed to become ready"
                        ) from None
                    time.sleep(0.1)
            for path in ("/", "/src/main.tsx"):
                with urllib.request.urlopen("http://127.0.0.1:5173" + path, timeout=3) as response:
                    payload = response.read()
                    assert response.status == 200 and payload
                    checks.append({"route": path, "status": response.status, "bytes": len(payload)})
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
    evidence = {
        "result": "PASS",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checks": checks,
        "manual_browser_rendering": "NON VERIFICATO",
    }
    report = root / "build" / "reports" / "frontend-start.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
