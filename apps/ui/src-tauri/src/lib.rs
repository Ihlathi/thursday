use std::sync::atomic::{AtomicBool, Ordering};

use serde::Serialize;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, Runtime, State, WebviewWindow};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

#[derive(Clone, Serialize)]
struct SummonEvent {
    active: bool,
    /// Which panel the overlay should show: "assistant" or "settings".
    view: String,
    x: f64,
    y: f64,
}

#[derive(Serialize)]
struct CoreConnectionConfig {
    url: String,
    token: String,
}

struct OverlayState(AtomicBool);

fn set_overlay_interaction<R: Runtime>(window: &WebviewWindow<R>, active: bool) -> Result<(), String> {
    window
        .set_ignore_cursor_events(!active)
        .map_err(|error| error.to_string())?;
    window
        .set_focusable(active)
        .map_err(|error| error.to_string())?;
    if active {
        window.show().map_err(|error| error.to_string())?;
        window.set_focus().map_err(|error| error.to_string())?;
    }
    Ok(())
}

/// Single path used by the shortcut, the tray menu and the tray click, so the
/// overlay's interaction flag and the frontend can never disagree.
fn apply_overlay<R: Runtime>(app: &AppHandle<R>, active: bool, view: &str) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let state = app.state::<OverlayState>();
    state.0.store(active, Ordering::SeqCst);

    let origin = window
        .cursor_position()
        .ok()
        .and_then(|cursor| {
            let window_position = window.outer_position().ok()?;
            let scale = window.scale_factor().ok()?;
            Some((
                (cursor.x - f64::from(window_position.x)) / scale,
                (cursor.y - f64::from(window_position.y)) / scale,
            ))
        })
        .unwrap_or((0.0, 0.0));

    if let Err(error) = set_overlay_interaction(&window, active) {
        eprintln!("Unable to update overlay interaction: {error}");
        return;
    }
    if let Err(error) = app.emit_to(
        "main",
        "jarvis-toggle",
        SummonEvent {
            active,
            view: view.to_string(),
            x: origin.0,
            y: origin.1,
        },
    ) {
        eprintln!("Unable to toggle overlay: {error}");
    }
}

fn toggle_overlay<R: Runtime>(app: &AppHandle<R>, view: &str) {
    let state = app.state::<OverlayState>();
    let currently_active = state.0.load(Ordering::SeqCst);
    // Asking for a different panel while open switches panel instead of closing.
    let next_active = !currently_active || view == "settings";
    apply_overlay(app, next_active, view);
}

#[tauri::command]
fn overlay_ready(window: WebviewWindow) -> Result<(), String> {
    window.show().map_err(|error| error.to_string())
}

#[tauri::command]
fn set_overlay_active(
    window: WebviewWindow,
    state: State<'_, OverlayState>,
    active: bool,
) -> Result<(), String> {
    state.0.store(active, Ordering::SeqCst);
    set_overlay_interaction(&window, active)
}

#[tauri::command]
fn core_connection_config() -> Result<CoreConnectionConfig, String> {
    let token = std::env::var("AGENT_UI_TOKEN").map_err(|_| {
        "AGENT_UI_TOKEN is not set. Start JARVIS through its trusted launcher.".to_string()
    })?;
    if !(32..=256).contains(&token.len()) {
        return Err("AGENT_UI_TOKEN must contain 32 to 256 characters.".to_string());
    }

    let url =
        std::env::var("AGENT_UI_URL").unwrap_or_else(|_| "ws://127.0.0.1:8765/v1/ui".to_string());
    let loopback = url.starts_with("ws://127.0.0.1:") && url.ends_with("/v1/ui");
    if !loopback {
        return Err("AGENT_UI_URL must use ws://127.0.0.1:<port>/v1/ui.".to_string());
    }
    Ok(CoreConnectionConfig { url, token })
}

fn build_tray<R: Runtime>(app: &AppHandle<R>) -> Result<(), Box<dyn std::error::Error>> {
    let open = MenuItem::with_id(app, "open", "Open JARVIS", true, Some("Ctrl+Alt+J"))?;
    let settings = MenuItem::with_id(app, "settings", "Settings…", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, "quit", "Quit JARVIS", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &settings, &separator, &quit])?;

    let mut tray = TrayIconBuilder::with_id("jarvis")
        .tooltip("JARVIS — press Ctrl+Alt+J")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open" => apply_overlay(app, true, "assistant"),
            "settings" => apply_overlay(app, true, "settings"),
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                toggle_overlay(tray.app_handle(), "assistant");
            }
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(OverlayState(AtomicBool::new(false)))
        .plugin(tauri_plugin_websocket::init())
        .invoke_handler(tauri::generate_handler![
            overlay_ready,
            set_overlay_active,
            core_connection_config
        ])
        .setup(|app| {
            let window = app
                .get_webview_window("main")
                .ok_or("Main overlay window missing")?;
            set_overlay_interaction(&window, false)?;
            if let Some(monitor) = window.primary_monitor()? {
                window.set_position(*monitor.position())?;
                window.set_size(*monitor.size())?;
            }

            // The tray is the resting state of the app: closing the overlay
            // leaves JARVIS running here rather than quitting it.
            if let Err(error) = build_tray(app.handle()) {
                eprintln!("Unable to create the tray icon: {error}");
            }

            let toggle = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyJ);
            let quit = Shortcut::new(
                Some(Modifiers::CONTROL | Modifiers::ALT | Modifiers::SHIFT),
                Code::KeyJ,
            );
            app.handle().plugin(
                tauri_plugin_global_shortcut::Builder::new()
                    .with_handler(move |app, shortcut, event| {
                        if event.state() != ShortcutState::Released {
                            return;
                        }
                        if shortcut == &quit {
                            app.exit(0);
                        } else if shortcut == &toggle {
                            toggle_overlay(app, "assistant");
                        }
                    })
                    .build(),
            )?;
            app.global_shortcut().register(toggle)?;
            app.global_shortcut().register(quit)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("Unable to start JARVIS; check whether its shortcuts are already in use");
}
