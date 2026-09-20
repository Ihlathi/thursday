use std::process::{Child, Command};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{Emitter, Manager, State};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[derive(Clone, Serialize)]
struct SummonOrigin {
    x: f64,
    y: f64,
}

/// Physical pixel origin of the overlay window plus its scale factor, so the
/// overlay can translate Core's screen coordinates into CSS pixels.
#[derive(Clone, Serialize)]
struct OverlayMetrics {
    origin_x: f64,
    origin_y: f64,
    scale: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
struct Settings {
    /// Provider credentials. Stored locally only; never sent over the UI socket.
    gemini_api_key: String,
    gemini_model: String,
    elevenlabs_api_key: String,
    elevenlabs_voice_id: String,
    model_mode: String,
    core_port: u16,
    /// Launcher inputs for the bundled Python Core.
    python_path: String,
    repo_path: String,
    autostart_core: bool,
    start_bridge: bool,
    /// Distinct >=32 character role tokens, generated once on first run.
    ui_token: String,
    platform_token: String,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            gemini_api_key: String::new(),
            gemini_model: "gemini-3.8-flash".into(),
            elevenlabs_api_key: String::new(),
            elevenlabs_voice_id: String::new(),
            model_mode: "mock".into(),
            core_port: 8765,
            python_path: if cfg!(windows) { "py".into() } else { "python3".into() },
            repo_path: String::new(),
            autostart_core: false,
            start_bridge: true,
            ui_token: String::new(),
            platform_token: String::new(),
        }
    }
}

fn token() -> String {
    format!("{}{}", uuid::Uuid::new_v4().simple(), uuid::Uuid::new_v4().simple())
}

#[derive(Default)]
struct CoreProcess {
    core: Mutex<Option<Child>>,
    bridge: Mutex<Option<Child>>,
}

fn settings_path(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    let dir = app.path().app_config_dir().map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir.join("settings.json"))
}

fn read_settings(app: &tauri::AppHandle) -> Settings {
    settings_path(app)
        .ok()
        .and_then(|path| std::fs::read_to_string(path).ok())
        .and_then(|text| serde_json::from_str::<Settings>(&text).ok())
        .unwrap_or_default()
}

fn write_settings(app: &tauri::AppHandle, settings: &Settings) -> Result<(), String> {
    let text = serde_json::to_string_pretty(settings).map_err(|e| e.to_string())?;
    std::fs::write(settings_path(app)?, text).map_err(|e| e.to_string())
}

/// Tokens are minted here so neither the user nor the repository ever holds them.
fn ensure_tokens(app: &tauri::AppHandle) -> Settings {
    let mut settings = read_settings(app);
    let mut changed = false;
    if settings.ui_token.len() < 32 {
        settings.ui_token = token();
        changed = true;
    }
    if settings.platform_token.len() < 32 || settings.platform_token == settings.ui_token {
        settings.platform_token = token();
        changed = true;
    }
    if settings.repo_path.is_empty() {
        // Default to the repository three levels above the bundled binary during dev.
        if let Ok(exe) = std::env::current_exe() {
            if let Some(root) = exe.ancestors().find(|p| p.join("run.py").is_file()) {
                settings.repo_path = root.to_string_lossy().into();
                changed = true;
            }
        }
    }
    if changed {
        let _ = write_settings(app, &settings);
    }
    settings
}

#[tauri::command]
fn overlay_ready(window: tauri::WebviewWindow) -> Result<OverlayMetrics, String> {
    window.show().map_err(|e| e.to_string())?;
    let position = window.outer_position().map_err(|e| e.to_string())?;
    let scale = window.scale_factor().map_err(|e| e.to_string())?;
    Ok(OverlayMetrics { origin_x: position.x.into(), origin_y: position.y.into(), scale })
}

#[tauri::command]
fn get_settings(app: tauri::AppHandle) -> Settings {
    ensure_tokens(&app)
}

#[tauri::command]
fn save_settings(app: tauri::AppHandle, settings: Settings) -> Result<(), String> {
    let mut merged = settings;
    let existing = ensure_tokens(&app);
    if merged.ui_token.len() < 32 {
        merged.ui_token = existing.ui_token;
    }
    if merged.platform_token.len() < 32 {
        merged.platform_token = existing.platform_token;
    }
    write_settings(&app, &merged)?;
    // Signal only: keys never travel to a window. The overlay owns the Core
    // socket, so it re-reads its socket config and reconnects.
    app.emit_to("main", "settings-changed", ()).map_err(|e| e.to_string())
}

/// The overlay asks for its socket parameters only; no provider keys cross IPC.
#[derive(Serialize)]
struct SocketConfig {
    url: String,
    token: String,
}

#[tauri::command]
fn socket_config(app: tauri::AppHandle) -> SocketConfig {
    let settings = ensure_tokens(&app);
    SocketConfig {
        url: format!("ws://127.0.0.1:{}/v1/ui", settings.core_port),
        token: settings.ui_token,
    }
}

fn is_running(slot: &Mutex<Option<Child>>) -> bool {
    let mut guard = slot.lock().unwrap();
    match guard.as_mut() {
        Some(child) => match child.try_wait() {
            Ok(None) => true,
            _ => {
                *guard = None;
                false
            }
        },
        None => false,
    }
}

