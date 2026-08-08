use serde::Serialize;
use serde_json::Value;
use std::{
    fs::{create_dir_all, File, OpenOptions},
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use tauri::{AppHandle, Emitter, Manager, State};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const CORE_STARTUP_TIMEOUT: Duration = Duration::from_secs(45);
const CORE_RESTART_COOLDOWN: Duration = Duration::from_secs(5);

struct CoreProcess {
    child: Child,
    stdin: ChildStdin,
    started_at: Instant,
}

#[derive(Default)]
struct CoreState {
    process: Mutex<Option<CoreProcess>>,
    connected: AtomicBool,
    generation: AtomicU64,
    last_spawn_attempt: Mutex<Option<Instant>>,
    shutting_down: AtomicBool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ProviderKeySummary {
    provider: String,
    index: usize,
    hint: String,
    source: String,
    removable: bool,
}

fn provider_variables(provider: &str) -> Result<(&'static str, &'static str), String> {
    match provider.trim().to_lowercase().as_str() {
        "groq" => Ok(("GROQ_API_KEYS", "GROQ_API_KEY")),
        "openrouter" => Ok(("OPENROUTER_API_KEYS", "OPENROUTER_API_KEY")),
        "gemini" => Ok(("GEMINI_API_KEYS", "GEMINI_API_KEY")),
        _ => Err("Unsupported model provider.".to_owned()),
    }
}

fn split_key_list(value: &str) -> Vec<String> {
    let unquoted = value
        .trim()
        .trim_matches(|character| character == '"' || character == '\'');
    let mut keys = Vec::new();
    for raw_key in unquoted.split(',') {
        let key = raw_key.trim();
        if !key.is_empty() && !keys.iter().any(|existing| existing == key) {
            keys.push(key.to_owned());
        }
    }
    keys
}

fn env_value(contents: &str, variable: &str) -> Option<String> {
    contents.lines().find_map(|line| {
        let (name, value) = line.split_once('=')?;
        (name.trim() == variable).then(|| value.trim().to_owned())
    })
}

fn numbered_key_values<'a>(
    pairs: impl Iterator<Item = (&'a str, &'a str)>,
    prefix: &str,
) -> Vec<String> {
    let numbered_prefix = format!("{prefix}_");
    let mut values: Vec<(usize, String)> = pairs
        .filter_map(|(name, raw_value)| {
            let suffix = name.strip_prefix(&numbered_prefix)?;
            let index = suffix.parse::<usize>().ok()?;
            let value = raw_value.trim();
            (!value.is_empty()).then(|| (index, value.to_owned()))
        })
        .collect();
    values.sort_by_key(|(index, _)| *index);
    values.into_iter().map(|(_, value)| value).collect()
}

fn file_provider_keys(contents: &str, provider: &str) -> Result<Vec<String>, String> {
    let (plural, legacy) = provider_variables(provider)?;
    let mut keys = env_value(contents, plural)
        .map(|value| split_key_list(&value))
        .unwrap_or_default();
    if let Some(value) = env_value(contents, legacy) {
        for key in split_key_list(&value) {
            if !keys.contains(&key) {
                keys.push(key);
            }
        }
    }
    let pairs = contents.lines().filter_map(|line| line.split_once('='));
    for key in numbered_key_values(pairs, legacy) {
        if !keys.contains(&key) {
            keys.push(key);
        }
    }
    Ok(keys)
}

fn inherited_provider_keys(provider: &str) -> Result<Vec<String>, String> {
    let (plural, legacy) = provider_variables(provider)?;
    let mut keys = std::env::var(plural)
        .ok()
        .map(|value| split_key_list(&value))
        .unwrap_or_default();
    if let Ok(value) = std::env::var(legacy) {
        for key in split_key_list(&value) {
            if !keys.contains(&key) {
                keys.push(key);
            }
        }
    }
    let environment: Vec<(String, String)> = std::env::vars().collect();
    for key in numbered_key_values(
        environment
            .iter()
            .map(|(name, value)| (name.as_str(), value.as_str())),
        legacy,
    ) {
        if !keys.contains(&key) {
            keys.push(key);
        }
    }
    Ok(keys)
}

fn key_hint(key: &str) -> String {
    let characters: Vec<char> = key.chars().collect();
    let prefix_length = 10.min(characters.len().saturating_sub(6));
    let suffix_length = 4.min(characters.len().saturating_sub(prefix_length));
    let prefix: String = characters[..prefix_length].iter().collect();
    let suffix: String = characters[characters.len() - suffix_length..]
        .iter()
        .collect();
    format!("{prefix}••••••••{suffix}")
}

fn provider_env_path(app: &AppHandle) -> Result<PathBuf, String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("Cannot locate Nova data directory: {error}"))?;
    create_dir_all(&data_dir)
        .map_err(|error| format!("Cannot create Nova data directory: {error}"))?;
    Ok(data_dir.join(".env"))
}

