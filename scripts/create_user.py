"""Create a staff user for the admin site (asks for the details in the terminal)."""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import db  # noqa: E402

if __name__ == "__main__":
    db.init_db()
    username = input("Username: ").strip()
    full_name = input("Full name: ").strip()
    password = getpass.getpass("Password (min 6 chars): ")
    if password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    try:
        db.create_user(username, password, full_name)
    except db.ValidationError as e:
        sys.exit(str(e))
    print(f"User '{username}' created.")
