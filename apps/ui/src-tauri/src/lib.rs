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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![overlay_ready])
        .setup(|app| {
            let window = app.get_webview_window("main").ok_or("Main overlay window missing")?;
            window.set_ignore_cursor_events(true)?;
            window.set_focusable(false)?;
            if let Some(monitor) = window.primary_monitor()? {
                window.set_position(*monitor.position())?;
                window.set_size(*monitor.size())?;
            }
            let toggle = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyJ);
            let quit = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT | Modifiers::SHIFT), Code::KeyJ);
            app.handle().plugin(
                tauri_plugin_global_shortcut::Builder::new()
                    .with_handler(move |app, shortcut, event| {
                        if event.state() == ShortcutState::Released {
                            if shortcut == &quit {
                                app.exit(0);
                            } else if shortcut == &toggle {
                                let origin = app.get_webview_window("main").and_then(|window| {
                                    let cursor = window.cursor_position().ok()?;
                                    let window_position = window.outer_position().ok()?;
                                    let scale = window.scale_factor().ok()?;
                                    Some(SummonOrigin {
                                        x: (cursor.x - f64::from(window_position.x)) / scale,
                                        y: (cursor.y - f64::from(window_position.y)) / scale,
                                    })
                                }).unwrap_or(SummonOrigin { x: 0.0, y: 0.0 });
                                if let Err(error) = app.emit_to("main", "jarvis-toggle", origin) {
                                    eprintln!("Unable to toggle overlay: {error}");
                                }
                            }
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
