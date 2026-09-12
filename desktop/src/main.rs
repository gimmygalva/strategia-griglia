#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod supervisor;

use std::sync::Arc;
use std::time::Duration;
use supervisor::{BackendState, Bootstrap};
use tauri::{Manager, RunEvent, State, WindowEvent};

#[tauri::command]
async fn bootstrap(state: State<'_, Arc<BackendState>>) -> Result<Bootstrap, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || state.wait_ready(Duration::from_secs(50)))
        .await
        .map_err(|_| "Backend startup worker failed".to_string())?
}

#[tauri::command]
async fn frontend_ready(state: State<'_, Arc<BackendState>>) -> Result<(), String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || state.confirm_frontend())
        .await
        .map_err(|_| "Frontend readiness worker failed".to_string())?
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .setup(|app| {
            let data_dir = supervisor::data_directory(app.handle())?;
            let state = Arc::new(BackendState::new(data_dir));
            app.manage(state.clone());
            supervisor::start(app.handle().clone(), state);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![bootstrap, frontend_ready])
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let state = window.state::<Arc<BackendState>>();
                if !state.is_finished() {
                    api.prevent_close();
                    supervisor::request_shutdown(window.app_handle().clone(), state.inner().clone());
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("Grid Hedge Bot desktop startup failed");

    app.run(|app, event| {
        if let RunEvent::ExitRequested { api, .. } = event {
            let state = app.state::<Arc<BackendState>>();
            if !state.is_finished() {
                api.prevent_exit();
                supervisor::request_shutdown(app.clone(), state.inner().clone());
            }
        }
    });
}
