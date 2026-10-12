import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Every test gets its own empty, seeded database file."""
    db.set_db_path(tmp_path / "test.db")
    db.init_db()
    yield
