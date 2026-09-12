#[path = "http.rs"]
mod http;

use rand::rngs::OsRng;
use rand::RngCore;
use serde::Serialize;
use std::fs;
use std::io::{self, BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Condvar, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager};

#[derive(Clone, Serialize)]
pub struct Bootstrap {
    pub url: String,
    pub token: String,
}

struct Inner {
    endpoint: Option<Bootstrap>,
    error: Option<String>,
    backend_pid: Option<u32>,
    generation: u32,
    frontend_ready: bool,
    bot_status: Option<String>,
    mainnet_allowed: Option<bool>,
    finished: bool,
}

pub struct BackendState {
    inner: Mutex<Inner>,
    changed: Condvar,
    shutdown: AtomicBool,
    data_dir: PathBuf,
}

impl BackendState {
    pub fn new(data_dir: PathBuf) -> Self {
        Self {
            inner: Mutex::new(Inner {
                endpoint: None,
                error: None,
                backend_pid: None,
                generation: 0,
                frontend_ready: false,
                bot_status: None,
                mainnet_allowed: None,
                finished: false,
            }),
            changed: Condvar::new(),
            shutdown: AtomicBool::new(false),
            data_dir,
        }
    }

    pub fn wait_ready(&self, timeout: Duration) -> Result<Bootstrap, String> {
        let deadline = Instant::now() + timeout;
        let mut state = self.inner.lock().map_err(|_| "Desktop state lock failed")?;
        loop {
            if self.shutdown.load(Ordering::Acquire) {
                return Err("Application is shutting down".to_string());
            }
            if let Some(endpoint) = &state.endpoint {
                return Ok(endpoint.clone());
            }
            if let Some(error) = &state.error {
                return Err(error.clone());
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err("Backend startup timed out".to_string());
            }
            state = self
                .changed
                .wait_timeout(state, remaining)
                .map_err(|_| "Desktop state wait failed")?
                .0;
        }
    }

    pub fn confirm_frontend(&self) -> Result<(), String> {
        let endpoint = self.wait_ready(Duration::from_secs(1))?;
        http::health(&endpoint.url, &endpoint.token)?;
        let response = http::request(&endpoint.url, &endpoint.token, "GET", "/api/state")?;
        let backend: serde_json::Value = serde_json::from_slice(&response)
            .map_err(|_| "Backend state response is invalid".to_string())?;
        let mut state = self.inner.lock().map_err(|_| "Desktop state lock failed")?;
        if state.endpoint.as_ref().map(|current| &current.token) != Some(&endpoint.token) {
            return Err("Backend restarted during frontend initialization".to_string());
        }
        state.frontend_ready = true;
        state.bot_status = backend.get("status").and_then(|value| value.as_str()).map(str::to_string);
        state.mainnet_allowed = backend.get("mainnet_allowed").and_then(|value| value.as_bool());
        self.write_marker(&state);
        Ok(())
    }

    pub fn is_finished(&self) -> bool {
        self.inner.lock().map(|state| state.finished).unwrap_or(false)
    }

    fn update(&self, endpoint: Option<Bootstrap>, error: Option<String>, pid: Option<u32>, generation: u32) {
        if let Ok(mut state) = self.inner.lock() {
            state.endpoint = endpoint;
            state.error = error;
            state.backend_pid = pid;
            state.generation = generation;
            state.frontend_ready = false;
            state.bot_status = None;
            state.mainnet_allowed = None;
            self.write_marker(&state);
            self.changed.notify_all();
        } else {
            self.shutdown.store(true, Ordering::Release);
            eprintln!("event=desktop_state_failure");
        }
    }

    fn finish(&self) {
        if let Ok(mut state) = self.inner.lock() {
            state.endpoint = None;
            state.backend_pid = None;
            state.frontend_ready = false;
            state.finished = true;
            self.write_marker(&state);
            self.changed.notify_all();
        }
    }

    fn write_marker(&self, state: &Inner) {
        let value = serde_json::json!({
            "url": state.endpoint.as_ref().map(|endpoint| &endpoint.url),
            "app_pid": std::process::id(),
            "backend_pid": state.backend_pid,
            "ready": state.endpoint.is_some(),
            "frontend_ready": state.frontend_ready,
            "bot_status": state.bot_status,
            "mainnet_allowed": state.mainnet_allowed,
            "generation": state.generation,
            "error": state.error,
            "finished": state.finished,
        });
        let result = (|| -> io::Result<()> {
            let temporary = self.data_dir.join("desktop-status.json.tmp");
            fs::write(&temporary, serde_json::to_vec(&value)?)?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600))?;
            }
            fs::rename(temporary, self.data_dir.join("desktop-status.json"))
        })();
        if result.is_err() {
            eprintln!("event=desktop_status_write_failed");
        }
    }
}

