"""
robot/academy_guide.py -- the open-day guide robot.

Watches the camera for a visitor, greets them with a wave, answers questions
from the staff-managed database (via Gemini), points at places while speaking,
and bows when the conversation ends.

Run from the project root:  python -m robot.academy_guide   (or start_robot.bat)
"""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

# Windows consoles often default to a non-UTF-8 codepage, which can't print Hebrew/emoji.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import edge_tts  # noqa: E402
import pygame  # noqa: E402
import speech_recognition as sr  # noqa: E402
from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

import db  # noqa: E402  (also loads .env)
from robot import brain  # noqa: E402
from robot.robot_motion import ALLOWED_GROUPS, BOW, WAVE, RobotMotion  # noqa: E402

# --------------------------------------------------------------------------- settings

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
ROBOT_COM_PORT = os.environ.get("ROBOT_COM_PORT", "COM3")

# Minimum detected face width (pixels) before a visitor counts as "close enough" to greet
FACE_PROXIMITY_THRESHOLD = 130
# Pause after a session so the same visitor doesn't immediately start a new one
COOLDOWN_AFTER_SESSION = 5

# Male Hebrew neural voice, slightly slower and lower for a "robotic" cadence
ROBOT_VOICE = "he-IL-AvriNeural"
ROBOT_VOICE_RATE = "-8%"
ROBOT_VOICE_PITCH = "-10Hz"

GREETING = "שלום! אני המדריך של המכללה. אפשר לשאול אותי על מקומות בבניין, על ההרצאות של היום ועל הלימודים."
CLOSING = "בשמחה! שיהיה לכם יום פתוח נעים במכללה. להתראות!"
EXIT_WORDS = {"תודה", "צא", "exit", "stop"}

# --------------------------------------------------------------------------- setup

pygame.mixer.init()
recognizer = sr.Recognizer()
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
motion = RobotMotion(ROBOT_COM_PORT)   # if the robot isn't connected, motions are skipped
AUDIO_FILE = Path(tempfile.gettempdir()) / "visitor_guide_reply.mp3"


# --------------------------------------------------------------------------- speech

def speak(text: str, gesture_id=None) -> None:
    """Create the audio first, then start the gesture and the playback at the same moment."""
    try:
        communicate = edge_tts.Communicate(text, voice=ROBOT_VOICE, rate=ROBOT_VOICE_RATE, pitch=ROBOT_VOICE_PITCH)
        asyncio.run(communicate.save(str(AUDIO_FILE)))   # the slow part happens before anything moves
        pygame.mixer.music.load(str(AUDIO_FILE))

        if gesture_id is not None:
            if gesture_id in ALLOWED_GROUPS:
                motion.start_talking(first_group=gesture_id)   # runs in a background thread
            else:
                print(f"⚠️ Gesture {gesture_id} is not in ALLOWED_GROUPS (robot_motion.py); skipped.")
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
        pygame.mixer.music.unload()
    except Exception as e:
        print(f"[Audio output error: {e}]")
    finally:
        motion.stop_talking()   # waits for the gesture to finish, never cuts it mid-way


def listen_to_visitor():
    with sr.Microphone() as source:
        print("\n🎤 Listening...")
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
            text = recognizer.recognize_google(audio, language="he-IL")
            print(f"Visitor: {text}")
            return text
        except sr.WaitTimeoutError:
            print("...silence")
        except sr.UnknownValueError:
            print("...could not understand")
        except sr.RequestError as e:
            print(f"...speech service error: {e}")
        return None


# --------------------------------------------------------------------------- thinking

def answer(question: str) -> brain.Action:
    """Read fresh data from the database, ask Gemini, and decide what to say and do."""
    try:
        snapshot = db.robot_snapshot()
    except Exception as e:
        print(f"⚠️ Database error: {e}")
        return brain.Action(brain.UNKNOWN_SENTENCE, unanswered=True)
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=question,
            config=types.GenerateContentConfig(system_instruction=brain.build_system_prompt(snapshot)),
        )
        parsed = brain.parse_reply(response.text)
    except Exception as e:
        print(f"⚠️ Gemini error: {e}")
        parsed = brain.Parsed("UNKNOWN", "")
    print(f"[{parsed.tag}{':' + str(parsed.place_id) if parsed.place_id else ''}]")
    return brain.decide(parsed, snapshot["places"])


def handle_question(question: str) -> None:
    action = answer(question)
    if action.unanswered:
        try:
            db.add_unanswered(question)
        except Exception as e:
            print(f"⚠️ Could not save unanswered question: {e}")
    print(f"Guide: {action.say}")
    speak(action.say, gesture_id=action.gesture_id)


# --------------------------------------------------------------------------- session

def is_exit(text: str) -> bool:
    clean = text.lower().strip()
    return "תודה בוט" in clean or clean in EXIT_WORDS


def run_conversation_session() -> None:
    print("👋 Visitor detected -- waving and greeting.")
    print(f"Guide: {GREETING}")
    speak(GREETING, gesture_id=WAVE)

    while True:
        question = listen_to_visitor()
        if not question:
            continue
        if is_exit(question):
            print(f"Guide: {CLOSING}")
            speak(CLOSING)
            motion.run_group(BOW)
            print("Session ended.")
            return
        handle_question(question)


def wait_for_visitor(cap) -> bool:
    """Block until a close-enough face is seen. Returns False if ESC was pressed."""
    print("\n📷 Watching for visitors... (ESC on the camera window to shut down)")
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5)
        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)
        cv2.imshow("VisitorGuideBot Vision", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            return False
        if any(w > FACE_PROXIMITY_THRESHOLD for (_, _, w, _) in faces):
           cv2.destroyWindow("VisitorGuideBot Vision")
           return True


def open_camera():
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    for index in (1, 0):   # 1 = external USB webcam, 0 = built-in
        cap = cv2.VideoCapture(index, backend)
        if cap.isOpened() and cap.read()[0]:
            print(f"📷 Using camera index {index}")
            return cap
        cap.release()
    return None


def main() -> None:
    db.init_db()
    print("🤖 Visitor guide is online. Say 'תודה' to end a session. ESC on the camera window to quit.")
    cap = open_camera()
    if cap is None:
        print("❌ Could not open the camera. Check that it is connected and not used by another app.")
        return
    try:
        while wait_for_visitor(cap):
            run_conversation_session()
            print(f"⏳ Cooling down {COOLDOWN_AFTER_SESSION}s...")
            time.sleep(COOLDOWN_AFTER_SESSION)
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
