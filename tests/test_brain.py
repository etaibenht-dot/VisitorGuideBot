from robot import brain

PLACES = [
    {"id": 1, "name": "מעליות", "aliases": "מעלית", "floor": "0", "directions": "ימינה", "gesture_id": 126},
    {"id": 2, "name": "מזכירות", "aliases": None, "floor": "1", "directions": None, "gesture_id": None},
]


def test_place_tag_with_gesture():
    p = brain.parse_reply("[PLACE:1]\nהמעליות מימין, בסוף המסדרון.")
    assert (p.tag, p.place_id, p.text) == ("PLACE", 1, "המעליות מימין, בסוף המסדרון.")
    a = brain.decide(p, PLACES)
    assert a.gesture_id == 126 and not a.unanswered and "[" not in a.say


def test_place_tag_without_gesture():
    a = brain.decide(brain.parse_reply("[PLACE:2] המזכירות בקומה הראשונה."), PLACES)
    assert a.gesture_id is None and a.say == "המזכירות בקומה הראשונה."


def test_unknown_place_id_becomes_none():
    a = brain.decide(brain.parse_reply("[PLACE:99]\nטקסט"), PLACES)
    assert a.gesture_id is None and a.say == "טקסט" and not a.unanswered


def test_unknown_tag():
    a = brain.decide(brain.parse_reply("[UNKNOWN]\nלא יודע"), PLACES)
    assert a.unanswered and a.say == brain.UNKNOWN_SENTENCE and a.gesture_id is None


def test_none_tag_and_case():
    p = brain.parse_reply("[none]\nשלום!")
    assert p.tag == "NONE" and p.text == "שלום!"


def test_missing_tag_is_none():
    p = brain.parse_reply("שלום, איך אפשר לעזור?")
    assert p.tag == "NONE" and p.text == "שלום, איך אפשר לעזור?"


def test_malformed_tag_is_stripped():
    p = brain.parse_reply("תשובה כלשהי [PLACE:1]")
    assert p.tag == "NONE" and "[" not in p.text


def test_empty_reply_counts_as_unknown():
    assert brain.decide(brain.parse_reply(""), PLACES).unanswered
    assert brain.decide(brain.parse_reply("[NONE]"), PLACES).unanswered


def test_prompt_contains_the_data():
    prompt = brain.build_system_prompt({
        "places": PLACES,
        "knowledge": [{"category_name": "מלגות", "question": "אילו מלגות?", "answer": "ארבעה סוגים."}],
        "events": [{"start_time": "10:00", "end_time": "10:45", "title": "מבוא למערכות מידע", "lecturer": "ד\"ר כהן",
                    "place_id": 1, "place_name": "מעליות", "description": None}],
    })
    for needle in ["1 | מעליות", "ארבעה סוגים", "מבוא למערכות מידע", "[PLACE:", "[UNKNOWN]", "[NONE]"]:
        assert needle in prompt


def test_prompt_with_no_data():
    prompt = brain.build_system_prompt({"places": [], "knowledge": [], "events": []})
    assert "אין אירועים נוספים היום" in prompt


def test_staff_edit_reaches_the_next_question():
    """End to end without hardware: DB -> prompt -> Gemini-style reply -> action."""
    import db
    elevator = next(p for p in db.list_places() if p["name"] == "מעליות")
    db.update_place(elevator["id"], {"name": "מעליות", "directions": "המעליות משמאל, ליד הקפיטריה.",
                                     "gesture_id": "126", "is_active": "on"})
    snapshot = db.robot_snapshot()
    assert "ליד הקפיטריה" in brain.build_system_prompt(snapshot)
    reply = f"[PLACE:{elevator['id']}]\nהמעליות משמאל, ליד הקפיטריה."
    action = brain.decide(brain.parse_reply(reply), snapshot["places"])
    assert action.gesture_id == 126 and action.say == "המעליות משמאל, ליד הקפיטריה."
