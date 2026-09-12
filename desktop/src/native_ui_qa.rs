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

fn evaluation(directory: &Path, serialized: &str) -> Result<(), String> {
    let report: Report = serde_json::from_str(serialized)
        .map_err(|_| "Native UI evaluation returned invalid JSON".to_string())?;
    if !matches!(report.result.as_str(), "WAIT" | "RUNNING" | "PASS" | "FAIL") {
        return Err("Native UI evaluation returned an invalid status".to_string());
    }
    if report.checks.len() > 16
        || report.checks.iter().any(|check| check.name.len() > 160)
        || report.failure.as_ref().is_some_and(|error| error.len() > 256)
    {
        return Err("Native UI evaluation exceeded report limits".to_string());
    }
    let bytes = serde_json::to_vec_pretty(&report)
        .map_err(|_| "Cannot encode native UI progress".to_string())?;
    fs::write(directory.join("qa-native-ui-progress.json"), bytes)
        .map_err(|_| "Cannot persist native UI progress".to_string())?;
    if matches!(report.result.as_str(), "PASS" | "FAIL") {
        record(directory, report)?;
        fs::remove_file(directory.join("qa-native-ui-active"))
            .map_err(|_| "Cannot complete native UI evaluation".to_string())?;
    }
    Ok(())
}

pub fn poll(app: &tauri::AppHandle, directory: &Path) -> Result<(), String> {
    if !enabled() {
        return Ok(());
    }
    let request = directory.join("qa-native-ui-request");
    let active = directory.join("qa-native-ui-active");
    if !request.is_file() && !active.is_file() {
        return Ok(());
    }
    let script = if request.is_file() {
        fs::remove_file(request).map_err(|_| "Cannot consume native UI QA request".to_string())?;
        fs::write(&active, "requested").map_err(|_| "Cannot persist native UI request".to_string())?;
        include_str!("native_ui_qa.js")
    } else {
        "window.__GRIDBOT_NATIVE_QA__ || {result: 'WAIT', checks: [], failure: null}"
    };
    let directory = directory.to_path_buf();
    app.get_webview_window("main")
        .ok_or_else(|| "Native QA window is missing".to_string())?
        .eval_with_callback(script, move |serialized| {
            if let Err(error) = evaluation(&directory, &serialized) {
                eprintln!("event=native_ui_qa_failed error={error}");
            }
        })
        .map_err(|_| "Cannot evaluate installed native UI checks".to_string())
}
