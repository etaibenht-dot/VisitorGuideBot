# Task: Staff admin system + robot integration for VisitorGuideBot

You are working in a fork of `VisitorGuideBot`, a Hebrew-speaking open-day guide robot (Hiwonder TonyBot) for an academic college. Read the whole repo first. This prompt is the full spec. Where something is not specified, choose the **simplest** option and list your choice in `DECISIONS.md` instead of asking.

## Goal

1. A small web admin where college staff manage the data the robot uses: **places**, a **knowledge base**, an **open-day schedule**, and a list of **questions the robot could not answer**.
2. Change the robot code so it answers **only** from that data, and **points** at a place (runs a recorded motion) when it talks about one.

## Hard constraints

- Developed on macOS, **runs on Windows** (the PC connected to the robot). Everything must work on both. Use `pathlib` for paths; no shell-specific commands in Python.
- **Python only** (3.12). No Docker, no Node.js, no npm, no frontend build step, no React.
- **One project, one machine, one SQLite file** (`data/guide.db`). The admin and the robot both use a shared module `db.py` (stdlib `sqlite3`, WAL mode, a new connection per operation). **No HTTP API between them.**
- Admin: **FastAPI + Jinja2 server-rendered HTML**. Styling: **Pico.css saved locally** in `admin/static/` (no CDN, the PC may be offline). All pages `lang="he" dir="rtl"`, all UI text in Hebrew.
- Secrets/config in `.env` (via `python-dotenv`), never committed. Provide `.env.example`.
- Do not modify `firmware/` (Arduino code already flashed on the robot).

## Folder layout (target)

```
admin/            main.py (FastAPI app), templates/, static/pico.min.css
robot/            __init__.py, academy_guide.py (moved from root), robot_motion.py
db.py             all SQL lives here
scripts/          init_db.py, create_user.py
firmware/         tonybot_listener/ (unchanged)
data/             guide.db (gitignored)
tests/            pytest tests
start_admin.bat   start_robot.bat
requirements.txt  .env.example  README.md  DECISIONS.md
```

Run commands (from the project root):
- Admin: `uvicorn admin.main:app --port 8000` → `start_admin.bat`
- Robot: `python -m robot.academy_guide` → `start_robot.bat`
- `.bat` files: activate `.venv` and run the command; keep the window open on error (`pause`).

## `.env` keys

`GEMINI_API_KEY`, `GEMINI_MODEL` (default: the model name already in `academy_guide.py`), `ROBOT_COM_PORT` (default `COM3`), `DB_PATH` (default `data/guide.db`), `SESSION_SECRET`.

## Database (create in `db.py`, called by `scripts/init_db.py`)

| table | columns |
|---|---|
| users | id PK, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, full_name TEXT, created_at |
| gestures | id INTEGER PK (= the robot action-group number), name TEXT NOT NULL |
| places | id PK, name TEXT UNIQUE NOT NULL, aliases TEXT (comma-separated), floor TEXT, directions TEXT, gesture_id INTEGER NULL → gestures, is_active INTEGER DEFAULT 1, updated_at |
| categories | id PK, name TEXT UNIQUE NOT NULL |
| knowledge_items | id PK, category_id → categories, question TEXT NOT NULL, answer TEXT NOT NULL, is_active INTEGER DEFAULT 1, updated_at, updated_by → users NULL |
| events | id PK, title TEXT NOT NULL, description TEXT, lecturer TEXT, date TEXT NOT NULL (YYYY-MM-DD), start_time TEXT NOT NULL (HH:MM), end_time TEXT NOT NULL (HH:MM), place_id → places NULL, is_active INTEGER DEFAULT 1 |
| unanswered_questions | id PK, question_text TEXT NOT NULL, asked_at, status TEXT DEFAULT 'new' ('new' or 'handled') |

`init_db.py` is safe to run again (creates missing tables, inserts seed rows only if absent). Seed:
- gestures: 124 `הצבעה לשירותים`, 125 `הצבעה לחדר עיון`, 126 `הצבעה למעליות`, 127 `הצבעה לחדר סגל`
- places (directions empty): שירותים→124, חדר עיון→125, מעליות→126, חדר סגל→127, מזכירות→no gesture
- categories: מסלולי לימוד, שכר לימוד, מלגות, כללי
- knowledge_items: the three answers currently in `MENU_OPTIONS` in `academy_guide.py`, each in its matching category

`create_user.py`: prompts for username, full name and password (hidden input), stores a bcrypt hash.

## Admin screens

Login required on every page except `/login` (session cookie via Starlette `SessionMiddleware`). Top nav on every page: ראשי · מקומות · מאגר ידע · לוח זמנים · שאלות שלא נענו · משתמשים · יציאה.

