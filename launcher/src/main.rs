//! Ignis's launcher in Rust. Its first part is the vault access repair (access.rs), which ignis/ignis_native.py runs
//! as `ignis-launcher access watch` instead of re-scanning every few minutes; the rest of the launcher follows (the
//! plan: the AppContainer, the processes, the relay, the status file).
//!
//!   ignis-launcher access check  --vault <folder> --sid <S-1-15-2-…>   report what lacks the sandbox's rule
//!   ignis-launcher access repair --vault <folder> --sid <S-1-15-2-…>   repair it once
//!   ignis-launcher access watch  --vault <folder> --sid <S-1-15-2-…>   repair, then repair what arrives, until stopped
//!                                [--exit-with-stdin]                   (or until stdin ends: the launcher's own use)
//!
//! Each prints one JSON line per scan or repair (event, entries, repaired, failed, the first paths); errors go to
//! stderr with exit status 1. No command line is ever built from a string and nothing is run.

#[cfg(windows)]
mod access;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if let Err(e) = run(&args) {
        eprintln!("ignis-launcher: {e}");
        std::process::exit(1);
    }
}

fn value(args: &[String], name: &str) -> Option<String> {
    args.iter().position(|a| a == name).and_then(|i| args.get(i + 1)).cloned()
}

#[cfg(windows)]
fn run(args: &[String]) -> Result<(), String> {
    use std::io::Write;
    let usage = "usage: ignis-launcher access (check|repair|watch) --vault <folder> --sid <S-1-15-2-…>";
    let (Some("access"), Some(cmd)) = (args.first().map(String::as_str), args.get(1).map(String::as_str)) else { return Err(usage.into()) };
    let vault = value(args, "--vault").ok_or(usage)?;
    let sid = access::Sid::parse(&value(args, "--sid").ok_or(usage)?)?;
    let vault = std::fs::canonicalize(&vault).map_err(|e| format!("the vault {vault}: {e}"))?;
    if access::is_link(&vault) {
        return Err(format!("the vault {} is itself a link: not touched", vault.display()));
    }
    let print = |line: String| {
        let mut o = std::io::stdout().lock();
        _ = writeln!(o, "{line}");
        _ = o.flush();
    };
    match cmd {
        "check" => print(access::scan(&vault, &sid, true, false).json("check", &vault)),
        "repair" => print(access::scan(&vault, &sid, false, false).json("scan", &vault)),
        "watch" => {
            // --exit-with-stdin: the launcher holds the other end of stdin; when it ends (the launcher stopped or
            // was killed), so does this, rather than watching on with nobody reading
            if args.iter().any(|a| a == "--exit-with-stdin") {
                std::thread::spawn(|| {
                    _ = std::io::copy(&mut std::io::stdin().lock(), &mut std::io::sink());
                    std::process::exit(0);
                });
            }
            access::watch(&vault, &sid, print)?
        }
        _ => return Err(usage.into()),
    }
    Ok(())
}

#[cfg(not(windows))]
fn run(_: &[String]) -> Result<(), String> {
    Err("Ignis's launcher runs on Windows only (it uses an AppContainer)".into())
}
