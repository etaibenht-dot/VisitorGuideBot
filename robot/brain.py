"""
robot/brain.py -- the robot's "thinking", with no hardware and no network.

1. build_system_prompt(): turns the data from the database into instructions for Gemini.
2. parse_reply(): reads the tag on the first line of Gemini's answer.
3. decide(): turns a parsed reply into what the robot should say and which motion to run.

Everything here is a pure function so it can be unit-tested on any computer.
"""

import re
from dataclasses import dataclass
from typing import Optional

UNKNOWN_SENTENCE = "אין לי מידע על זה. כדאי לפנות למזכירות."

TAG_RE = re.compile(r"^\s*\[(?:(PLACE):(\d+)|(UNKNOWN)|(NONE))\]\s*", re.IGNORECASE)

BASE_INSTRUCTIONS = """אתה המדריך הרובוטי של יום הפתוח במכללה האקדמית תל אביב יפו.
ענה בעברית בלבד, בעד שלושה משפטים קצרים ושיחתיים, כי התשובה תיאמר בקול.
מותר לך לענות רק על סמך המידע שמופיע למטה. אל תמציא פרטים על המכללה, על מקומות או על אירועים.

השורה הראשונה בתשובה חייבת להיות תגית אחת בדיוק, ואחריה בשורה חדשה הטקסט שייאמר:
[PLACE:<מספר>] - כשהתשובה מכוונת את המבקר למקום מהרשימה (כולל המקום של אירוע). המספר הוא מספר המקום מהרשימה.
[UNKNOWN] - כשהמידע למטה לא מכיל תשובה לשאלה.
[NONE] - לכל תשובה אחרת, וגם לשיחת חולין (שלום, מה שלומך וכו').

כשמבקר שואל איפה מקום, תמיד השתמש בתגית PLACE עם מספר המקום, ופעל לפי העמודות "מצביע" ו"הוראות הגעה":
- יש הוראות הגעה: אמור אותן.
- אין הוראות הגעה (מופיע "-") והמקום מסומן "מצביע: כן": אמור רק משפט כמו "<שם המקום> נמצא בכיוון שאני מצביע אליו".
- אין הוראות הגעה והמקום מסומן "מצביע: לא": אמור שאין לך הוראות הגעה מדויקות למקום הזה, ושכדאי לשאול איש צוות שנמצא בסביבה.
לעולם אל תמציא כיוונים, קומות או מרחקים, ואל תגיד שאתה מצביע כשהמקום מסומן "מצביע: לא"."""


def _places_block(places) -> str:
    if not places:
        return "מקומות: אין."
    lines = ["מקומות (מספר | שם | שמות נוספים | קומה | מצביע | הוראות הגעה):"]
    for p in places:
        points = "כן" if p.get("gesture_id") else "לא"
        lines.append(
            f"{p['id']} | {p['name']} | {p.get('aliases') or '-'} | {p.get('floor') or '-'} | "
            f"מצביע: {points} | {p.get('directions') or '-'}"
        )
    return "\n".join(lines)


def _knowledge_block(items) -> str:
    if not items:
        return "מאגר ידע: אין."
    lines = ["מאגר ידע:"]
    for k in items:
        cat = f"[{k['category_name']}] " if k.get("category_name") else ""
        lines.append(f"- {cat}{k['question']}: {k['answer']}")
    return "\n".join(lines)


def _events_block(events) -> str:
    if not events:
        return "אירועים היום: אין אירועים נוספים היום."
    lines = ["אירועים היום שעוד לא הסתיימו (שעות | כותרת | מרצה | מספר מקום | שם מקום | תיאור):"]
    for e in events:
        lines.append(
            f"{e['start_time']}-{e['end_time']} | {e['title']} | {e.get('lecturer') or '-'} | "
            f"{e.get('place_id') or '-'} | {e.get('place_name') or '-'} | {e.get('description') or '-'}"
        )
    return "\n".join(lines)


def build_system_prompt(snapshot: dict) -> str:
    """snapshot = db.robot_snapshot(): {'places': [...], 'knowledge': [...], 'events': [...]}"""
    return "\n\n".join([
        BASE_INSTRUCTIONS,
        _places_block(snapshot.get("places", [])),
        _knowledge_block(snapshot.get("knowledge", [])),
        _events_block(snapshot.get("events", [])),
    ])


@dataclass
class Parsed:
    tag: str                 # "PLACE" | "UNKNOWN" | "NONE"
    text: str                # what to say, tag removed
    place_id: Optional[int] = None


def parse_reply(raw: Optional[str]) -> Parsed:
    """Read the tag at the start of Gemini's reply. A missing or broken tag counts as NONE."""
    raw = (raw or "").strip()
    m = TAG_RE.match(raw)
    if not m:
        # Remove any stray tag-looking text so the robot never reads brackets aloud.
        return Parsed("NONE", re.sub(r"\[[A-Za-z]+(?::\d+)?\]", "", raw).strip())
    text = raw[m.end():].strip()
    if m.group(1):
        return Parsed("PLACE", text, int(m.group(2)))
    if m.group(3):
        return Parsed("UNKNOWN", text)
    return Parsed("NONE", text)


@dataclass
class Action:
    say: str
    gesture_id: Optional[int] = None   # robot action group to run while speaking
    unanswered: bool = False           # save the question for the staff


def decide(parsed: Parsed, places) -> Action:
    """Turn a parsed reply into an action. `places` = the active places sent to Gemini."""
    if parsed.tag == "UNKNOWN" or (parsed.tag != "UNKNOWN" and not parsed.text):
        return Action(UNKNOWN_SENTENCE, unanswered=True)
    if parsed.tag == "PLACE":
        place = next((p for p in places if p["id"] == parsed.place_id), None)
        if place is None:           # unknown id -> treat as NONE
            return Action(parsed.text)
        return Action(parsed.text, gesture_id=place.get("gesture_id"))
    return Action(parsed.text)
