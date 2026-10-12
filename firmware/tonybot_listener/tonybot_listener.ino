/*
 * tonybot_listener.ino -- runs on the TonyBot's ESP32.
 * Receives action-group commands from the PC over USB serial and runs them.
 *
 * Protocol (one line per message, '\n' terminated, 115200 baud):
 *   PC -> robot : "RUN <id>"   run a whitelisted action group once
 *                 "PING"       health check
 *   robot -> PC : "READY"      after boot
 *                 "DONE"       action group finished
 *                 "PONG"
 *                 "ERR BUSY" | "ERR BAD_ID" | "ERR UNKNOWN" | "ERR NOSTART" | "ERR TIMEOUT"
 *
 * Non-blocking: loop() never uses delay()/waitForStop()/readStringUntil(),
 * so serial input and servo-controller feedback are always being processed.
 *
 * Includes and setup are taken from Hiwonder's official Tonybot Arduino
 * examples -- build it inside Hiwonder's Arduino project folder so the
 * libraries (LobotServoController, HWSensor, base_config ...) are found.
 */

#include "base_config.h"
#include "HardwareSerial.h"
#include "LobotServoController.h"
#include "Arduino.h"
#include "Servo.h"
#include "HWSensor.h"
#include "Hiwonder.hpp"

LobotServoController Controller(Serial2);
HWSensor hwsensor;   // same as Hiwonder's examples -- its constructor sets up the on-board sensors/buzzer
Servo sonarServo;

// Must match ALLOWED_GROUPS in robot_motion.py
const int ALLOWED_GROUPS[] = {0, 9, 10, 124, 125, 126, 127};   // 9 = wave, 10 = bow (factory)
const int NUM_ALLOWED = sizeof(ALLOWED_GROUPS) / sizeof(ALLOWED_GROUPS[0]);

const unsigned long START_TIMEOUT_MS = 800;   // controller must report "running" within this
const unsigned long MAX_RUN_MS       = 8000;  // longest allowed action group

enum State { IDLE, WAIT_START, RUNNING };
State state = IDLE;
unsigned long stateSince = 0;

char lineBuf[32];
uint8_t lineLen = 0;

bool isAllowed(int id) {
  for (int i = 0; i < NUM_ALLOWED; i++) {
    if (ALLOWED_GROUPS[i] == id) return true;
  }
  return false;
}

void setState(State s) {
  state = s;
  stateSince = millis();
}

void handleCommand(const char* cmd) {
  if (strcmp(cmd, "PING") == 0) {
    Serial.println("PONG");
    return;
  }
  if (strncmp(cmd, "RUN ", 4) == 0) {
    if (state != IDLE) {
      Serial.println("ERR BUSY");
      return;
    }
    char* end;
    long id = strtol(cmd + 4, &end, 10);
    if (end == cmd + 4 || *end != '\0' || !isAllowed((int)id)) {
      Serial.println("ERR BAD_ID");
      return;
    }
    Controller.runActionGroup((int)id, 1);
    setState(WAIT_START);
    return;
  }
  Serial.println("ERR UNKNOWN");
}

// Read serial byte-by-byte; never blocks.
void pollSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      lineBuf[lineLen] = '\0';
      if (lineLen > 0) handleCommand(lineBuf);
      lineLen = 0;
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    } else {
      lineLen = 0;                      // line too long -> drop it
      Serial.println("ERR UNKNOWN");
    }
  }
}

// Track the action group using the servo controller's own status feedback.
void updateMotion() {
  unsigned long elapsed = millis() - stateSince;
  switch (state) {
    case IDLE:
      break;
    case WAIT_START:
      // isRunning() only becomes true once the controller reports RUNNING,
      // so wait for that first -- otherwise we'd send DONE immediately.
      if (Controller.isRunning()) {
        setState(RUNNING);
      } else if (elapsed > START_TIMEOUT_MS) {
        Serial.println("ERR NOSTART");
        setState(IDLE);
      }
      break;
    case RUNNING:
      if (!Controller.isRunning()) {
        Serial.println("DONE");
        setState(IDLE);
      } else if (elapsed > MAX_RUN_MS) {
        Serial.println("ERR TIMEOUT");
        setState(IDLE);
      }
      break;
  }
}

void setup() {
  Serial.begin(115200);
  Serial2.begin(9600, SERIAL_8N1, IO_BaseRX, IO_BaseTX);

  // Center the head servo (as in Hiwonder's examples)
  sonarServo.attach(IO_Servo);
  sonarServo.write(90);
  delay(200);
  sonarServo.detach();

  Controller.runActionGroup(0, 1);      // Stand
  delay(1500);                          // setup only -- loop() never blocks
  Serial.println("READY");
}

void loop() {
  Controller.receiveHandle();           // process feedback from the servo controller
  pollSerial();
  updateMotion();
}
