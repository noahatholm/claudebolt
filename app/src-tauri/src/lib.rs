//! Thin native shell: starts the local Python engine, hands the UI its port + token, and kills the
//! engine on exit. No business logic lives here.
use serde::{Deserialize, Serialize};
use std::{
    io::{BufRead, BufReader},
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::Duration,
};
use tauri::{Manager, RunEvent, State};

#[derive(Clone, Serialize, Deserialize)]
struct EngineInfo {
    port: u16,
    token: String,
}

#[derive(Default)]
struct Engine {
    info: Mutex<Option<EngineInfo>>,
    child: Mutex<Option<Child>>,
    stopping: Mutex<bool>,
}

#[tauri::command]
fn engine_info(state: State<Arc<Engine>>) -> Option<EngineInfo> {
    state.info.lock().unwrap().clone()
}

/// Release: the frozen engine folder is installed as a resource at `<app dir>/engine/`.
/// Debug: `uv run` the engine project in the repo. `CLAUDEBOLT_ENGINE_CMD` overrides both.
fn engine_command() -> Command {
    if let Ok(custom) = std::env::var("CLAUDEBOLT_ENGINE_CMD") {
        let mut parts = custom.split_whitespace();
        let mut c = Command::new(parts.next().unwrap_or("claudebolt"));
        c.args(parts).args(["serve", "--port", "0"]);
        return c;
    }
    if !cfg!(debug_assertions) {
        if let Ok(exe) = std::env::current_exe() {
            let name = if cfg!(windows) { "claudebolt-engine.exe" } else { "claudebolt-engine" };
            let sibling = exe.with_file_name("engine").join(name);
            if sibling.exists() {
                let mut c = Command::new(sibling);
                c.args(["serve", "--port", "0"]);
                return c;
            }
        }
    }
    let project = concat!(env!("CARGO_MANIFEST_DIR"), "/../../engine");
    let mut c = Command::new("uv");
    c.args(["run", "--project", project, "claudebolt", "serve", "--port", "0"]);
    c
}

fn supervise(engine: Arc<Engine>) {
    thread::spawn(move || {
        let mut delay = 500u64;
        loop {
            if *engine.stopping.lock().unwrap() {
                break;
            }
            let mut cmd = engine_command();
            cmd.stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null());
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
            }
            match cmd.spawn() {
                Ok(mut child) => {
                    let stdout = child.stdout.take();
                    *engine.child.lock().unwrap() = Some(child);
                    if let Some(out) = stdout {
                        let eng = engine.clone();
                        // first line = {"port":N,"token":"..."}; keep draining so the pipe never fills
                        thread::spawn(move || {
                            let mut first = true;
                            for line in BufReader::new(out).lines().map_while(Result::ok) {
                                if first {
                                    first = false;
                                    if let Ok(i) = serde_json::from_str::<EngineInfo>(line.trim()) {
                                        *eng.info.lock().unwrap() = Some(i);
                                    }
                                }
                            }
                        });
                    }
                    loop {
                        thread::sleep(Duration::from_millis(300));
                        if *engine.stopping.lock().unwrap() {
                            return;
                        }
                        let mut guard = engine.child.lock().unwrap();
                        match guard.as_mut().map(|c| c.try_wait()) {
                            Some(Ok(None)) => continue,
                            _ => break,
                        }
                    }
                    *engine.info.lock().unwrap() = None; // crashed: the UI reconnects after restart
                    delay = (delay * 2).min(8000);
                }
                Err(_) => delay = (delay * 2).min(8000),
            }
            thread::sleep(Duration::from_millis(delay));
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let engine = Arc::new(Engine::default());
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(engine.clone())
        .invoke_handler(tauri::generate_handler![engine_info])
        .setup({
            let engine = engine.clone();
            move |_app| {
                supervise(engine.clone());
                Ok(())
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building claudebolt");

    app.run(move |handle, event| {
        if let RunEvent::Exit = event {
            let eng = handle.state::<Arc<Engine>>();
            *eng.stopping.lock().unwrap() = true;
            if let Some(mut child) = eng.child.lock().unwrap().take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    });
}