/// PIDs listening on a loopback port. `tauri dev` restarts kill the app but not
/// the Core it spawned, so an orphan keeps the port — and the UI then talks to a
/// Core running older code with an older token.
#[cfg(windows)]
fn listeners(port: u16) -> Vec<u32> {
    let needle = format!(":{port}");
    let mut command = Command::new("netstat");
    command.args(["-ano", "-p", "TCP"]);
    command.creation_flags(CREATE_NO_WINDOW);
    let Ok(output) = command.output() else { return Vec::new() };
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter(|line| line.contains("LISTENING") && line.contains(&needle))
        .filter_map(|line| line.split_whitespace().last()?.parse::<u32>().ok())
        .filter(|pid| *pid != 0 && *pid != std::process::id())
        .collect()
}

#[cfg(not(windows))]
fn listeners(_port: u16) -> Vec<u32> {
    Vec::new()
}

/// Kill whatever is holding the Core port. Explicit, never automatic.
#[tauri::command]
fn free_port(app: tauri::AppHandle, state: State<'_, CoreProcess>) -> Result<String, String> {
    let port = ensure_tokens(&app).core_port;
    stop_slot(&state.bridge);
    stop_slot(&state.core);
    let pids = listeners(port);
    if pids.is_empty() {
        return Ok(if port_in_use(port) {
            format!("Port {port} is busy but no owning process was found.")
        } else {
            format!("Port {port} is already free.")
        });
    }
    for pid in &pids {
        #[cfg(windows)]
        {
            let mut kill = Command::new("taskkill");
            kill.args(["/F", "/PID", &pid.to_string()]);
            kill.creation_flags(CREATE_NO_WINDOW);
            let _ = kill.status();
        }
    }
    Ok(format!("Stopped {} process(es) holding port {port}.", pids.len()))
}

/// A second Core cannot bind the port, so check before spawning a doomed child.
fn port_in_use(port: u16) -> bool {
    std::net::TcpListener::bind(("127.0.0.1", port)).is_err()
}

