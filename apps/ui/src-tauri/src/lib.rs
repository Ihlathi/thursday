use tauri::{Emitter, Manager};
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![overlay_ready, cursor_origin, set_cursor_position])
        .setup(|app| {
            let window = app.get_webview_window("main").ok_or("Main overlay window missing")?;
            window.set_ignore_cursor_events(true)?;
            window.set_focusable(false)?;
            if let Some(monitor) = window.primary_monitor()? {
                window.set_position(*monitor.position())?;
                window.set_size(*monitor.size())?;
            }
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
