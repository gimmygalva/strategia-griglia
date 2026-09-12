"""Record Cargo's real filtered native graph; never suppress lockfile advisories."""

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata", type=Path)
    parser.add_argument(
        "--target", choices=("aarch64-apple-darwin", "x86_64-apple-darwin"), required=True
    )
    args = parser.parse_args()
    metadata = json.loads(args.metadata.read_text())
    resolve = metadata["resolve"]
    packages = {package["id"]: package for package in metadata["packages"]}
    nodes = {node["id"]: node for node in resolve["nodes"]}
    reached: set[str] = set()
    pending = [resolve["root"]]
    while pending:
        identifier = pending.pop()
        if identifier in reached:
            continue
        reached.add(identifier)
        pending.extend(nodes[identifier]["dependencies"])
    native = sorted(
        (
            {"name": packages[item]["name"], "version": packages[item]["version"]}
            for item in reached
        ),
        key=lambda package: (package["name"], package["version"]),
    )
    # RUSTSEC-2024-0429 concerns Tauri's unsupported Linux/GTK dependency.
    # Prove absence from the actual Mac graph, including build dependencies.
    if any(package["name"] == "glib" for package in native):
        raise RuntimeError("Unexpected GLib dependency in the filtered native macOS build graph")
    report = {
        "result": "PASS",
        "target": args.target,
        "method": "cargo metadata --locked --features custom-protocol --filter-platform; resolved root reachability",
        "glib_in_native_graph": False,
        "packages": native,
        "limitations": [
            "This graph proves platform scope only; full-lockfile cargo-audit still runs without ignored advisories",
            "Informational unmaintained-package warnings remain documented; Linux desktop is not shipped",
        ],
    }
    output = args.metadata.parent / "rust-native-audit-scope.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {"result": "PASS", "target": args.target, "native_packages": len(native), "glib": False}
        )
    )


if __name__ == "__main__":
    main()