fn stop_slot(slot: &Mutex<Option<Child>>) {
    if let Some(mut child) = slot.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

/// Spawn a repo script with the configured interpreter.
///
/// PYTHONHOME/PYTHONPATH are stripped: a stale value inherited from whatever
/// launched the desktop app makes CPython fail with "Could not find platform
/// independent libraries <prefix>" before it ever reaches run.py. Output goes to
/// a log file because a windowless child has nowhere else to print.
fn spawn_python(settings: &Settings, args: &[String], log: &str) -> Result<Child, String> {
    let root = std::path::Path::new(&settings.repo_path);
    if !root.join("run.py").is_file() {
        return Err(format!("No run.py under {}. Fix the repository path in Settings.", settings.repo_path));
    }
    let out = root.join("_agent").join("out");
    std::fs::create_dir_all(&out).map_err(|e| e.to_string())?;
    let file = std::fs::File::create(out.join(log)).map_err(|e| e.to_string())?;
    let errors = file.try_clone().map_err(|e| e.to_string())?;

    let mut command = Command::new(&settings.python_path);
    command
        .args(args)
        .current_dir(root)
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .env("PYTHONUNBUFFERED", "1")
        .env("AGENT_UI_TOKEN", &settings.ui_token)
        .env("AGENT_PLATFORM_TOKEN", &settings.platform_token)
        .env("AGENT_MODEL_MODE", &settings.model_mode)
        .env("GEMINI_API_KEY", &settings.gemini_api_key)
        .env("GEMINI_MODEL", &settings.gemini_model)
        .env("ELEVENLABS_API_KEY", &settings.elevenlabs_api_key)
        .env("ELEVENLABS_VOICE_ID", &settings.elevenlabs_voice_id)
        .stdout(std::process::Stdio::from(file))
        .stderr(std::process::Stdio::from(errors));
    // `tauri dev` serves the webview from the Vite origin, which Core's strict
    // origin list rejects. Production builds use tauri://localhost and never
    // set this.
    if tauri::is_dev() {
        command.env("AGENT_ALLOWED_ORIGIN", "http://localhost:1420");
    }
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    command
        .spawn()
        .map_err(|e| format!("Unable to run `{} {}`: {e}", settings.python_path, args.join(" ")))
}

#[tauri::command]
fn core_status(state: State<'_, CoreProcess>) -> Vec<bool> {
    vec![is_running(&state.core), is_running(&state.bridge)]
}

#[tauri::command]
fn core_start(app: tauri::AppHandle, state: State<'_, CoreProcess>) -> Result<(), String> {
    let settings = ensure_tokens(&app);
    if settings.repo_path.is_empty() {
        return Err("Set the repository path in Settings first.".into());
    }
    let port = settings.core_port.to_string();
    if !is_running(&state.core) && port_in_use(settings.core_port) {
        return Err(format!(
            "Port {port} is already taken, most likely by an orphaned Core from an earlier run. Press \"Free port\" and start again."
        ));
    }
    if !is_running(&state.core) {
        let args = vec![
            "run.py".into(),
            "serve".into(),
            "--mode".into(),
            settings.model_mode.clone(),
            "--port".into(),
            port.clone(),
        ];
        *state.core.lock().unwrap() = Some(spawn_python(&settings, &args, "core.log")?);
    }
    // The bridge is the process that actually touches the desktop; Core only
    // proxies tool calls to it over /v1/platform with the platform token.
    if settings.start_bridge && !is_running(&state.bridge) {
        let args = vec![
            "run.py".into(),
            "windows-platform".into(),
            "--url".into(),
            format!("ws://127.0.0.1:{port}/v1/platform"),
        ];
        match spawn_python(&settings, &args, "bridge.log") {
            Ok(child) => *state.bridge.lock().unwrap() = Some(child),
            Err(error) => return Err(format!("Core started; bridge did not: {error}")),
        }
    }
    Ok(())
}

#[tauri::command]
fn core_stop(state: State<'_, CoreProcess>) -> Result<(), String> {
    stop_slot(&state.bridge);
    stop_slot(&state.core);
    Ok(())
}

/// Settings panel test box -> overlay's authenticated Core socket.
#[tauri::command]
fn send_request(app: tauri::AppHandle, text: String) -> Result<(), String> {
    app.emit_to("main", "core-request", text).map_err(|e| e.to_string())
}

fn show_settings(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("settings") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(CoreProcess::default())
        .invoke_handler(tauri::generate_handler![
            overlay_ready,
            get_settings,
            save_settings,
            socket_config,
            core_status,
            core_start,
            free_port,
            core_stop,
            send_request
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            let settings = ensure_tokens(&handle);

            let window = app.get_webview_window("main").ok_or("Main overlay window missing")?;
            window.set_ignore_cursor_events(true)?;
            window.set_focusable(false)?;
            if let Some(monitor) = window.primary_monitor()? {
                window.set_position(*monitor.position())?;
                window.set_size(*monitor.size())?;
            }

            // The settings window is the only window a person can ever see, and it
            // hides instead of closing so the app keeps running in the tray.
            if let Some(panel) = app.get_webview_window("settings") {
                let hidden = panel.clone();
                panel.on_window_event(move |event| {
                    if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();
                        let _ = hidden.hide();
                    }
                });
            }

            let open = MenuItem::with_id(app, "settings", "Settings…", true, None::<&str>)?;
            let toggle = MenuItem::with_id(app, "toggle", "Toggle overlay (Ctrl+Alt+J)", true, None::<&str>)?;
            let start = MenuItem::with_id(app, "core_start", "Start Core", true, None::<&str>)?;
            let stop = MenuItem::with_id(app, "core_stop", "Stop Core", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &toggle, &start, &stop, &quit])?;
            TrayIconBuilder::with_id("tray")
                .icon(app.default_window_icon().ok_or("Tray icon missing")?.clone())
                .tooltip("Thursday")
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "settings" => show_settings(app),
                    "toggle" => {
                        let _ = app.emit_to("main", "overlay-toggle", SummonOrigin { x: 0.0, y: 0.0 });
                    }
                    "core_start" => {
                        let state = app.state::<CoreProcess>();
                        if let Err(error) = core_start(app.clone(), state) {
                            eprintln!("{error}");
                        }
                    }
                    "core_stop" => {
                        let _ = core_stop(app.state::<CoreProcess>());
                    }
                    "quit" => {
                        let _ = core_stop(app.state::<CoreProcess>());
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;

            let summon = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyJ);
            let leave = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT | Modifiers::SHIFT), Code::KeyJ);
            app.handle().plugin(
                tauri_plugin_global_shortcut::Builder::new()
                    .with_handler(move |app, shortcut, event| {
                        if event.state() != ShortcutState::Released {
                            return;
                        }
                        if shortcut == &leave {
                            let _ = core_stop(app.state::<CoreProcess>());
                            app.exit(0);
                        } else if shortcut == &summon {
                            let origin = app
                                .get_webview_window("main")
                                .and_then(|window| {
                                    let cursor = window.cursor_position().ok()?;
                                    let position = window.outer_position().ok()?;
                                    let scale = window.scale_factor().ok()?;
                                    Some(SummonOrigin {
                                        x: (cursor.x - f64::from(position.x)) / scale,
                                        y: (cursor.y - f64::from(position.y)) / scale,
                                    })
                                })
                                .unwrap_or(SummonOrigin { x: 0.0, y: 0.0 });
                            if let Err(error) = app.emit_to("main", "overlay-toggle", origin) {
                                eprintln!("Unable to toggle overlay: {error}");
                            }
                        }
                    })
                    .build(),
            )?;
            app.global_shortcut().register(summon)?;
            app.global_shortcut().register(leave)?;

            if settings.autostart_core && !settings.repo_path.is_empty() {
                let state = handle.state::<CoreProcess>();
                if let Err(error) = core_start(handle.clone(), state) {
                    eprintln!("{error}");
                }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if window.label() == "main" {
                    let _ = core_stop(window.app_handle().state::<CoreProcess>());
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("Unable to start Thursday; check whether its shortcuts are already in use");
}
