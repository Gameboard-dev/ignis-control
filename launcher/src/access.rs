//! The vault's access repair: every file and folder of the vault must carry the sandbox's (the AppContainer's) rule,
//! which they inherit from the vault's folder. A file moved in from elsewhere keeps the access list it had, and Ignis
//! cannot open it (EPERM). This finds such items and makes each inherit from its folder again, as
//! `icacls <item> /reset` would; `watch` does it as items arrive (ReadDirectoryChangesW), after one full scan.
//!
//! Links are never followed, entered or changed: a symbolic link or junction in the vault that points elsewhere must
//! not get its target's access list replaced. The scan skips reparse points, and the repair opens each item without
//! following links (FILE_FLAG_OPEN_REPARSE_POINT), refuses it if it is itself a link, and changes the access list
//! through that handle, so an item swapped for a link between the scan and the repair cannot redirect the change.
//! (The same design as ignis_native.py's lacking_grant/reinherit, tested 2026-10-27.)

use std::ffi::c_void;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::time::Duration;

use windows_sys::Win32::Foundation::{CloseHandle, LocalFree, HANDLE, INVALID_HANDLE_VALUE};
use windows_sys::Win32::Security::Authorization::{ConvertStringSidToSidW, GetNamedSecurityInfoW, SetSecurityInfo, SE_FILE_OBJECT};
use windows_sys::Win32::Security::{EqualSid, GetAce, InitializeAcl, ACL, ACL_REVISION, DACL_SECURITY_INFORMATION, PSID, UNPROTECTED_DACL_SECURITY_INFORMATION};
use windows_sys::Win32::Storage::FileSystem::{
    CreateFileW, GetFileInformationByHandle, ReadDirectoryChangesW, BY_HANDLE_FILE_INFORMATION, FILE_ACTION_ADDED, FILE_ACTION_MODIFIED,
    FILE_ACTION_RENAMED_NEW_NAME, FILE_ATTRIBUTE_REPARSE_POINT, FILE_FLAG_BACKUP_SEMANTICS, FILE_FLAG_OPEN_REPARSE_POINT, FILE_LIST_DIRECTORY,
    FILE_NOTIFY_CHANGE_DIR_NAME, FILE_NOTIFY_CHANGE_FILE_NAME, FILE_NOTIFY_CHANGE_SECURITY, FILE_SHARE_DELETE, FILE_SHARE_READ, FILE_SHARE_WRITE,
    OPEN_EXISTING, READ_CONTROL, WRITE_DAC,
};

fn wide(p: &Path) -> Vec<u16> {
    p.as_os_str().encode_wide().chain(Some(0)).collect()
}

/// A SID from its string form (S-1-15-2-…), freed when dropped.
pub struct Sid(PSID);

impl Sid {
    pub fn parse(s: &str) -> Result<Sid, String> {
        let w: Vec<u16> = s.encode_utf16().chain(Some(0)).collect();
        let mut sid: PSID = std::ptr::null_mut();
        // SAFETY: w is a NUL-terminated string; sid receives a LocalAlloc'd SID, freed in Drop
        if unsafe { ConvertStringSidToSidW(w.as_ptr(), &mut sid) } == 0 {
            return Err(format!("{s} is not a SID ({})", std::io::Error::last_os_error()));
        }
        Ok(Sid(sid))
    }
}

impl Drop for Sid {
    fn drop(&mut self) {
        // SAFETY: allocated by ConvertStringSidToSidW
        unsafe { LocalFree(self.0) };
    }
}

/// An open handle, closed when dropped.
struct Handle(HANDLE);

impl Drop for Handle {
    fn drop(&mut self) {
        // SAFETY: a handle CreateFileW returned
        unsafe { CloseHandle(self.0) };
    }
}

/// Whether a path is a symbolic link, junction or other reparse point (or cannot be read: left alone too).
pub fn is_link(p: &Path) -> bool {
    std::fs::symlink_metadata(p).map_or(true, |m| m.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0)
}