fn write_provider_keys(env_path: &Path, provider: &str, keys: &[String]) -> Result<(), String> {
    let (plural, legacy) = provider_variables(provider)?;
    let current = std::fs::read_to_string(env_path).unwrap_or_default();
    let mut lines: Vec<String> = current
        .lines()
        .filter(|line| {
            let variable = line
                .split_once('=')
                .map(|(name, _)| name.trim())
                .unwrap_or("");
            let numbered = variable
                .strip_prefix(&format!("{legacy}_"))
                .is_some_and(|suffix| suffix.parse::<usize>().is_ok());
            variable != plural && variable != legacy && !numbered
        })
        .map(str::to_owned)
        .collect();
    if !keys.is_empty() {
        lines.push(format!("{plural}={}", keys.join(",")));
    }
    let contents = if lines.is_empty() {
        String::new()
    } else {
        format!("{}\n", lines.join("\n"))
    };
    std::fs::write(env_path, contents)
        .map_err(|error| format!("Cannot save Nova provider settings: {error}"))
}

fn validate_api_key(api_key: &str) -> Result<&str, String> {
    let key = api_key.trim();
    if key.len() < 12
        || key.len() > 512
        || key.contains(',')
        || !key
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || "_-.".contains(character))
    {
        return Err("API key has an invalid format.".to_owned());
    }
    Ok(key)
}

#[tauri::command]
fn nova_connect(app: AppHandle, state: State<'_, Arc<CoreState>>) -> bool {
    ensure_core_running(&app, state.inner())
}

