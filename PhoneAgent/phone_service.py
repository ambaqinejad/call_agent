# -*- coding: utf-8 -*-
"""
Windows GSM Phone Service for SIMCOM R800C / R1850.
- Serial control only; audio is intentionally left to Qwen Realtime/WebUI.
- Python 3.10+
Install: py -m pip install pyserial
Run: set PHONE_API_TOKEN=... && py phone_service.py
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import serial

SERIAL_PORT = os.getenv("PHONE_SERIAL_PORT", "COM5")
BAUDRATE = int(os.getenv("PHONE_BAUDRATE", "115200"))
HTTP_HOST = os.getenv("PHONE_HTTP_HOST", "127.0.0.1")
HTTP_PORT = int(os.getenv("PHONE_HTTP_PORT", "8787"))
API_TOKEN = os.getenv("PHONE_API_TOKEN", "")
AUTO_ANSWER = os.getenv("PHONE_AUTO_ANSWER", "false").lower() in ("1", "true", "yes")
AUTO_ANSWER_DELAY = float(os.getenv("PHONE_AUTO_ANSWER_DELAY", "1.0"))

class PhoneController:
    def __init__(self):
        self.ser = None
        self.write_lock = threading.Lock()
        self.cv = threading.Condition()
        self.lines = []
        self.events = []
        self.state = "starting"
        self.direction = None
        self.number = None
        self.last_error = None
        self.last_change = time.time()
        self._stop = False
        self._ring_at = 0.0
        self._reader = None

    def _set_state(self, state, **extra):
        with self.cv:
            self.state = state
            self.last_change = time.time()
            event = {"time": self.last_change, "state": state, **extra}
            self.events.append(event)
            self.events = self.events[-200:]
            self.cv.notify_all()

    def start(self):
        self.ser = serial.Serial(
            port=SERIAL_PORT, baudrate=BAUDRATE, timeout=0.25,
            write_timeout=2
        )
        time.sleep(0.4)
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self.command("AT", timeout=2)
        self.command("ATE0", timeout=2)
        self.command("AT+CLIP=1", timeout=2)
        self.command("AT+CRC=1", timeout=2)
        self._set_state("idle")
        print(f"[PHONE] Serial ready: {SERIAL_PORT} @ {BAUDRATE}")
        print(f"[PHONE] HTTP: http://{HTTP_HOST}:{HTTP_PORT}")

    def _read_loop(self):
        buf = b""
        while not self._stop and self.ser:
            try:
                chunk = self.ser.read(256)
                if not chunk:
                    continue
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if line:
                        self._handle_line(line)
            except Exception as e:
                self.last_error = str(e)
                self._set_state("error", error=str(e))
                time.sleep(0.5)

    def _handle_line(self, line):
        print("[MODEM]", line)
        with self.cv:
            self.lines.append((time.time(), line))
            self.lines = self.lines[-500:]
            self.cv.notify_all()

        upper = line.upper()
        if upper == "RING" or upper.startswith("+CRING:"):
            self._ring_at = time.time()
            if self.state not in ("active", "dialing"):
                self.direction = "incoming"
                self._set_state("ringing", number=self.number)
                if AUTO_ANSWER:
                    threading.Thread(target=self._auto_answer, daemon=True).start()
            return

        if upper.startswith("+CLIP:"):
            m = re.search(r'"([^"]+)"', line)
            if m:
                self.number = m.group(1)
                self.direction = "incoming" if self.state == "ringing" else self.direction
                self._set_state(self.state, caller_number=self.number)
            return

        if upper == "CONNECT":
            self._set_state("active", number=self.number, direction=self.direction)
        elif upper in ("NO CARRIER", "BUSY", "NO ANSWER"):
            self._set_state("idle", reason=upper)
            self.direction = None
            self.number = None
        elif upper == "ERROR":
            self.last_error = "Modem returned ERROR"

    def _auto_answer(self):
        time.sleep(AUTO_ANSWER_DELAY)
        if self.state == "ringing":
            try:
                self.answer()
            except Exception as e:
                self.last_error = str(e)

    def command(self, cmd, timeout=3):
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Serial modem is not connected")
        marker = time.time()
        with self.write_lock:
            self.ser.write((cmd + "\r").encode("ascii", errors="ignore"))
            self.ser.flush()
        deadline = time.time() + timeout
        collected = []
        while time.time() < deadline:
            with self.cv:
                collected = [line for ts, line in self.lines if ts >= marker]
                if any(x in ("OK", "ERROR") for x in collected):
                    break
                self.cv.wait(timeout=0.1)
        return collected

    def dial(self, number):
        number = re.sub(r"[ \-()]", "", str(number))
        if not re.fullmatch(r"\+?[0-9]{6,20}", number):
            raise ValueError("شماره تلفن معتبر نیست؛ فقط رقم و علامت + مجاز است.")
        if self.state not in ("idle", "error"):
            raise RuntimeError(f"خط در وضعیت {self.state} است؛ ابتدا تماس فعلی را قطع کنید.")
        self.number = number
        self.direction = "outgoing"
        self._set_state("dialing", number=number, direction="outgoing")
        result = self.command(f"ATD{number};", timeout=2)
        if any(x == "ERROR" for x in result):
            self._set_state("idle", reason="dial_error")
            raise RuntimeError("مودم فرمان شماره‌گیری را نپذیرفت.")
        return self.status(refresh=False)

    def answer(self):
        if self.state != "ringing":
            raise RuntimeError(f"تماس ورودی برای پاسخ وجود ندارد؛ وضعیت فعلی: {self.state}")
        result = self.command("ATA", timeout=5)
        if any(x == "ERROR" for x in result):
            raise RuntimeError("مودم فرمان پاسخ را نپذیرفت.")
        self.direction = "incoming"
        self._set_state("active", number=self.number, direction="incoming")
        return self.status(refresh=False)

    def hangup(self):
        self.command("ATH", timeout=3)
        self.direction = None
        self.number = None
        self._set_state("idle", reason="local_hangup")
        return self.status(refresh=False)

    def status(self, refresh=True):
        if refresh and self.state in ("dialing", "active", "ringing"):
            result = self.command("AT+CLCC", timeout=1.5)
            clcc = next((x for x in result if x.startswith("+CLCC:")), None)
            if clcc:
                # +CLCC: <id>,<dir>,<stat>,<mode>,<mpty>[,<number>,<type>]
                fields = clcc.split(":", 1)[1].strip().split(",")
                if len(fields) >= 3:
                    stat = fields[2].strip()
                    mapped = {"0": "active", "2": "dialing", "3": "alerting",
                              "4": "incoming", "5": "waiting"}.get(stat)
                    if mapped:
                        if mapped == "incoming" and self.state != "active":
                            self._set_state("ringing")
                        elif mapped in ("active", "dialing", "alerting"):
                            self._set_state(mapped)
            elif self.state == "active" and any(
                line == "NO CARRIER" for _, line in self.lines[-20:]
            ):
                self._set_state("idle")
        return {
            "state": self.state,
            "direction": self.direction,
            "phone_number": self.number,
            "caller_number": self.number if self.direction == "incoming" else None,
            "auto_answer": AUTO_ANSWER,
            "last_error": self.last_error,
            "updated_at": self.last_change,
        }

    def recent_events(self, limit=30):
        return self.events[-max(1, min(int(limit), 100)):]

phone = PhoneController()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[HTTP]", fmt % args)

    def _send(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        if not API_TOKEN:
            self._send(503, {"ok": False, "error": "PHONE_API_TOKEN تنظیم نشده است."})
            return False
        supplied = self.headers.get("Authorization", "")
        if supplied != "Bearer " + API_TOKEN:
            self._send(401, {"ok": False, "error": "Unauthorized"})
            return False
        return True

    def do_GET(self):
        if not self._authorized():
            return
        path = urlparse(self.path).path
        try:
            if path == "/api/status":
                self._send(200, {"ok": True, **phone.status()})
            elif path == "/api/events":
                self._send(200, {"ok": True, "events": phone.recent_events()})
            else:
                self._send(404, {"ok": False, "error": "Not found"})
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})

    def do_POST(self):
        if not self._authorized():
            return
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if path == "/api/dial":
                result = phone.dial(payload.get("phone_number", ""))
            elif path == "/api/answer":
                result = phone.answer()
            elif path == "/api/hangup":
                result = phone.hangup()
            else:
                self._send(404, {"ok": False, "error": "Not found"})
                return
            self._send(200, {"ok": True, "result": result})
        except ValueError as e:
            self._send(400, {"ok": False, "error": str(e)})
        except RuntimeError as e:
            self._send(409, {"ok": False, "error": str(e)})
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})

def main():
    if not API_TOKEN or len(API_TOKEN) < 24:
        raise SystemExit("PHONE_API_TOKEN را با یک مقدار تصادفی حداقل ۲۴ کاراکتری تنظیم کنید.")
    phone.start()
    server = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        phone._stop = True
        if phone.ser:
            phone.ser.close()

if __name__ == "__main__":
    main()
