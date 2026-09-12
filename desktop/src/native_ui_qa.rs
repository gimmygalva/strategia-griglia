//! Installed-WKWebView smoke checks, available only in the explicit CI QA mode.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;
use tauri::Manager;

#[derive(Deserialize, Serialize)]
pub struct Check {
    name: String,
    passed: bool,
}

#[derive(Deserialize, Serialize)]
pub struct Report {
    result: String,
    checks: Vec<Check>,
    failure: Option<String>,
}

pub fn enabled() -> bool {
    std::env::var("GRIDBOT_DESKTOP_QA").as_deref() == Ok("1")
}

pub fn record(directory: &Path, report: Report) -> Result<(), String> {
    if !enabled() {
        return Err("Native UI QA is disabled".to_string());
    }
    if !matches!(report.result.as_str(), "PASS" | "FAIL")
        || report.checks.len() > 16
        || report.checks.iter().any(|check| check.name.len() > 160)
        || report.failure.as_ref().is_some_and(|error| error.len() > 256)
    {
        return Err("Invalid native UI QA report".to_string());
    }
    let bytes = serde_json::to_vec_pretty(&report)
        .map_err(|_| "Cannot encode native UI QA report".to_string())?;
    let temporary = directory.join("qa-native-ui-result.tmp");
    fs::write(&temporary, bytes).map_err(|_| "Cannot persist native UI QA report".to_string())?;
    fs::rename(&temporary, directory.join("qa-native-ui-result.json"))
        .map_err(|_| "Cannot commit native UI QA report".to_string())
}

pub fn poll(app: &tauri::AppHandle, directory: &Path) -> Result<(), String> {
    if !enabled() {
        return Ok(());
    }
    let request = directory.join("qa-native-ui-request");
    if !request.is_file() {
        return Ok(());
    }
    fs::remove_file(request).map_err(|_| "Cannot consume native UI QA request".to_string())?;
    app.get_webview_window("main")
        .ok_or_else(|| "Native QA window is missing".to_string())?
        .eval(include_str!("native_ui_qa.js"))
        .map_err(|_| "Cannot run installed native UI checks".to_string())
}