pub fn data_directory(app: &AppHandle) -> io::Result<PathBuf> {
    let path = if let Some(override_path) = std::env::var_os("GRIDBOT_DATA_DIR") {
        let path = PathBuf::from(override_path);
        if !path.is_absolute() {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "Data directory must be absolute"));
        }
        path
    } else {
        app.path()
            .data_dir()
            .map_err(|error| io::Error::other(error.to_string()))?
            .join("Grid Hedge Bot")
    };
    fs::create_dir_all(&path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&path, fs::Permissions::from_mode(0o700))?;
    }
    Ok(path)
}

fn sidecar_path() -> io::Result<PathBuf> {
    let executable = std::env::current_exe()?;
    let bundled = executable
        .parent()
        .ok_or_else(|| io::Error::other("Application executable has no directory"))?
        .join("gridbot-backend");
    if bundled.is_file() {
        return Ok(bundled);
    }
    #[cfg(debug_assertions)]
    {
        let development = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("binaries")
            .join(format!("gridbot-backend-{}", env!("GRIDBOT_TARGET")));
        if development.is_file() {
            return Ok(development);
        }
    }
    Err(io::Error::new(io::ErrorKind::NotFound, "Embedded backend executable is missing"))
}

fn random_token() -> String {
    let mut bytes = [0u8; 32];
    OsRng.fill_bytes(&mut bytes);
    bytes.iter().map(|value| format!("{value:02x}")).collect()
}

fn ready_url(line: &str) -> Option<String> {
    let value: serde_json::Value = serde_json::from_str(line).ok()?;
    if value.get("type")?.as_str()? != "ready" {
        return None;
    }
    let url = value.get("url")?.as_str()?;
    let port = http::port_from_url(url).ok()?;
    if value.get("port")?.as_u64()? != u64::from(port) {
        return None;
    }
    Some(url.to_string())
}

fn spawn_backend(path: &Path, state: &BackendState, token: &str) -> io::Result<(Child, mpsc::Receiver<String>)> {
    let allow_mainnet = std::env::var("ALLOW_MAINNET_TRADING").as_deref() == Ok("true");
    let mut command = Command::new(path);
    command
        .args(["--port", "0", "--data-dir"])
        .arg(&state.data_dir)
        .env("GRID_API_TOKEN", token)
        .env("GRIDBOT_PARENT_PID", std::process::id().to_string())
        .env("GRIDBOT_PARENT_STDIN", "true")
        .env("ALLOW_MAINNET_TRADING", if allow_mainnet { "true" } else { "false" })
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONHOME")
        .current_dir(&state.data_dir)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    let mut child = command.spawn()?;
    let stdout = child.stdout.take().ok_or_else(|| io::Error::other("Backend stdout unavailable"))?;
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines() {
            match line {
                Ok(line) => {
                    if let Some(url) = ready_url(&line) {
                        let _ = sender.send(url);
                    }
                }
                Err(_) => break,
            }
        }
    });
    Ok((child, receiver))
}

fn stop_backend(child: &mut Child, endpoint: Option<&Bootstrap>) {
    if let Some(endpoint) = endpoint {
        if http::request(&endpoint.url, &endpoint.token, "POST", "/api/pause").is_err() {
            eprintln!("event=desktop_pause_request_failed");
        }
        if http::request(&endpoint.url, &endpoint.token, "POST", "/api/shutdown").is_err() {
            eprintln!("event=desktop_shutdown_request_failed");
        }
    }
    // EOF is a parent-liveness signal, including through PyInstaller's bootloader.
    // Closing here also unblocks Python's stdin executor thread before shutdown.
    drop(child.stdin.take());
    if wait_for_exit(child, Duration::from_secs(10)) && !process_group_alive(child.id()) {
        return;
    }
    terminate_process_group(child, false);
    if wait_for_exit(child, Duration::from_secs(3)) && !process_group_alive(child.id()) {
        return;
    }
    terminate_process_group(child, true);
    if child.wait().is_err() {
        eprintln!("event=desktop_backend_wait_failed");
    }
}

fn process_group_alive(pid: u32) -> bool {
    #[cfg(unix)]
    unsafe {
        libc::kill(-(pid as i32), 0) == 0
    }
    #[cfg(not(unix))]
    {
        let _ = pid;
        false
    }
}

fn terminate_process_group(child: &mut Child, force: bool) {
    #[cfg(unix)]
    unsafe {
        let signal = if force { libc::SIGKILL } else { libc::SIGTERM };
        if libc::kill(-(child.id() as i32), signal) != 0 && process_group_alive(child.id()) {
            eprintln!("event=desktop_backend_signal_failed");
        }
    }
    #[cfg(not(unix))]
    {
        let _ = force;
        if child.kill().is_err() {
            eprintln!("event=desktop_backend_kill_failed");
        }
    }
}

fn wait_for_exit(child: &mut Child, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        match child.try_wait() {
            Ok(Some(_)) => return true,
            Ok(None) => thread::sleep(Duration::from_millis(100)),
            Err(_) => return false,
        }
    }
    false
}

