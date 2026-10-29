//! The access repair on a temporary folder, with SYSTEM (S-1-5-18) as the "sandbox": a file whose inherited rules were
//! removed lacks it and is repaired; a junction to a protected folder outside is neither entered nor changed; `watch`
//! repairs a file moved in while it runs. icacls and mklink set the scene (argument lists, no shell strings).
#![cfg(windows)]

use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

const SYSTEM: &str = "S-1-5-18";
const EXE: &str = env!("CARGO_BIN_EXE_ignis-launcher");

/// The current user's SID, for icacls (`*S-1-5-21-…`; a name can be ambiguous, as when the computer has the user's name).
fn my_sid() -> String {
    let out = Command::new("whoami.exe").args(["/user", "/fo", "csv", "/nh"]).output().unwrap();
    let text = String::from_utf8_lossy(&out.stdout);
    format!("*{}", text.trim().rsplit(',').next().unwrap().trim_matches('"'))
}

fn icacls(p: &Path, args: &[&str]) {
    let me = my_sid();
    let mut c = Command::new("icacls");
    c.arg(p);
    for a in args {
        c.arg(a.replace("{me}", &me));
    }
    assert!(c.stdout(Stdio::null()).status().unwrap().success(), "icacls {args:?}");
}

/// Only the current user's rule, nothing inherited: SYSTEM is not in it.
fn strip(p: &Path) {
    icacls(p, &["/inheritance:r", "/grant:r", if p.is_dir() { "{me}:(OI)(CI)F" } else { "{me}:F" }]);
}

fn lacks_system(p: &Path) -> bool {
    let out = Command::new("icacls").arg(p).output().unwrap();
    !String::from_utf8_lossy(&out.stdout).contains("NT AUTHORITY\\SYSTEM")
}

fn run(cmd: &str, vault: &Path) -> serde_json::Value {
    let out = Command::new(EXE).args(["access", cmd, "--vault"]).arg(vault).args(["--sid", SYSTEM]).output().unwrap();
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    serde_json::from_slice(&out.stdout).unwrap()
}

fn fresh(name: &str) -> PathBuf {
    let d = Path::new(env!("CARGO_TARGET_TMPDIR")).join(format!("{name}-{}", std::process::id()));
    _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

#[test]
fn repairs_and_leaves_links_alone() {
    let root = fresh("access");
    let vault = root.join("vault");
    let outside = root.join("outside");
    std::fs::create_dir_all(vault.join("notes")).unwrap();
    std::fs::create_dir_all(&outside).unwrap();
    let note = vault.join("notes").join("moved in.md");
    std::fs::write(&note, "x").unwrap();
    strip(&note);
    strip(&outside);
    assert!(lacks_system(&note) && lacks_system(&outside) && !lacks_system(&vault));
    let ok = Command::new("cmd").args(["/c", "mklink", "/J"]).arg(vault.join("link")).arg(&outside).output().unwrap();
    assert!(ok.status.success(), "{:?} {} {}", vault, String::from_utf8_lossy(&ok.stdout), String::from_utf8_lossy(&ok.stderr));

    let check = run("check", &vault);
    assert_eq!(check["failed"], 1, "{check}"); // the note; the junction is skipped
    let repair = run("repair", &vault);
    assert_eq!(repair["repaired"], 1, "{repair}");
    assert!(repair["repaired_first"][0].as_str().unwrap().ends_with("notes/moved in.md"));
    assert!(!lacks_system(&note), "the note inherits again");
    assert!(lacks_system(&outside), "the folder the junction points at is unchanged");
    assert_eq!(run("check", &vault)["failed"], 0);
}

#[test]
fn watch_repairs_what_arrives() {
    let root = fresh("watch");
    let vault = root.join("vault");
    std::fs::create_dir_all(&vault).unwrap();
    let mut child = Command::new(EXE).args(["access", "watch", "--vault"]).arg(&vault).args(["--sid", SYSTEM]).stdout(Stdio::piped()).spawn().unwrap();
    // its lines through a channel, so a missing one fails the test instead of hanging it
    let (tx, rx) = std::sync::mpsc::channel();
    let stdout = child.stdout.take().unwrap();
    std::thread::spawn(move || BufReader::new(stdout).lines().map_while(Result::ok).for_each(|l| _ = tx.send(l)));
    let next = || -> serde_json::Value { serde_json::from_str(&rx.recv_timeout(std::time::Duration::from_secs(20)).expect("no line from watch")).unwrap() };
    let first = next();
    assert_eq!(first["event"], "scan");
    // a file made outside with its own access list, moved in (a move keeps the access list)
    let elsewhere = root.join("elsewhere.md");
    std::fs::write(&elsewhere, "y").unwrap();
    strip(&elsewhere);
    std::fs::rename(&elsewhere, vault.join("arrived.md")).unwrap();
    let got = next();
    _ = child.kill();
    assert_eq!(got["event"], "repaired", "{got}");
    assert_eq!(got["repaired_first"][0], "arrived.md");
    assert!(!lacks_system(&vault.join("arrived.md")));
}