/// Whether an item's access list has a rule for `sid`. None: it could not be read (gone since it was listed).
pub fn has_rule(p: &Path, sid: &Sid) -> Option<bool> {
    let w = wide(p);
    let mut dacl: *mut ACL = std::ptr::null_mut();
    let mut sd: *mut c_void = std::ptr::null_mut();
    // SAFETY: out-pointers to locals; sd is LocalFree'd below and dacl points into it
    let rc = unsafe {
        GetNamedSecurityInfoW(w.as_ptr(), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, std::ptr::null_mut(), std::ptr::null_mut(), &mut dacl, std::ptr::null_mut(), &mut sd)
    };
    if rc != 0 {
        return None;
    }
    let mut found = dacl.is_null(); // no access list at all: everyone may open it
    if !dacl.is_null() {
        // SAFETY: dacl is a valid ACL inside sd
        let count = unsafe { (*dacl).AceCount } as u32;
        for i in 0..count {
            let mut ace: *mut c_void = std::ptr::null_mut();
            // SAFETY: i < AceCount
            if unsafe { GetAce(dacl, i, &mut ace) } == 0 || ace.is_null() {
                continue;
            }
            // header (type, flags, size: 4 bytes), access mask (4), then the SID, for the allowed and denied types
            // SAFETY: an ACE is at least its header long
            let kind = unsafe { *(ace as *const u8) };
            if matches!(kind, 0 | 1 | 9 | 10) {
                // SAFETY: these types hold the SID at offset 8
                let ace_sid = unsafe { (ace as *mut u8).add(8) } as PSID;
                // SAFETY: both are valid SIDs
                if unsafe { EqualSid(ace_sid, sid.0) } != 0 {
                    found = true;
                    break;
                }
            }
        }
    }
    // SAFETY: allocated by GetNamedSecurityInfoW
    unsafe { LocalFree(sd) };
    Some(found)
}

/// Replace an item's access list with what it inherits from its folder (an empty, unprotected list, which Windows
/// fills with the inherited rules), through a handle opened without following links; refused for a link.
pub fn reinherit(p: &Path) -> Result<(), String> {
    let w = wide(p);
    // SAFETY: w is NUL-terminated; the handle is closed by Handle's Drop
    let h = unsafe {
        CreateFileW(
            w.as_ptr(),
            WRITE_DAC | READ_CONTROL,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            std::ptr::null(),
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
            std::ptr::null_mut(),
        )
    };
    if h == INVALID_HANDLE_VALUE {
        return Err(format!("cannot open it ({})", std::io::Error::last_os_error()));
    }
    let h = Handle(h);
    let mut info: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    // SAFETY: a valid handle and an out-struct
    if unsafe { GetFileInformationByHandle(h.0, &mut info) } == 0 {
        return Err(format!("cannot read it ({})", std::io::Error::last_os_error()));
    }
    if info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        return Err("it is a link: not changed".into());
    }
    let mut acl: ACL = unsafe { std::mem::zeroed() };
    // SAFETY: an ACL with room for its header only (no rules)
    if unsafe { InitializeAcl(&mut acl, std::mem::size_of::<ACL>() as u32, ACL_REVISION) } == 0 {
        return Err(format!("cannot make an empty access list ({})", std::io::Error::last_os_error()));
    }
    // SAFETY: a valid handle opened with WRITE_DAC and a valid ACL
    let rc = unsafe { SetSecurityInfo(h.0, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION | UNPROTECTED_DACL_SECURITY_INFORMATION, std::ptr::null_mut(), std::ptr::null_mut(), &acl, std::ptr::null()) };
    if rc != 0 {
        return Err(format!("cannot change its access list ({})", std::io::Error::from_raw_os_error(rc as i32)));
    }
    Ok(())
}

/// What a scan found and did.
#[derive(Debug, Default)]
pub struct Report {
    pub entries: usize,
    pub repaired: Vec<PathBuf>,
    /// Items lacking the rule that could not be repaired, with why.
    pub failed: Vec<(PathBuf, String)>,
}

impl Report {
    pub fn json(&self, event: &str, root: &Path) -> String {
        let rel = |p: &PathBuf| p.strip_prefix(root).unwrap_or(p).to_string_lossy().replace('\\', "/");
        serde_json::json!({
            "event": event,
            "entries": self.entries,
            "repaired": self.repaired.len(),
            "repaired_first": self.repaired.iter().take(20).map(rel).collect::<Vec<_>>(),
            "failed": self.failed.len(),
            "failed_first": self.failed.iter().take(5).map(|(p, why)| format!("{}: {why}", rel(p))).collect::<Vec<_>>(),
        })
        .to_string()
    }
}

/// Every item under `dir` (and `dir` itself if `with_root`), links skipped and not entered; each lacking the rule is
/// repaired unless `check_only`.
pub fn scan(dir: &Path, sid: &Sid, check_only: bool, with_root: bool) -> Report {
    let mut r = Report::default();
    let mut stack = vec![dir.to_path_buf()];
    if with_root {
        visit(dir, sid, check_only, &mut r);
    }
    while let Some(d) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&d) else { continue };
        for e in entries.flatten() {
            let p = e.path();
            if is_link(&p) {
                continue;
            }
            visit(&p, sid, check_only, &mut r);
            if e.file_type().is_ok_and(|t| t.is_dir()) {
                stack.push(p);
            }
        }
    }
    r
}