fn ensure_core_running(app: &AppHandle, core_state: &Arc<CoreState>) -> bool {
    if core_state.shutting_down.load(Ordering::Acquire) {
        return false;
    }

    let mut guard = match core_state.process.lock() {
        Ok(guard) => guard,
        Err(_) => return false,
    };
    let connected = core_state.connected.load(Ordering::Acquire);
    let restart_needed = match guard.as_mut() {
        Some(process) => match process.child.try_wait() {
            Ok(None) => !connected && process.started_at.elapsed() >= CORE_STARTUP_TIMEOUT,
            Ok(Some(status)) => {
                append_supervisor_log(app, &format!("Core exited with status {status}."));
                true
            }
            Err(error) => {
                append_supervisor_log(app, &format!("Cannot inspect Core process: {error}"));
                true
            }
        },
        None => true,
    };

    if !restart_needed {
        return connected;
    }

    core_state.connected.store(false, Ordering::Release);
    if let Some(mut process) = guard.take() {
        let _ = process.child.kill();
        let _ = process.child.wait();
    }
    drop(guard);

    if claim_restart(core_state) {
        append_supervisor_log(app, "Restarting Nova Core.");
        if let Err(error) = spawn_core(app.clone(), core_state.clone()) {
            append_supervisor_log(app, &format!("Core restart failed: {error}"));
        }
    }

    false
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
fn nova_list_provider_keys(app: AppHandle) -> Result<Vec<ProviderKeySummary>, String> {
    let env_path = provider_env_path(&app)?;
    let contents = std::fs::read_to_string(&env_path).unwrap_or_default();
    let mut summaries = Vec::new();

    for provider in ["groq", "openrouter", "gemini"] {
        let file_keys = file_provider_keys(&contents, provider)?;
        let inherited_keys = inherited_provider_keys(provider)?;

        for (index, key) in file_keys.iter().enumerate() {
            summaries.push(ProviderKeySummary {
                provider: provider.to_owned(),
                index,
                hint: key_hint(key),
                source: "nova".to_owned(),
                removable: true,
            });
        }
        for key in inherited_keys {
            if file_keys.contains(&key) {
                continue;
            }
            summaries.push(ProviderKeySummary {
                provider: provider.to_owned(),
                index: 0,
                hint: key_hint(&key),
                source: "environment".to_owned(),
                removable: false,
            });
        }
    }

    Ok(summaries)
}

fn add_provider_key(
    provider: String,
    api_key: String,
    app: AppHandle,
    state: State<'_, Arc<CoreState>>,
) -> Result<(), String> {
    provider_variables(&provider)?;
    let key = validate_api_key(&api_key)?;
    let env_path = provider_env_path(&app)?;
    let current = std::fs::read_to_string(&env_path).unwrap_or_default();
    let mut keys = file_provider_keys(&current, &provider)?;
    if !keys.iter().any(|existing| existing == key) {
        keys.push(key.to_owned());
        write_provider_keys(&env_path, &provider, &keys)?;
    }

    let core_state = state.inner().clone();
    stop_core(&core_state);
    spawn_core(app, core_state)
}

#[tauri::command]
fn nova_add_provider_key(
    provider: String,
    api_key: String,
    app: AppHandle,
    state: State<'_, Arc<CoreState>>,
) -> Result<(), String> {
    add_provider_key(provider, api_key, app, state)
}

#[tauri::command]
fn nova_configure_provider(
    provider: String,
    api_key: String,
    app: AppHandle,
    state: State<'_, Arc<CoreState>>,
) -> Result<(), String> {
    add_provider_key(provider, api_key, app, state)
}

#[tauri::command]
fn nova_remove_provider_key(
    provider: String,
    index: usize,
    app: AppHandle,
    state: State<'_, Arc<CoreState>>,
) -> Result<(), String> {
    provider_variables(&provider)?;
    let env_path = provider_env_path(&app)?;
    let current = std::fs::read_to_string(&env_path).unwrap_or_default();
    let mut keys = file_provider_keys(&current, &provider)?;
    if index >= keys.len() {
        return Err("Provider key was not found.".to_owned());
    }
    keys.remove(index);
    write_provider_keys(&env_path, &provider, &keys)?;

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

fn apply_provider_environment(command: &mut Command, app: &AppHandle) -> Result<(), String> {
    let env_path = provider_env_path(app)?;
    let contents = std::fs::read_to_string(env_path).unwrap_or_default();
    for provider in ["groq", "openrouter", "gemini"] {
        let (plural, _) = provider_variables(provider)?;
        let mut keys = file_provider_keys(&contents, provider)?;
        for key in inherited_provider_keys(provider)? {
            if !keys.contains(&key) {
                keys.push(key);
            }
        }
        if !keys.is_empty() {
            command.env(plural, keys.join(","));
        }
    }
    Ok(())
}

fn spawn_core(app: AppHandle, state: Arc<CoreState>) -> Result<(), String> {
    if let Ok(mut last_spawn_attempt) = state.last_spawn_attempt.lock() {
        *last_spawn_attempt = Some(Instant::now());
    }
    let mut command = build_core_command(&app)?;
    apply_provider_environment(&mut command, &app)?;
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
    let core_log = app.path().app_log_dir().ok().and_then(|directory| {
        create_dir_all(&directory).ok()?;
        File::create(directory.join("nova-core.log")).ok()
    });

    let process_id = child.id();
    let generation = state.generation.fetch_add(1, Ordering::AcqRel) + 1;
    {
        let mut guard = state
            .process
            .lock()
            .map_err(|_| "Nova Core process lock is poisoned.".to_owned())?;
        *guard = Some(CoreProcess {
            child,
            stdin,
            started_at: Instant::now(),
        });
    }
    state.connected.store(false, Ordering::Release);
    append_supervisor_log(
        &app,
        &format!("Spawned Nova Core pid={process_id}, generation={generation}."),
    );

    let event_app = app.clone();
    let event_state = state.clone();
    std::thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        let mut bytes = Vec::new();
        loop {
            bytes.clear();
            match reader.read_until(b'\n', &mut bytes) {
                Ok(0) | Err(_) => break,
                Ok(_) => {}
            }
            let line = String::from_utf8_lossy(&bytes);
            let Ok(event) = serde_json::from_str::<Value>(&line) else {
                continue;
            };
            let is_event = event.get("event_type").and_then(Value::as_str).is_some()
                && event.get("payload").is_some();
            if is_event && event_state.generation.load(Ordering::Acquire) == generation {
                if !event_state.connected.swap(true, Ordering::AcqRel) {
                    append_supervisor_log(
                        &event_app,
                        &format!("Core connected, generation={generation}."),
                    );
                    let _ = event_app.emit("nova:connection", true);
                }
                let _ = event_app.emit("nova:event", event);
            }
        }
        if event_state.generation.load(Ordering::Acquire) == generation {
            event_state.connected.store(false, Ordering::Release);
            append_supervisor_log(
                &event_app,
                &format!("Core output closed, generation={generation}."),
            );
            let _ = event_app.emit("nova:connection", false);
        }
    });

    std::thread::spawn(move || {
        let mut core_log = core_log;
        let mut reader = BufReader::new(stderr);
        let mut bytes = Vec::new();
        loop {
            bytes.clear();
            match reader.read_until(b'\n', &mut bytes) {
                Ok(0) | Err(_) => break,
                Ok(_) => {}
            }
            let line = String::from_utf8_lossy(&bytes);
            let line = line.trim_end_matches(['\r', '\n']);
            eprintln!("[Nova Core] {line}");
            if let Some(log) = core_log.as_mut() {
                let _ = writeln!(log, "{line}");
            }
        }
    });

    Ok(())
}