pub fn start(app: AppHandle, state: Arc<BackendState>) {
    thread::spawn(move || {
        let result = supervise(&app, &state);
        if let Err(error) = result {
            state.update(None, Some(error.clone()), None, 0);
            let _ = app.emit("backend-unavailable", error);
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
            }
        }
        state.finish();
    });
}

fn supervise(app: &AppHandle, state: &Arc<BackendState>) -> Result<(), String> {
    let path = sidecar_path().map_err(|_| "Embedded backend executable is missing".to_string())?;
    for attempt in 0..4u32 {
        if state.shutdown.load(Ordering::Acquire) {
            return Ok(());
        }
        state.update(None, None, None, attempt + 1);
        let token = random_token();
        let (mut child, receiver) = spawn_backend(&path, state, &token)
            .map_err(|_| "Embedded backend could not start".to_string())?;
        let deadline = Instant::now() + Duration::from_secs(45);
        let mut endpoint = None;
        let mut candidate = None;
        while Instant::now() < deadline && !state.shutdown.load(Ordering::Acquire) {
            if let Ok(url) = receiver.recv_timeout(Duration::from_millis(100)) {
                candidate = Some(url);
            }
            if let Some(url) = &candidate {
                if http::health(url, &token).is_ok() {
                    endpoint = Some(Bootstrap { url: url.clone(), token: token.clone() });
                    break;
                }
            }
            if !matches!(child.try_wait(), Ok(None)) {
                break;
            }
        }
        if state.shutdown.load(Ordering::Acquire) {
            stop_backend(&mut child, endpoint.as_ref());
            return Ok(());
        }
        if endpoint.is_none() {
            stop_backend(&mut child, None);
        } else {
            state.update(endpoint.clone(), None, Some(child.id()), attempt + 1);
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
            }
            if attempt > 0 {
                let _ = app.emit("backend-restarted", attempt + 1);
            }
            loop {
                let qa_close = state.data_dir.join("qa-request-close");
                if std::env::var("GRIDBOT_DESKTOP_QA").as_deref() == Ok("1") && qa_close.is_file() {
                    let _ = fs::remove_file(qa_close);
                    if let Some(window) = app.get_webview_window("main") {
                        let _ = window.close();
                    }
                }
                if state.shutdown.load(Ordering::Acquire) {
                    stop_backend(&mut child, endpoint.as_ref());
                    return Ok(());
                }
                match child.try_wait() {
                    Ok(None) => thread::sleep(Duration::from_millis(200)),
                    Ok(Some(_)) => {
                        stop_backend(&mut child, endpoint.as_ref());
                        break;
                    }
                    Err(_) => {
                        stop_backend(&mut child, endpoint.as_ref());
                        break;
                    }
                }
            }
        }
        state.update(None, None, None, attempt + 1);
        let _ = app.emit("backend-unavailable", "Backend stopped; reconnect and reconcile before trading");
        let retry_deadline = Instant::now() + Duration::from_secs(1 << attempt);
        while Instant::now() < retry_deadline && !state.shutdown.load(Ordering::Acquire) {
            thread::sleep(Duration::from_millis(100));
        }
    }
    Err("Backend could not remain healthy after three restarts; trading is paused".to_string())
}

pub fn request_shutdown(app: AppHandle, state: Arc<BackendState>) {
    if state.shutdown.swap(true, Ordering::AcqRel) {
        return;
    }
    state.changed.notify_all();
    thread::spawn(move || {
        let deadline = Instant::now() + Duration::from_secs(25);
        while !state.is_finished() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(100));
        }
        if state.is_finished() {
            app.exit(0);
        } else {
            let _ = app.emit("backend-unavailable", "Safe shutdown did not complete; application remains open");
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn session_tokens_are_random_header_safe_and_256_bit() {
        let first = random_token();
        let second = random_token();
        assert_eq!(first.len(), 64);
        assert!(first.bytes().all(|value| value.is_ascii_hexdigit()));
        assert_ne!(first, second);
    }

    #[test]
    fn readiness_requires_matching_port_and_loopback() {
        assert_eq!(ready_url(r#"{"type":"ready","url":"http://127.0.0.1:23000","port":23000}"#), Some("http://127.0.0.1:23000".to_string()));
        assert!(ready_url(r#"{"type":"ready","url":"http://127.0.0.1:23000","port":23001}"#).is_none());
        assert!(ready_url(r#"{"type":"ready","url":"http://0.0.0.0:23000","port":23000}"#).is_none());
        assert!(ready_url(r#"{"type":"event","url":"http://127.0.0.1:23000","port":23000}"#).is_none());
    }

    #[test]
    fn never_returns_bootstrap_before_readiness() {
        let state = BackendState::new(std::env::temp_dir());
        assert!(state.wait_ready(Duration::from_millis(1)).is_err());
    }

    #[test]
    fn shutdown_invalidates_bootstrap() {
        let state = BackendState::new(std::env::temp_dir());
        state.shutdown.store(true, Ordering::Release);
        assert!(state.wait_ready(Duration::from_millis(1)).is_err());
    }
}
