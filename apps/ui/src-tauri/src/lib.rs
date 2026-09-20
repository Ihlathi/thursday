mod core_link;
use std::fs;
use std::path::PathBuf;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{Emitter, Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

#[derive(Clone, serde::Serialize)]
struct SummonOrigin {
    x: f64,
    y: f64,
}

#[tauri::command]
fn overlay_ready(window: tauri::WebviewWindow) -> Result<(), String> {
    window.show().map_err(|error| error.to_string())
}

#[tauri::command]
fn cursor_origin(window: tauri::WebviewWindow) -> Result<SummonOrigin, String> {
    let cursor = window.cursor_position().map_err(|error| error.to_string())?;
    let window_position = window.outer_position().map_err(|error| error.to_string())?;
    let scale = window.scale_factor().map_err(|error| error.to_string())?;
    Ok(SummonOrigin {
        x: (cursor.x - f64::from(window_position.x)) / scale,
        y: (cursor.y - f64::from(window_position.y)) / scale,
    })
}

#[tauri::command]
fn set_cursor_position(window: tauri::WebviewWindow, x: f64, y: f64) -> Result<(), String> {
    window
        .set_cursor_position(tauri::LogicalPosition::new(x, y))
        .map_err(|error| error.to_string())
}

fn visual_settings_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let directory = app.path().app_config_dir().map_err(|error| error.to_string())?;
    Ok(directory.join("visual-settings.json"))
}

#[tauri::command]
fn load_visual_settings(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let path = visual_settings_path(&app)?;
    match fs::read_to_string(path) {
        Ok(json) => Ok(Some(json)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.to_string()),
    }
}

#[tauri::command]
fn save_visual_settings(app: tauri::AppHandle, json: String) -> Result<(), String> {
    serde_json::from_str::<serde_json::Value>(&json).map_err(|error| error.to_string())?;
    let path = visual_settings_path(&app)?;
    if let Some(directory) = path.parent() {
        fs::create_dir_all(directory).map_err(|error| error.to_string())?;
    }
    fs::write(path, json).map_err(|error| error.to_string())
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
        .manage(core_link::CoreLink::default())
        .invoke_handler(tauri::generate_handler![
            core_link::core_connect,
            core_link::core_send,
            overlay_ready,
            cursor_origin,
            set_cursor_position,
            load_visual_settings,
            save_visual_settings
        ])
        .setup(|app| {
            let window = app.get_webview_window("main").ok_or("Main overlay window missing")?;
            window.set_ignore_cursor_events(true)?;
            window.set_focusable(false)?;
            if let Some(monitor) = window.primary_monitor()? {
                window.set_position(*monitor.position())?;
                window.set_size(*monitor.size())?;
            }

            let settings = WebviewWindowBuilder::new(
                app,
                "settings",
                WebviewUrl::App("index.html".into()),
            )
            .title("JARVIS Settings")
            .inner_size(940.0, 720.0)
            .min_inner_size(720.0, 560.0)
            .center()
            .visible(false)
            .resizable(true)
            .build()?;
            let settings_for_close = settings.clone();
            settings.on_window_event(move |event| {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = settings_for_close.hide();
                }
            });

            let assistant = WebviewWindowBuilder::new(app, "assistant", WebviewUrl::App("index.html".into()))
                .title("JARVIS Assistant").inner_size(650.0, 680.0).min_inner_size(480.0, 480.0)
                .center().visible(false).build()?;
            let assistant_close = assistant.clone();
            assistant.on_window_event(move |event| {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = assistant_close.hide();
                }
            });
            let assistant_item = MenuItem::with_id(app, "assistant", "Open Assistant", true, None::<&str>)?;
            let settings_item = MenuItem::with_id(app, "settings", "Settings", true, None::<&str>)?;
            let summon_item = MenuItem::with_id(app, "summon", "Show / Summon JARVIS", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit JARVIS", true, None::<&str>)?;
            let tray_menu = Menu::with_items(app, &[&assistant_item, &settings_item, &summon_item, &quit_item])?;
            let mut tray_builder = TrayIconBuilder::with_id("jarvis")
                .menu(&tray_menu)
                .tooltip("JARVIS")
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "assistant" => {
                        if let Some(window) = app.get_webview_window("assistant") {
                            let _ = window.show(); let _ = window.unminimize(); let _ = window.set_focus();
                        }
                    }
                    "settings" => show_settings(app),
                    "summon" => {
                        if let Err(error) = app.emit_to("main", "jarvis-toggle", ()) {
                            eprintln!("Unable to toggle overlay: {error}");
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                });
            if let Some(icon) = app.default_window_icon() {
                tray_builder = tray_builder.icon(icon.clone());
            }
            let tray = tray_builder.build(app)?;
            app.manage(tray);

            let toggle = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyJ);
            let aura = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyM);
            let movement = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyT);
            let click = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyC);
            let action = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyA);
            let quit = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT | Modifiers::SHIFT), Code::KeyJ);
            app.handle().plugin(
                tauri_plugin_global_shortcut::Builder::new()
                    .with_handler(move |app, shortcut, event| {
                        if event.state() == ShortcutState::Released {
                            if shortcut == &quit {
                                app.exit(0);
                            } else if shortcut == &toggle {
                                if let Err(error) = app.emit_to("main", "jarvis-toggle", ()) {
                                    eprintln!("Unable to toggle overlay: {error}");
                                }
                            } else {
                                let action = if shortcut == &aura {
                                    Some("aura")
                                } else if shortcut == &movement {
                                    Some("movement")
                                } else if shortcut == &click {
                                    Some("click")
                                } else if shortcut == &action {
                                    Some("action")
                                } else {
                                    None
                                };
                                if let Some(action) = action {
                                    if let Err(error) = app.emit_to("main", "jarvis-dev-action", action) {
                                        eprintln!("Unable to run cursor visual: {error}");
                                    }
                                }
                            }
                        }
                    })
                    .build(),
            )?;
            app.global_shortcut().register(toggle)?;
            app.global_shortcut().register(aura)?;
            app.global_shortcut().register(movement)?;
            app.global_shortcut().register(click)?;
            app.global_shortcut().register(action)?;
            app.global_shortcut().register(quit)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("Unable to start JARVIS; check whether its shortcuts are already in use");
}
