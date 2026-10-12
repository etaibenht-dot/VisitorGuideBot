"""
Print what a Bus Servo Control motion file (.rob) does, frame by frame.

    python scripts/show_motion.py firmware/motions/Point_Elevator.rob

File layout (reverse-engineered from Bus Servo Control V3.5 files):
  16-byte header: b"ACT-40", then the frame count (uint32, little-endian) at byte 6.
  Each frame is 248 bytes: duration in ms (uint16) at +0, then 40 servo slots of
  6 bytes starting at +8; the position (uint16, 0-1000) is the first 2 bytes of a slot.
  TonyBot uses servo IDs 1-16.
"""
import struct
import sys
from pathlib import Path

HEADER, FRAME, SLOT, FIRST_SLOT, SERVOS = 16, 248, 6, 8, 16
NAMES = {6: "left elbow", 7: "left arm sideways", 8: "left arm up/down",
         14: "right elbow", 15: "right arm sideways", 16: "right arm up/down"}


def read_frames(path):
    data = Path(path).read_bytes()
    if not data.startswith(b"ACT-40"):
        raise ValueError(f"{path}: not a Bus Servo Control motion file")
    count = struct.unpack_from("<I", data, 6)[0]
    frames = []
    for i in range(count):
        base = HEADER + FRAME * i
        ms = struct.unpack_from("<H", data, base)[0]
        pos = [struct.unpack_from("<H", data, base + FIRST_SLOT + SLOT * s)[0] for s in range(SERVOS)]
        frames.append((ms, pos))
    return frames


if __name__ == "__main__":
    for path in sys.argv[1:]:
        frames = read_frames(path)
        first = frames[0][1]
        total = sum(ms for ms, _ in frames)
        print(f"{Path(path).name}: {len(frames)} frames, {total} ms")
        for n, (ms, pos) in enumerate(frames, 1):
            moved = {sid: pos[sid - 1] for sid in range(1, SERVOS + 1) if pos[sid - 1] != first[sid - 1]}
            desc = ", ".join(f"ID {sid} ({NAMES.get(sid, 'leg')}) = {v}" for sid, v in moved.items()) or "stand"
            print(f"  frame {n}: {ms:5} ms  {desc}")
