"""
robot_motion.py -- gesture layer for VisitorGuideBot.

Talks to a small listener sketch on the TonyBot's ESP32 over USB serial:
    PC  -> robot : "RUN <group_id>\n"
    robot -> PC  : "DONE\n"   (or "ERR ...\n")
The listener sketch must exist and be flashed first -- this module does NOT
work with the old WonderCode automation (that takes ~24s per gesture).

Every action group recorded in Bus Servo Control should START and END in the
Stand pose, so any gesture can follow any other without a jerk.
"""

import random
import threading
import time

import serial

# ---- Action-group IDs (fill in the slots you download to in Bus Servo Control) ----
STAND = 0
WAVE = 9       # factory wave  (was triggered via WonderCode by the previous team)
BOW = 10       # factory bow
TALK_GESTURES = []                        # optional random "body language" while speaking (not used for now)
# Custom slots 110+ are empty in the factory set (factory uses 0-104 and 150-158).
POINT_GESTURES = {                        # place -> action group recorded in Bus Servo Control
    "toilet": 124,         # point_Toilet
    "heder_eyoon": 125,    # point_Heder_Eyoon (reading room)
    "elevator": 126,       # point_Elevator
    "segel": 127,          # point_Segel (staff room)
}
ALLOWED_GROUPS = {STAND, WAVE, BOW, *TALK_GESTURES, *POINT_GESTURES.values()}


class RobotMotion:
    def __init__(self, port, baud=115200):
        self._lock = threading.Lock()          # one gesture on the wire at a time
        self._stop_talking = threading.Event()
        self._talk_thread = None
        self._last_talk = None
        self.ser = None
        try:
            ser = serial.Serial()
            ser.port, ser.baudrate, ser.timeout = port, baud, 0.1
            # Opening the port normally toggles DTR/RTS, which RESETS the ESP32.
            ser.dtr = False
            ser.rts = False
            ser.open()
            time.sleep(2)                      # in case it reset anyway
            ser.reset_input_buffer()
            self.ser = ser
            print(f"✅ Robot motion connected on {port}")
        except Exception as e:
            print(f"⚠️ Robot motion disabled ({e})")

    # ---------- low level ----------
    def run_group(self, group_id, timeout=10.0):
        """Blocking: run one action group and wait until the robot reports DONE."""
        if self.ser is None:
            return False
        if group_id not in ALLOWED_GROUPS:
            raise ValueError(f"Action group {group_id} is not whitelisted")
        with self._lock:
            self.ser.reset_input_buffer()
            self.ser.write(f"RUN {group_id}\n".encode())
            deadline = time.time() + timeout
            while time.time() < deadline:
                line = self.ser.readline().decode(errors="ignore").strip()
                if line == "DONE":
                    return True
                if line.startswith("ERR"):
                    print(f"⚠️ Robot error: {line}")
                    return False
            print(f"⚠️ Timeout waiting for action group {group_id}")
            return False

    def run_group_async(self, group_id):
        t = threading.Thread(target=self.run_group, args=(group_id,), daemon=True)
        t.start()
        return t

    # ---------- talking body language ----------
    def _pick_talk_gesture(self):
        # random, but never the same gesture twice in a row
        options = [g for g in TALK_GESTURES if g != self._last_talk] or TALK_GESTURES
        self._last_talk = random.choice(options)
        return self._last_talk

    def _talk_loop(self, first_group):
        group = first_group
        while group is not None and not self._stop_talking.is_set():
            self.run_group(group)
            if not TALK_GESTURES or self._stop_talking.wait(0.4):
                break                          # no talk gestures -> just the one gesture
            group = self._pick_talk_gesture()

    def start_talking(self, first_group=None):
        """Start looping random talk gestures in the background until stop_talking()."""
        if self.ser is None:
            return
        self._stop_talking.clear()
        first = first_group
        if first is None:
            if not TALK_GESTURES:
                return                         # nothing to do
            first = self._pick_talk_gesture()
        self._talk_thread = threading.Thread(target=self._talk_loop, args=(first,), daemon=True)
        self._talk_thread.start()

    def stop_talking(self):
        """Stop after the current gesture finishes (never cut a gesture mid-way)."""
        self._stop_talking.set()
        if self._talk_thread is not None:
            self._talk_thread.join(timeout=10)
            self._talk_thread = None