fn claim_restart(state: &Arc<CoreState>) -> bool {
    let Ok(mut last_attempt) = state.last_spawn_attempt.lock() else {
        return false;
    };
    if last_attempt
        .map(|attempt| attempt.elapsed() < CORE_RESTART_COOLDOWN)
        .unwrap_or(false)
    {
        return false;
    }
    *last_attempt = Some(Instant::now());
    true
}

fn append_supervisor_log(app: &AppHandle, message: &str) {
    let Ok(directory) = app.path().app_log_dir() else {
        return;
    };
    if create_dir_all(&directory).is_err() {
        return;
    }
    let Ok(mut log) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(directory.join("nova-desktop.log"))
    else {
        return;
    };
    let _ = writeln!(log, "{message}");
}

fn stop_core(state: &Arc<CoreState>) {
    state.connected.store(false, Ordering::Release);
    state.generation.fetch_add(1, Ordering::AcqRel);
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
            nova_configure_provider,
            nova_list_provider_keys,
            nova_add_provider_key,
            nova_remove_provider_key
        ])
        .setup(move |app| {
            if let Some(window) = app.get_webview_window("main") {
                let icon = tauri::image::Image::from_bytes(include_bytes!(
                    "../icons/icon.png"
                ))?;
                window.set_icon(icon)?;
            }
            let app_handle = app.handle().clone();
            if let Err(error) = spawn_core(app_handle.clone(), state_for_setup.clone()) {
                eprintln!("[Nova Desktop] {error}");
            }
            let watchdog_state = state_for_setup.clone();
            std::thread::spawn(move || {
                while !watchdog_state.shutting_down.load(Ordering::Acquire) {
                    std::thread::sleep(Duration::from_secs(2));
                    ensure_core_running(&app_handle, &watchdog_state);
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Nova desktop");

    app.run(move |_app_handle, event| {
        if matches!(
            event,
            tauri::RunEvent::Exit | tauri::RunEvent::ExitRequested { .. }
        ) {
            core_state.shutting_down.store(true, Ordering::Release);
            stop_core(&core_state);
        }
    });
}

#[cfg(test)]
mod tests {
    use super::{file_provider_keys, key_hint, split_key_list};

    #[test]
    fn provider_key_hint_keeps_only_safe_edges() {
        let key = "sk-or-v1-private-middle-A7x2";
        let hint = key_hint(key);

        assert_eq!(hint, "sk-or-v1-p••••••••A7x2");
        assert!(!hint.contains("rivate-middle"));
    }

    #[test]
    fn provider_key_list_is_unbounded_and_deduplicated() {
        let value = (1..=25)
            .map(|index| format!("test-key-{index:02}"))
            .collect::<Vec<_>>()
            .join(",");
        let keys = split_key_list(&value);

        assert_eq!(keys.len(), 25);
        assert_eq!(keys[0], "test-key-01");
        assert_eq!(keys[24], "test-key-25");
    }

    #[test]
    fn plural_and_legacy_provider_keys_are_merged() {
        let contents = concat!(
            "GROQ_API_KEYS=groq-key-one,groq-key-two\n",
            "GROQ_API_KEY=groq-key-one\n",
            "GROQ_API_KEY_37=groq-key-thirty-seven\n",
            "OPENROUTER_API_KEYS=openrouter-key\n",
        );

        let groq = file_provider_keys(contents, "groq").unwrap();
        let openrouter = file_provider_keys(contents, "openrouter").unwrap();

        assert_eq!(
            groq,
            vec!["groq-key-one", "groq-key-two", "groq-key-thirty-seven"]
        );
        assert_eq!(openrouter, vec!["openrouter-key"]);
    }
}