fn visit(p: &Path, sid: &Sid, check_only: bool, r: &mut Report) {
    r.entries += 1;
    if has_rule(p, sid) != Some(false) {
        return;
    }
    if check_only {
        r.failed.push((p.to_path_buf(), "lacks the rule".into()));
        return;
    }
    match reinherit(p) {
        // the folder's rules may not reach it (a protected folder above): say so rather than count it repaired
        Ok(()) if has_rule(p, sid) == Some(true) => r.repaired.push(p.to_path_buf()),
        Ok(()) => r.failed.push((p.to_path_buf(), "inherits again, but its folder does not give the rule either".into())),
        Err(why) => r.failed.push((p.to_path_buf(), why)),
    }
}

/// One full scan and repair, then the items that arrive (created, moved or renamed in) or whose access list changes,
/// checked as Windows reports them; a lost batch of reports (overflow) means a full scan again. `out` gets one JSON
/// line per scan or repair; never returns unless the vault's folder cannot be watched.
pub fn watch(vault: &Path, sid: &Sid, mut out: impl FnMut(String)) -> Result<(), String> {
    out(scan(vault, sid, false, false).json("scan", vault));
    let w = wide(vault);
    // SAFETY: w is NUL-terminated; the handle is closed by Handle's Drop
    let h = unsafe {
        CreateFileW(w.as_ptr(), FILE_LIST_DIRECTORY, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, std::ptr::null(), OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, std::ptr::null_mut())
    };
    if h == INVALID_HANDLE_VALUE {
        return Err(format!("cannot watch {} ({})", vault.display(), std::io::Error::last_os_error()));
    }
    let h = Handle(h);
    let mut buf = vec![0u64; 8192]; // 64 KB, 8-byte aligned (the records are DWORD-aligned)
    let filter = FILE_NOTIFY_CHANGE_FILE_NAME | FILE_NOTIFY_CHANGE_DIR_NAME | FILE_NOTIFY_CHANGE_SECURITY;
    let mut pending: Vec<PathBuf> = Vec::new();
    loop {
        let mut got = 0u32;
        // SAFETY: a directory handle, a buffer of the stated size, synchronous (no OVERLAPPED)
        let ok = unsafe {
            ReadDirectoryChangesW(h.0, buf.as_mut_ptr() as *mut c_void, (buf.len() * 8) as u32, 1, filter, &mut got, std::ptr::null_mut(), None)
        };
        if ok == 0 {
            return Err(format!("watching {} stopped ({})", vault.display(), std::io::Error::last_os_error()));
        }
        if got == 0 {
            // more changes than the buffer held: look at everything again
            out(scan(vault, sid, false, false).json("rescan", vault));
            pending.clear();
            continue;
        }
        let bytes = unsafe { std::slice::from_raw_parts(buf.as_ptr() as *const u8, got as usize) };
        let mut at = 0usize;
        loop {
            let next = u32::from_le_bytes(bytes[at..at + 4].try_into().unwrap()) as usize;
            let action = u32::from_le_bytes(bytes[at + 4..at + 8].try_into().unwrap());
            let len = u32::from_le_bytes(bytes[at + 8..at + 12].try_into().unwrap()) as usize;
            let name: Vec<u16> = bytes[at + 12..at + 12 + len].chunks_exact(2).map(|c| u16::from_le_bytes([c[0], c[1]])).collect();
            if matches!(action, FILE_ACTION_ADDED | FILE_ACTION_RENAMED_NEW_NAME | FILE_ACTION_MODIFIED) {
                let rel = String::from_utf16_lossy(&name);
                // a name Windows reports is relative to the vault; nothing climbs out of it
                if !rel.split(['\\', '/']).any(|c| c == "..") {
                    pending.push(vault.join(rel));
                }
            }
            if next == 0 {
                break;
            }
            at += next;
        }
        // the reports Windows gave together (a folder copied in comes as one or a few batches), each item once; a
        // moment's pause first, so a file still being written is complete
        std::thread::sleep(Duration::from_millis(200));
        pending.sort();
        pending.dedup();
        let mut r = Report::default();
        for p in pending.drain(..) {
            if is_link(&p) {
                continue;
            }
            if p.is_dir() {
                let sub = scan(&p, sid, false, true);
                r.entries += sub.entries;
                r.repaired.extend(sub.repaired);
                r.failed.extend(sub.failed);
            } else {
                visit(&p, sid, false, &mut r);
            }
        }
        if !r.repaired.is_empty() || !r.failed.is_empty() {
            out(r.json("repaired", vault));
        }
    }
}
