//! Protocol v1.0 UI transport. Credentials stay in the native process.
use std::{net::TcpStream, sync::{Mutex, mpsc}, time::Duration};
use tauri::{Emitter, Manager};
use tungstenite::{Message, client::client_with_config, protocol::WebSocketConfig};

#[derive(Default)]
pub struct CoreLink(pub Mutex<Option<mpsc::Sender<String>>>);

#[tauri::command]
pub fn core_send(window: tauri::WebviewWindow, state: tauri::State<CoreLink>, json: String) -> Result<(), String> {
    if window.label() != "assistant" { return Err("Only the Assistant window sends requests".into()); }
    if json.len() > 3_000_000 { return Err("Message too large".into()); }
    let value: serde_json::Value = serde_json::from_str(&json).map_err(|_| "Invalid JSON")?;
    if value["version"] != "1.0" || !matches!(value["type"].as_str(), Some("user_request" | "user_reply" | "confirmation_response" | "cancel")) {
        return Err("Unsupported UI message".into());
    }
    state.0.lock().map_err(|_| "Connection unavailable")?.as_ref()
        .ok_or("Connect to Core first")?.send(json).map_err(|_| "Core disconnected".into())
}

#[tauri::command]
pub fn core_connect(window: tauri::WebviewWindow, app: tauri::AppHandle, state: tauri::State<CoreLink>) -> Result<(), String> {
    if window.label() != "assistant" { return Err("Only the Assistant window connects".into()); }
    let token = std::env::var("AGENT_UI_TOKEN").map_err(|_| "Launch JARVIS with AGENT_UI_TOKEN from your trusted launcher")?;
    if !(32..=256).contains(&token.len()) { return Err("AGENT_UI_TOKEN must contain 32–256 characters".into()); }
    let mut guard = state.0.lock().map_err(|_| "Connection unavailable")?;
    if guard.is_some() { return Err("Already connected or connecting".into()); }
    let (tx, rx) = mpsc::channel::<String>();
    *guard = Some(tx);
    drop(guard);
    std::thread::spawn(move || {
        let result = (|| -> Result<(), String> {
            let stream = TcpStream::connect_timeout(&"127.0.0.1:8765".parse().unwrap(), Duration::from_secs(3)).map_err(|_| "Core is not running on port 8765")?;
            stream.set_read_timeout(Some(Duration::from_secs(5))).map_err(|_| "Socket configuration failed")?;
            stream.set_write_timeout(Some(Duration::from_secs(3))).map_err(|_| "Socket configuration failed")?;
            let config = WebSocketConfig::default().max_message_size(Some(3_000_000)).max_frame_size(Some(3_000_000));
            let (mut socket, _) = client_with_config("ws://127.0.0.1:8765/v1/ui", stream, Some(config)).map_err(|_| "Core handshake failed")?;
            socket.send(Message::Text(serde_json::json!({"version":"1.0","type":"hello","request_id":"ui_hello","payload":{"role":"ui","token":token}}).to_string().into())).map_err(|_| "Authentication failed")?;
            let ack = socket.read().map_err(|_| "Core authentication failed")?;
            let ack: serde_json::Value = serde_json::from_str(ack.to_text().map_err(|_| "Invalid Core handshake")?).map_err(|_| "Invalid Core handshake")?;
            if ack["version"] != "1.0" || ack["type"] != "hello_ack" || ack["request_id"] != "ui_hello" || ack["payload"]["role"] != "ui" { return Err("Core authentication rejected".into()); }
            socket.get_mut().set_read_timeout(Some(Duration::from_millis(50))).map_err(|_| "Socket configuration failed")?;
            let _ = app.emit_to("assistant", "core-connection", "connected");
            loop {
                while let Ok(json) = rx.try_recv() { socket.send(Message::Text(json.into())).map_err(|_| "Core disconnected")?; }
                match socket.read() {
                    Ok(Message::Text(json)) => {
                        let value: serde_json::Value = serde_json::from_str(&json).map_err(|_| "Invalid Core message")?;
                        if value["version"] != "1.0" || !matches!(value["type"].as_str(), Some("agent_event" | "error")) { return Err("Unexpected Core message".into()); }
                        let _ = app.emit_to("assistant", "core-message", value);
                    }
                    Ok(Message::Close(_)) => return Err("Core disconnected".into()),
                    Ok(_) => { let _ = socket.flush(); }
                    Err(tungstenite::Error::Io(e)) if matches!(e.kind(), std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut) => {}
                    Err(_) => return Err("Core disconnected".into()),
                }
            }
        })();
        if let Ok(mut guard) = app.state::<CoreLink>().0.lock() { *guard = None; }
        let _ = app.emit_to("assistant", "core-connection", result.err().unwrap_or_else(|| "Disconnected".into()));
    });
    Ok(())
}