| page | URL | content |
|---|---|---|
| Login | `/login` | username, password, Hebrew error message |
| Home | `/` | counts of active places, active knowledge items, today's events; the 5 newest `new` unanswered questions |
| Places | `/places`, `/places/new`, `/places/{id}` | table (name, floor, gesture, active) + form (name, aliases, floor, directions, gesture dropdown incl. "ללא הצבעה", active) |
| Knowledge | `/knowledge`, `/knowledge/new`, `/knowledge/{id}` | table with category filter + text search; form (category, question, answer, active); add/delete categories on the list page |
| Schedule | `/events`, `/events/new`, `/events/{id}` | table sorted by date+time; form (title, description, lecturer, date, start, end, place dropdown, active) |
| Unanswered | `/unanswered` | newest first; buttons: "הוסף למאגר" (opens knowledge form with the question pre-filled and marks it handled on save), "טופל", "מחק" |
| Users | `/users` | list, add user, change own password |

Rules: required fields = place name, knowledge question+answer, event title+date+start+end, end > start. Place and category names unique. Deleting a place used by an event is blocked with a Hebrew message. Every delete asks for confirmation (`confirm()` is fine). After save: flash "נשמר" and return to the list. Inactive rows stay in the DB but the robot ignores them.

## Robot changes (`robot/academy_guide.py`)

Keep as is: face detection, speech-to-text, edge-tts Hebrew voice, exit words.

1. **Motion:** use `robot/robot_motion.py` (provided, `RobotMotion` over USB serial at 115200, protocol `RUN <n>` → `DONE`). Wave = `run_group(9)` on greeting, bow = `run_group(10)` on closing. Delete `wave_via_wondercode.py` and all WonderCode/pyautogui code and the old 9600-baud serial code. If the robot is not connected, everything else must still work (motions are skipped).
2. **Remove** `MENU_OPTIONS` and the menu prompt. New greeting: `שלום! אני המדריך של המכללה. אפשר לשאול אותי על מקומות בבניין, על ההרצאות של היום ועל הלימודים.`
3. **Per question**, read from the DB via `db.py`: active places, active knowledge items, and **active events whose date is today and whose end_time is later than now**.
4. Build the Gemini system prompt from that data (places listed with their numeric id). Instructions: answer in Hebrew, at most 3 short sentences, **only** from the data; the **first line must be exactly one tag**:
   - `[PLACE:<id>]` — the answer directs the visitor to a place (including an event's place)
   - `[UNKNOWN]` — the data does not contain the answer
   - `[NONE]` — any other answer or small talk
5. Parse with a regex on the first line, strip the tag before speaking. Missing/invalid tag or unknown id → `[NONE]`. Gemini or DB error → `[UNKNOWN]`.
6. Act:
   - `[PLACE:id]` with a gesture → speak and point **at the same moment** (see 7). Without a gesture → just speak.
   - `[UNKNOWN]` → speak exactly `אין לי מידע על זה. כדאי לפנות למזכירות.` and insert the question into `unanswered_questions`.
   - `[NONE]` → speak.
7. `speak(text, point_group=None)`: first generate the mp3 with edge-tts, **then** start the motion in a background thread and immediately start playback (so speech and pointing start together). Use the threading approach already in `robot_motion.py`.
8. Put the tag parsing and the DB-to-prompt building in small pure functions so they can be unit-tested.

## Tests (`pytest`, must pass on macOS without the robot, camera or Gemini)

- `db.py`: CRUD for each table, uniqueness, place-in-use delete block, today's-events filter (past event today, future event today, event on another day).
- Tag parser: each tag, missing tag, malformed tag, unknown place id.
- Admin (FastAPI `TestClient`): redirect to `/login` when logged out; login; create/edit/delete a place; "הוסף למאגר" flow from an unanswered question.

## Done when

- [ ] Fresh setup on Windows following README works: venv, `pip install -r requirements.txt`, copy `.env`, `init_db.py`, `create_user.py`, both `.bat` files.
- [ ] Logged out → every page redirects to `/login`.
- [ ] Staff can add, edit, deactivate and delete places, knowledge items and events.
- [ ] Asking "איפה המעליות?" → the robot reads the directions from the DB and runs motion 126 while speaking.
- [ ] Editing the directions in the admin affects the very next question, without restarting the robot.
- [ ] Unknown topic → the secretary sentence, and the question appears in `/unanswered`.
- [ ] Events that already ended today, or are on another day, are never mentioned.
- [ ] Inactive items are never used.
- [ ] Wave on greeting and bow on closing work without WonderCode.
- [ ] All tests pass.

## How to work

1. Read the repo, then write a short plan (files, order) before coding.
2. Build in this order, running tests after each: `db.py` + scripts → admin → robot changes → README (Hebrew setup guide for Windows, step by step, for a non-technical staff member) → `DECISIONS.md`.
3. Commit after each step with a clear message.
