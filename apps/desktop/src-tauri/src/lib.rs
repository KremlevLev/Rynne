use serde_json::Value;
use std::{
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
};
use tauri::{AppHandle, Emitter, Manager, State};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

struct CoreProcess {
    child: Child,
    stdin: ChildStdin,
}

#[derive(Default)]
struct CoreState {
    process: Mutex<Option<CoreProcess>>,
    connected: AtomicBool,
}

#[tauri::command]
fn nova_connect(state: State<'_, Arc<CoreState>>) -> bool {
    let mut guard = match state.process.lock() {
        Ok(guard) => guard,
        Err(_) => return false,
    };
    let Some(process) = guard.as_mut() else {
        return false;
    };

    match process.child.try_wait() {
        Ok(None) => state.connected.load(Ordering::Acquire),
        Ok(Some(_)) | Err(_) => {
            state.connected.store(false, Ordering::Release);
            *guard = None;
            false
        }
    }
}

#[tauri::command]
fn nova_send_command(command: Value, state: State<'_, Arc<CoreState>>) -> Result<(), String> {
    if !state.connected.load(Ordering::Acquire) {
        return Err("Nova Core is not connected.".to_owned());
    }

    let mut guard = state
        .process
        .lock()
        .map_err(|_| "Nova Core process lock is poisoned.".to_owned())?;
    let process = guard
        .as_mut()
        .ok_or_else(|| "Nova Core process is unavailable.".to_owned())?;

    serde_json::to_writer(&mut process.stdin, &command)
        .map_err(|error| format!("Cannot encode Nova command: {error}"))?;
    process
        .stdin
        .write_all(b"\n")
        .and_then(|_| process.stdin.flush())
        .map_err(|error| format!("Cannot send command to Nova Core: {error}"))
}

#[tauri::command]
fn nova_configure_provider(
    provider: String,
    api_key: String,
    app: AppHandle,
    state: State<'_, Arc<CoreState>>,
) -> Result<(), String> {
    let variable = match provider.trim().to_lowercase().as_str() {
        "groq" => "GROQ_API_KEY",
        "openrouter" => "OPENROUTER_API_KEY",
        "gemini" => "GEMINI_API_KEY",
        _ => return Err("Unsupported model provider.".to_owned()),
    };
    let key = api_key.trim();
    if key.len() < 12
        || key.len() > 512
        || !key
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || "_-.".contains(character))
    {
        return Err("API key has an invalid format.".to_owned());
    }

    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("Cannot locate Nova data directory: {error}"))?;
    std::fs::create_dir_all(&data_dir)
        .map_err(|error| format!("Cannot create Nova data directory: {error}"))?;
    let env_path = data_dir.join(".env");
    let current = std::fs::read_to_string(&env_path).unwrap_or_default();
    let mut lines: Vec<String> = current
        .lines()
        .filter(|line| !line.trim_start().starts_with(&format!("{variable}=")))
        .map(str::to_owned)
        .collect();
    lines.push(format!("{variable}={key}"));
    std::fs::write(&env_path, format!("{}\n", lines.join("\n")))
        .map_err(|error| format!("Cannot save Nova provider settings: {error}"))?;

    let core_state = state.inner().clone();
    stop_core(&core_state);
    spawn_core(app, core_state)
}

fn build_core_command(app: &AppHandle) -> Result<Command, String> {
    if let Some(executable) = std::env::var_os("NOVA_CORE_SIDECAR") {
        return Ok(Command::new(executable));
    }

    if cfg!(debug_assertions) {
        let repository = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../..")
            .canonicalize()
            .map_err(|error| format!("Cannot locate Nova repository: {error}"))?;
        let mut command = Command::new("python");
        command
            .arg(repository.join("nova_sidecar.py"))
            .current_dir(repository);
        return Ok(command);
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("Cannot locate Nova resources: {error}"))?;
    let binary_name = core_binary_name();
    let executable = [
        resource_dir
            .join(format!("nova-core-{}", env!("CARGO_PKG_VERSION")))
            .join(&binary_name),
        resource_dir
            .join("resources")
            .join("nova-core")
            .join(&binary_name),
        resource_dir.join("nova-core").join(&binary_name),
    ]
    .into_iter()
    .find(|candidate| candidate.is_file())
    .ok_or_else(|| {
        format!(
            "Packaged Nova Core is missing below {}",
            resource_dir.display()
        )
    })?;

    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("Cannot locate Nova data directory: {error}"))?;
    std::fs::create_dir_all(&data_dir)
        .map_err(|error| format!("Cannot create Nova data directory: {error}"))?;

    let mut command = Command::new(executable);
    command.current_dir(data_dir);
    Ok(command)
}

fn core_binary_name() -> PathBuf {
    #[cfg(windows)]
    {
        PathBuf::from("nova-core.exe")
    }
    #[cfg(not(windows))]
    {
        PathBuf::from("nova-core")
    }
}

fn spawn_core(app: AppHandle, state: Arc<CoreState>) -> Result<(), String> {
    let mut command = build_core_command(&app)?;
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);

    let mut child = command
        .spawn()
        .map_err(|error| format!("Cannot launch Nova Core: {error}"))?;
    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| "Nova Core stdin is unavailable.".to_owned())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "Nova Core stdout is unavailable.".to_owned())?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "Nova Core stderr is unavailable.".to_owned())?;

    {
        let mut guard = state
            .process
            .lock()
            .map_err(|_| "Nova Core process lock is poisoned.".to_owned())?;
        *guard = Some(CoreProcess { child, stdin });
    }
    state.connected.store(false, Ordering::Release);

    let event_app = app.clone();
    let event_state = state.clone();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines() {
            let Ok(line) = line else {
                break;
            };
            let Ok(event) = serde_json::from_str::<Value>(&line) else {
                continue;
            };
            let is_event = event.get("event_type").and_then(Value::as_str).is_some()
                && event.get("payload").is_some();
            if is_event {
                if !event_state.connected.swap(true, Ordering::AcqRel) {
                    let _ = event_app.emit("nova:connection", true);
                }
                let _ = event_app.emit("nova:event", event);
            }
        }
        event_state.connected.store(false, Ordering::Release);
        let _ = event_app.emit("nova:connection", false);
    });

    std::thread::spawn(move || {
        for line in BufReader::new(stderr).lines() {
            if let Ok(line) = line {
                eprintln!("[Nova Core] {line}");
            }
        }
    });

    Ok(())
}

fn stop_core(state: &Arc<CoreState>) {
    state.connected.store(false, Ordering::Release);
    if let Ok(mut guard) = state.process.lock() {
        if let Some(mut process) = guard.take() {
            let _ = process.child.kill();
            let _ = process.child.wait();
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let core_state = Arc::new(CoreState::default());
    let state_for_setup = core_state.clone();

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .manage(core_state.clone())
        .invoke_handler(tauri::generate_handler![
            nova_connect,
            nova_send_command,
            nova_configure_provider
        ])
        .setup(move |app| {
            if let Err(error) = spawn_core(app.handle().clone(), state_for_setup.clone()) {
                eprintln!("[Nova Desktop] {error}");
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Nova desktop");

    app.run(move |_app_handle, event| {
        if matches!(
            event,
            tauri::RunEvent::Exit | tauri::RunEvent::ExitRequested { .. }
        ) {
            stop_core(&core_state);
        }
    });
}
