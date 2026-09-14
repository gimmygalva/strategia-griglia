fn main() {
    let target = std::env::var("TARGET").expect("Cargo target must be set");
    println!("cargo:rustc-env=GRIDBOT_TARGET={target}");
    let sidecar = std::path::Path::new(&std::env::var("CARGO_MANIFEST_DIR").expect("Cargo manifest directory must be set"))
        .join("binaries")
        .join(format!("gridbot-backend-{target}"));
    println!("cargo:rerun-if-changed={}", sidecar.display());
    let digest = std::process::Command::new("/usr/bin/shasum")
        .args(["-a", "256"])
        .arg(&sidecar)
        .output()
        .expect("Native backend sidecar digest command must run");
    assert!(digest.status.success(), "Native backend sidecar digest must succeed");
    let digest = String::from_utf8(digest.stdout).expect("Native backend digest must be UTF-8");
    let digest = digest.split_whitespace().next().expect("Native backend digest must exist");
    assert_eq!(digest.len(), 64, "Native backend digest must be SHA-256");
    println!("cargo:rustc-env=GRIDBOT_SIDECAR_SHA256={digest}");
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&["bootstrap", "frontend_ready"]),
        ),
    )
    .expect("Tauri build configuration must be valid");
}
