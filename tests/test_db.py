from datetime import datetime

import pytest

import db


def place_by_name(name):
    return next(p for p in db.list_places() if p["name"] == name)


def test_seed_is_idempotent():
    db.init_db()
    db.init_db()
    assert len(db.list_places()) == 5
    assert len(db.list_knowledge()) == 3
    assert [g["id"] for g in db.list_gestures()] == [124, 125, 126, 127]
    assert place_by_name("מעליות")["gesture_id"] == 126
    assert place_by_name("מזכירות")["gesture_id"] is None


def test_users_and_login():
    uid = db.create_user("ron", "secret1", "רון")
    assert db.authenticate("ron", "secret1")["id"] == uid
    assert db.authenticate("ron", "wrong") is None
    assert db.authenticate("nobody", "secret1") is None
    with pytest.raises(db.ValidationError):
        db.create_user("ron", "another1")
    with pytest.raises(db.ValidationError):
        db.create_user("short", "123")
    db.change_password(uid, "newpass1")
    assert db.authenticate("ron", "newpass1")


def test_place_crud_and_rules():
    pid = db.create_place({"name": " מעבדה ", "aliases": "lab,  מעבדת מחשבים ,", "gesture_id": "124", "is_active": "on"})
    p = db.get_place(pid)
    assert p["name"] == "מעבדה" and p["aliases"] == "lab, מעבדת מחשבים" and p["gesture_id"] == 124 and p["is_active"] == 1
    db.update_place(pid, {"name": "מעבדה", "gesture_id": "", "is_active": None})
    p = db.get_place(pid)
    assert p["gesture_id"] is None and p["is_active"] == 0
    assert all(x["id"] != pid for x in db.list_places(active_only=True))
    with pytest.raises(db.ValidationError):
        db.create_place({"name": "מעליות"})          # duplicate name
    with pytest.raises(db.ValidationError):
        db.create_place({"name": "   "})            # empty name
    db.delete_place(pid)
    assert db.get_place(pid) is None


def test_place_in_use_cannot_be_deleted():
    pid = place_by_name("חדר עיון")["id"]
    db.create_event({"title": "הרצאה", "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
                     "place_id": str(pid), "is_active": "on"})
    with pytest.raises(db.ValidationError):
        db.delete_place(pid)


def test_categories_and_knowledge():
    cid = db.create_category("תנאי קבלה")
    kid = db.create_knowledge({"category_id": str(cid), "question": "מה תנאי הקבלה?", "answer": "בגרות ופסיכומטרי.",
                               "is_active": "on"})
    assert db.list_knowledge(category_id=cid)[0]["id"] == kid
    assert db.list_knowledge(search="פסיכומטרי")[0]["id"] == kid
    with pytest.raises(db.ValidationError):
        db.delete_category(cid)                     # not empty
    with pytest.raises(db.ValidationError):
        db.create_knowledge({"question": "רק שאלה"})
    db.update_knowledge(kid, {"category_id": str(cid), "question": "מה תנאי הקבלה?", "answer": "x", "is_active": None})
    assert all(k["id"] != kid for k in db.list_knowledge(active_only=True))
    db.delete_knowledge(kid)
    db.delete_category(cid)


def test_event_validation():
    base = {"title": "א", "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00"}
    with pytest.raises(db.ValidationError):
        db.create_event({**base, "end_time": "09:00"})
    with pytest.raises(db.ValidationError):
        db.create_event({**base, "date": "01/11/2026"})
    with pytest.raises(db.ValidationError):
        db.create_event({**base, "title": ""})


def test_todays_upcoming_events_filter():
    now = datetime(2026, 11, 1, 11, 0)
    mk = lambda title, date, s, e, active="on": db.create_event(
        {"title": title, "date": date, "start_time": s, "end_time": e, "is_active": active})
    mk("ended today", "2026-11-01", "09:00", "10:45")
    mk("running now", "2026-11-01", "10:30", "11:30")
    mk("later today", "2026-11-01", "13:00", "14:00")
    mk("tomorrow", "2026-11-02", "10:00", "11:00")
    mk("yesterday", "2026-10-31", "12:00", "13:00")
    mk("inactive today", "2026-11-01", "15:00", "16:00", active=None)
    titles = [e["title"] for e in db.todays_upcoming_events(now)]
    assert titles == ["running now", "later today"]


def test_unanswered_flow():
    qid = db.add_unanswered("איפה החניה?")
    assert db.list_unanswered(status="new")[0]["id"] == qid
    db.set_unanswered_status(qid, "handled")
    assert db.list_unanswered(status="new") == []
    assert len(db.list_unanswered()) == 1
    db.delete_unanswered(qid)
    assert db.list_unanswered() == []


def test_robot_snapshot_only_active():
    pid = place_by_name("שירותים")["id"]
    db.update_place(pid, {"name": "שירותים", "gesture_id": "124", "is_active": None})
    snap = db.robot_snapshot()
    assert "שירותים" not in [p["name"] for p in snap["places"]]
    assert len(snap["knowledge"]) == 3
