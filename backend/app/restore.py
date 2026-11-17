"""B9 · Bring data back from a backup. See docs/backup-restore.md for when and how.

    python -m app.restore list                 the backups on this server, newest first
    python -m app.restore test [FILE]          check a backup (default: the newest) — changes nothing
    python -m app.restore apply FILE --yes     replace the database with FILE (STOP the server first)

Uses the same settings as the server (DATABASE_PATH, BACKUP_DIR, DB_ENCRYPTION_KEY, AUDIT_SECRET / JWT_SECRET).
"""
import hashlib
import sys

from .config import Settings
from .services import data_protection


def main(argv: list[str]) -> int:
    s = Settings()
    key = s.db_encryption_key or None
    secret = s.audit_secret or hashlib.sha256(f"audit|{s.jwt_secret}".encode()).hexdigest()
    cmd = argv[0] if argv else "help"
    if cmd == "list":
        files = data_protection.list_backups(s.backup_dir)
        if not files:
            print(f"No backups in {s.backup_dir}")
        for f in files:
            print(f"{f['file']}  {f['bytes'] // 1024} KB")
        return 0
    if cmd == "test":
        files = data_protection.list_backups(s.backup_dir)
        name = argv[1] if len(argv) > 1 else (files[0]["file"] if files else "")
        if not name:
            print("No backups yet")
            return 1
        r = data_protection.check_backup(data_protection.backup_path(s.backup_dir, name), key, secret)
        print(("OK  " if r["ok"] else "FAILED  ") + r["file"])
        for t, n in r["rows"].items():
            print(f"  {t}: {n} rows")
        for p in r["problems"]:
            print("  problem: " + p)
        return 0 if r["ok"] else 1
    if cmd == "apply":
        if len(argv) < 2 or "--yes" not in argv:
            print("Usage: python -m app.restore apply FILE --yes   (stop the server first)")
            return 2
        path = data_protection.backup_path(s.backup_dir, argv[1])
        keep = data_protection.restore_apply(s.database_path, path, key)
        print(f"Restored {argv[1]} into {s.database_path}")
        if keep:
            print(f"The database from before the restore is kept at {keep}")
        print("Now start the server again.")
        return 0
    print(__doc__)
    return 0 if cmd == "help" else 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except data_protection.DataError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
