use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::Manager;

struct BridgeProcess(Mutex<Option<Child>>);

fn find_python() -> String {
    let candidates = [
        "/opt/homebrew/bin/python3.11",
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
        "python3",
    ];
    for c in &candidates {
        if Command::new(c)
            .arg("--version")
            .output()
            .is_ok()
        {
            return c.to_string();
        }
    }
    "python3".to_string()
}

fn find_bridge_script(app: &tauri::AppHandle) -> String {
    // Production: bundled resource
    if let Ok(rc) = app.path().resource_dir() {
        let bundled = rc.join("bridge.py");
        if bundled.exists() {
            return bundled.to_string_lossy().to_string();
        }
    }
    // Dev: project root
    if let Ok(meta) = std::fs::metadata("bridge.py") {
        if meta.is_file() {
            return "bridge.py".to_string();
        }
    }
    let cwd = std::env::current_dir().unwrap_or_default().join("bridge.py");
    if cwd.exists() {
        return cwd.to_string_lossy().to_string();
    }
    eprintln!("WARNING: bridge.py not found, assuming 'bridge.py' in PATH");
    "bridge.py".to_string()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let python = find_python();
            let script = find_bridge_script(app.handle());
            let hermes_agent_path = std::env::var("HERMES_AGENT_PATH")
                .unwrap_or_else(|_| {
                    dirs::home_dir()
                        .map(|p| p.join(".hermes/hermes-agent"))
                        .unwrap_or_default()
                        .to_string_lossy()
                        .to_string()
                });

            println!("Starting bridge: {} {} (agent: {})", python, script, hermes_agent_path);

            let child = Command::new(&python)
                .arg("-u")
                .arg(&script)
                .env("PYTHONIOENCODING", "utf-8")
                .env("PYTHONPATH", &hermes_agent_path)
                .env("HERMES_CONFIG_HOME", std::env::var("HERMES_CONFIG_HOME").unwrap_or_else(|_| {
                    dirs::home_dir().map(|p| p.join(".hermes")).unwrap_or_default().to_string_lossy().to_string()
                }))
                .stdout(std::process::Stdio::inherit())
                .stderr(std::process::Stdio::inherit())
                .spawn();

            match child {
                Ok(c) => {
                    println!("Bridge started (PID: {})", c.id());
                    app.manage(BridgeProcess(Mutex::new(Some(c))));
                }
                Err(e) => {
                    eprintln!("Failed to start bridge: {}", e);
                    app.manage(BridgeProcess(Mutex::new(None)));
                }
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.try_state::<BridgeProcess>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(mut child) = guard.take() {
                            println!("Stopping bridge (PID: {})...", child.id());
                            let _ = child.kill();
                            let _ = child.wait();
                            println!("Bridge stopped");
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
