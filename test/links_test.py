"""The launcher's search for links that leave the vault (linked_out_of_vault in ignis/ignis_native.py).

Run:  python -I ignis/test/links_test.py  (in a clone of ignis-control: python -I test/links_test.py)

Builds a vault in a temporary folder with junctions pointing in and out of it, and checks which ones are reported.
Junctions are used throughout: making one needs no privilege, while a symbolic link needs an administrator, so the
symbolic-link case is only checked when this runs with that privilege (it is reported either way).
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ignis_native as n  # noqa: E402

failures: list[str] = []


def check(what: str, got: object, want: object) -> None:
    if got != want:
        failures.append(what)
        print(f"  FAILED {what}: got {got!r}, wanted {want!r}")
    else:
        print(f"  ok {what}")


def junction(link: Path, target: Path) -> bool:
    """A junction, through the Windows API as the launcher's setup does (no command line is parsed)."""
    import _winapi
    try:
        _winapi.CreateJunction(str(target), str(link))
        return True
    except OSError as e:
        print(f"  (could not make a junction: {e})")
        return False


def symlink(link: Path, target: Path) -> bool:
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        return False  # needs SeCreateSymbolicLink: an administrator


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="ignis-links-"))
    real_vault = n.VAULT
    try:
        vault = work / "vault"
        outside = work / "outside"
        (vault / "notes" / "deep").mkdir(parents=True)
        (vault / "notes" / "deep" / "note.md").write_text("a note", encoding="utf-8")
        outside.mkdir()
        (outside / "secret.md").write_text("not the vault's", encoding="utf-8")
        (vault / "inside-target").mkdir()

        n.VAULT = vault  # the search reads this

        print("a vault with no links at all")
        check("nothing reported", n.linked_out_of_vault(), [])

        print("\na junction pointing out of the vault")
        if junction(vault / "linked-away", outside):
            check("reported", n.linked_out_of_vault(), ["/linked-away"])
            check("the real folder beside it is not", "/notes" in n.linked_out_of_vault(), False)

        print("\na junction pointing inside the vault (which Ignis can serve)")
        if junction(vault / "linked-within", vault / "inside-target"):
            check("not reported", n.linked_out_of_vault(), ["/linked-away"])

        print("\na junction a few folders down")
        if junction(vault / "notes" / "deep" / "away", outside):
            check("reported with its path", n.linked_out_of_vault(),
                  ["/linked-away", "/notes/deep/away"])

        print("\na broken link, whose target has been removed since")
        # CreateJunction refuses a target that is not there, so the target is made, linked to, then removed.
        going = outside / "going"
        going.mkdir()
        broken = vault / "broken"
        if junction(broken, going):
            shutil.rmtree(going)
            check("the target is really gone", going.exists(), False)
            check("reported rather than raising", "/broken" in n.linked_out_of_vault(), True)

        print("\na symbolic link (needs an administrator to make)")
        if symlink(vault / "sym-away", outside):
            check("reported like a junction", "/sym-away" in n.linked_out_of_vault(), True)
        else:
            print("  skipped: making a symbolic link needs an administrator, and this is not one")

        print("\nhow deep the search goes")
        far = vault / "a" / "b" / "c" / "d" / "e"
        far.mkdir(parents=True)
        if junction(far / "away", outside):
            check(f"a link deeper than {n.LINK_SEARCH_DEPTH} folders is left alone",
                  "/a/b/c/d/e/away" in n.linked_out_of_vault(), False)

        print("\nnothing leaves the search (a link is never followed)")
        if junction(vault / "loop", vault):
            found = n.linked_out_of_vault()
            check("a link to the vault itself is not reported", "/loop" in found, False)
    finally:
        n.VAULT = real_vault
        shutil.rmtree(work, ignore_errors=True)

    print(f"\n{'FAILED: ' + '; '.join(failures) if failures else 'all checks passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
