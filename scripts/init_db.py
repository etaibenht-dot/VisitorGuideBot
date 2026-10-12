"""Create the database tables and insert the starting data. Safe to run again."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402

if __name__ == "__main__":
    db.init_db()
    print(f"Database ready: {db.get_db_path()}")
