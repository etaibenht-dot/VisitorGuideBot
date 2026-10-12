# firmware/tonybot_listener

`tonybot_listener.ino` is the program flashed on the TonyBot's ESP32. It receives
`RUN <n>` over USB serial (115200) and runs action group n, replying `DONE`.

To rebuild it, the sketch must sit inside a copy of Hiwonder's example folder
(e.g. "01 Breathing Light Program/Breathing") so the Hiwonder library files
(LobotServoController.h, HWSensor.h, Hiwonder.hpp, src/ ...) are next to it.
Build settings that worked: board "ESP32 Dev Module", esp32 core 2.0.17, SensorLib 0.2.1.

Allowed action groups: 0 (stand), 9 (wave), 10 (bow), 124-127 (pointing).
Must match ALLOWED_GROUPS in robot/robot_motion.py.
