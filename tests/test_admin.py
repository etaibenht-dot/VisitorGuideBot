import pytest
from fastapi.testclient import TestClient

import db
from admin.main import app


@pytest.fixture
def client():
    db.create_user("staff", "secret1", "איש סגל")
    with TestClient(app) as c:
        yield c


def login(c):
    r = c.post("/login", data={"username": "staff", "password": "secret1"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


@pytest.mark.parametrize("path", ["/", "/places", "/places/new", "/knowledge", "/events", "/unanswered", "/users"])
def test_logged_out_redirects_to_login(client, path):
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_static_and_login_page_are_public(client):
    assert client.get("/login").status_code == 200
    assert client.get("/static/pico.min.css").status_code == 200


def test_wrong_password(client):
    r = client.post("/login", data={"username": "staff", "password": "nope"})
    assert r.status_code == 200 and "שגויים" in r.text


def test_all_pages_render_when_logged_in(client):
    login(client)
    for path in ["/", "/places", "/places/new", "/knowledge", "/knowledge/new", "/events", "/events/new",
                 "/unanswered", "/unanswered?show=all", "/users"]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert 'dir="rtl"' in r.text


def test_place_create_edit_delete(client):
    login(client)
    r = client.post("/places/new", data={"name": "מעבדה", "directions": "שמאלה", "gesture_id": "125", "is_active": "on"})
    assert r.status_code == 200 and "נשמר" in r.text
    pid = next(p["id"] for p in db.list_places() if p["name"] == "מעבדה")
    client.post(f"/places/{pid}", data={"name": "מעבדה", "directions": "ימינה", "gesture_id": "", "is_active": "on"})
    p = db.get_place(pid)
    assert p["directions"] == "ימינה" and p["gesture_id"] is None
    client.post(f"/places/{pid}/delete")
    assert db.get_place(pid) is None


def test_duplicate_place_shows_error(client):
    login(client)
    r = client.post("/places/new", data={"name": "מעליות", "is_active": "on"})
    assert "כבר קיים" in r.text


def test_event_end_before_start_shows_error(client):
    login(client)
    r = client.post("/events/new", data={"title": "x", "date": "2026-11-01", "start_time": "11:00", "end_time": "10:00"})
    assert "שעת הסיום" in r.text
    assert db.list_events() == []


def test_add_to_knowledge_from_unanswered(client):
    login(client)
    qid = db.add_unanswered("איפה החניה?")
    r = client.get(f"/knowledge/new?from_unanswered={qid}")
    assert "איפה החניה?" in r.text
    r = client.post("/knowledge/new", data={"question": "איפה החניה?", "answer": "החניה מאחורי הבניין.",
                                            "category_id": "", "is_active": "on", "from_unanswered": str(qid)})
    assert r.status_code == 200
    assert db.get_unanswered(qid)["status"] == "handled"
    assert any(k["question"] == "איפה החניה?" for k in db.list_knowledge())


def test_logout(client):
    login(client)
    client.get("/logout")
    assert client.get("/", follow_redirects=False).status_code == 303
