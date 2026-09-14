fn main() {
    let target = std::env::var("TARGET").expect("Cargo target must be set");
    println!("cargo:rustc-env=GRIDBOT_TARGET={target}");
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&["bootstrap", "frontend_ready"]),
        ),
    )
    .expect("Tauri build configuration must be valid");
}
