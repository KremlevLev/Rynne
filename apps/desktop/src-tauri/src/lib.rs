use serde_json::Value;

/// The command exists from the first migration slice so the UI fails closed:
/// it reports the Core as disconnected until the sidecar bridge is attached.
#[tauri::command]
fn nova_connect() -> bool {
    false
}

#[tauri::command]
fn nova_send_command(_command: Value) -> Result<(), String> {
    Err("Nova Core sidecar is not connected yet.".to_owned())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            nova_connect,
            nova_send_command
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Nova desktop");
}
