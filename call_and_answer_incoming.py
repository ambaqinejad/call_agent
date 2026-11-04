import time
import re
import queue
import serial
import sounddevice as sd
import numpy as np


# ============================================================
# تنظیمات
# ============================================================

SERIAL_PORT = "COM5"
BAUDRATE = 115200

# حالت اجرا:
# 1 = فقط تماس خروجی (سیستم به مخاطب زنگ می‌زند)
# 2 = فقط تماس ورودی (منتظر تماس مخاطب می‌ماند و خودکار جواب می‌دهد)
CALL_MODE = None

AUTO_ANSWER = True
CALL_ANSWER_TIMEOUT = 180

PREFERRED_SAMPLE_RATES = [44100, 48000]
BLOCK_SIZE = 441
QUEUE_SIZE = 30


# ============================================================
# شناسایی و انتخاب دستگاه‌های صوتی
# ============================================================

def get_hostapi_name(device):
    try:
        return sd.query_hostapis(device["hostapi"])["name"]
    except Exception:
        return "Unknown"


def list_devices(direction):
    result = []

    for index, device in enumerate(sd.query_devices()):
        channels = (
            device["max_input_channels"]
            if direction == "input"
            else device["max_output_channels"]
        )

        if channels > 0:
            result.append({
                "index": index,
                "name": device["name"],
                "channels": channels,
                "rate": int(device["default_samplerate"]),
                "hostapi": get_hostapi_name(device)
            })

    return result


def find_preferred_device(devices, keywords):
    for keyword in keywords:
        for device in devices:
            if keyword.lower() in device["name"].lower():
                return device
    return None


def choose_device(title, direction, preferred_keywords=None):
    devices = list_devices(direction)

    if not devices:
        raise RuntimeError(f"دستگاه مناسب برای «{title}» پیدا نشد.")

    preferred = (
        find_preferred_device(devices, preferred_keywords)
        if preferred_keywords else None
    )

    print("\n" + "=" * 65)
    print(title)
    print("=" * 65)

    for i, device in enumerate(devices):
        mark = (
            "  <-- انتخاب پیشنهادی"
            if preferred and device["index"] == preferred["index"]
            else ""
        )
        print(
            f"{i + 1}. {device['name']}\n"
            f"   {device['hostapi']} | "
            f"کانال: {device['channels']} | "
            f"نرخ: {device['rate']}{mark}"
        )

    default_index = devices.index(preferred) + 1 if preferred else 1

    while True:
        answer = input(
            f"\nانتخاب دستگاه برای «{title}» [پیش‌فرض {default_index}]: "
        ).strip()

        if not answer:
            return devices[default_index - 1]

        try:
            number = int(answer)
            if 1 <= number <= len(devices):
                return devices[number - 1]
        except ValueError:
            pass

        print("شماره نامعتبر است.")


def select_audio_devices():
    print("\nانتخاب دستگاه‌های صوتی")

    devices = {
        "user_microphone": choose_device(
            "میکروفون کاربر - صدای شما",
            "input",
            ["A4ech FHD 1080P PC Camera", "A4tech"]
        ),
        "modem_input": choose_device(
            "ورودی کارت صدای USB - صدای مخاطب تلفنی",
            "input",
            ["Microphone (2- USB PnP Sound Device)",
             "Microphone (USB PnP Sound Device)"]
        ),
        "modem_output": choose_device(
            "خروجی کارت صدای USB - ارسال صدای شما به تماس",
            "output",
            ["Speakers (2- USB PnP Sound Device)",
             "Speakers (USB PnP Sound Device)"]
        ),
        "user_speaker": choose_device(
            "بلندگوی معمولی سیستم - پخش صدای مخاطب",
            "output",
            ["Microsoft Sound Mapper - Output",
             "Headphones (High Definition Audio Device)"]
        )
    }

    if devices["user_microphone"]["index"] == devices["modem_input"]["index"]:
        raise RuntimeError("میکروفون A4Tech و ورودی USB PnP باید دو دستگاه جدا باشند.")

    if devices["modem_output"]["index"] == devices["user_speaker"]["index"]:
        raise RuntimeError("خروجی USB PnP و بلندگوی سیستم باید دو دستگاه جدا باشند.")

    return devices


def select_sample_rate(devices):
    for rate in PREFERRED_SAMPLE_RATES:
        try:
            sd.check_input_settings(
                device=devices["user_microphone"]["index"],
                channels=1, dtype="float32", samplerate=rate
            )
            sd.check_input_settings(
                device=devices["modem_input"]["index"],
                channels=1, dtype="float32", samplerate=rate
            )
            sd.check_output_settings(
                device=devices["modem_output"]["index"],
                channels=2, dtype="float32", samplerate=rate
            )
            sd.check_output_settings(
                device=devices["user_speaker"]["index"],
                channels=2, dtype="float32", samplerate=rate
            )
            return rate
        except Exception:
            continue

    raise RuntimeError("نرخ نمونه‌برداری مشترک برای دستگاه‌های انتخاب‌شده پیدا نشد.")


# ============================================================
# مسیرهای صوتی دوطرفه
# ============================================================

mic_to_modem = queue.Queue(maxsize=QUEUE_SIZE)
modem_to_speaker = queue.Queue(maxsize=QUEUE_SIZE)


def clear_audio_queues():
    for audio_queue in (mic_to_modem, modem_to_speaker):
        while True:
            try:
                audio_queue.get_nowait()
            except queue.Empty:
                break


def put_audio(audio_queue, data):
    try:
        audio_queue.put_nowait(data.copy())
    except queue.Full:
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            audio_queue.put_nowait(data.copy())
        except queue.Full:
            pass


def get_audio(audio_queue, frames, channels):
    output = np.zeros((frames, channels), dtype=np.float32)

    try:
        data = audio_queue.get_nowait()
        if data.ndim == 1:
            data = data.reshape(-1, 1)

        if data.shape[1] == 1 and channels == 2:
            data = np.repeat(data, 2, axis=1)

        length = min(frames, len(data))
        output[:length, :channels] = data[:length, :channels]
    except queue.Empty:
        pass

    return output


def user_microphone_callback(indata, frames, time_info, status):
    put_audio(mic_to_modem, indata)


def modem_input_callback(indata, frames, time_info, status):
    put_audio(modem_to_speaker, indata)


def modem_output_callback(outdata, frames, time_info, status):
    outdata[:] = get_audio(mic_to_modem, frames, 2)


def user_speaker_callback(outdata, frames, time_info, status):
    outdata[:] = get_audio(modem_to_speaker, frames, 2)


def start_audio_bridge(devices, sample_rate):
    streams = []
    clear_audio_queues()

    try:
        streams = [
            sd.InputStream(
                device=devices["user_microphone"]["index"],
                samplerate=sample_rate, channels=1,
                dtype="float32", blocksize=BLOCK_SIZE,
                callback=user_microphone_callback
            ),
            sd.InputStream(
                device=devices["modem_input"]["index"],
                samplerate=sample_rate, channels=1,
                dtype="float32", blocksize=BLOCK_SIZE,
                callback=modem_input_callback
            ),
            sd.OutputStream(
                device=devices["modem_output"]["index"],
                samplerate=sample_rate, channels=2,
                dtype="float32", blocksize=BLOCK_SIZE,
                callback=modem_output_callback
            ),
            sd.OutputStream(
                device=devices["user_speaker"]["index"],
                samplerate=sample_rate, channels=2,
                dtype="float32", blocksize=BLOCK_SIZE,
                callback=user_speaker_callback
            )
        ]

        for stream in streams:
            stream.start()

        print("\nمسیرهای صوتی فعال شدند:")
        print("A4Tech microphone  ---> USB PnP output ---> تماس")
        print("تماس ---> USB PnP input ---> بلندگوی سیستم")
        return streams

    except Exception:
        stop_audio_bridge(streams)
        raise


def stop_audio_bridge(streams):
    for stream in streams:
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass


# ============================================================
# ارتباط با مودم
# ============================================================

def read_serial(ser, duration=0.5):
    result = ""
    deadline = time.time() + duration

    while time.time() < deadline:
        try:
            data = ser.read(ser.in_waiting or 1)
            if data:
                result += data.decode("utf-8", errors="ignore")
        except Exception:
            break

    if result.strip():
        print(result.strip())

    return result


def send_at(ser, command, wait=0.5):
    print(f"\n>> {command}")
    ser.write((command + "\r").encode())
    ser.flush()
    return read_serial(ser, wait)


def get_call_status(ser):
    response = send_at(ser, "AT+CLCC", wait=0.35)

    if any(x in response for x in ("NO CARRIER", "BUSY", "NO DIALTONE")):
        return "disconnected"

    matches = re.findall(r"\+CLCC:\s*\d+,\d+,(\d+),", response)

    if not matches:
        return "unknown"

    status = int(matches[0])

    if status == 0:
        return "active"
    if status in (1, 2, 3, 4, 5):
        return "waiting"
    if status == 6:
        return "disconnected"

    return "unknown"


# ============================================================
# تماس خروجی
# ============================================================

def wait_for_outgoing_answer(ser):
    print("\nمنتظر پاسخ مخاطب هستیم...")
    start = time.time()

    while time.time() - start < CALL_ANSWER_TIMEOUT:
        status = get_call_status(ser)

        if status == "active":
            print("\nتماس برقرار شد.")
            return True

        if status == "disconnected":
            print("\nتماس برقرار نشد یا قطع شد.")
            return False

        time.sleep(0.5)

    print("مهلت انتظار برای پاسخ به پایان رسید.")
    return False


# ============================================================
# تماس ورودی
# ============================================================

def wait_for_incoming_call(ser):
    print("\nمنتظر تماس ورودی هستیم...")
    print("برای خروج Ctrl+C را فشار دهید.")

    buffer = ""

    while True:
        try:
            data = ser.read(ser.in_waiting or 1)
            if not data:
                continue

            text = data.decode("utf-8", errors="ignore")
            buffer += text

            # نمایش شماره تماس‌گیرنده در صورت فعال بودن Caller ID
            for line in text.replace("\r", "\n").split("\n"):
                line = line.strip()
                if line:
                    print(line)

            if re.search(r"(^|[\r\n])\s*RING\s*([\r\n]|$)", buffer, re.I):
                print("\nتماس ورودی دریافت شد.")
                return True

            # جلوگیری از رشد بی‌نهایت بافر
            if len(buffer) > 2000:
                buffer = buffer[-500:]

        except KeyboardInterrupt:
            raise
        except Exception as error:
            print("خطا هنگام انتظار برای تماس:", error)
            time.sleep(0.5)


def answer_incoming_call(ser):
    print("\nدر حال پاسخ دادن به تماس...")

    response = send_at(ser, "ATA", wait=1.0)

    if "ERROR" in response:
        print("مودم نتوانست تماس را پاسخ دهد.")
        return False

    # پس از ATA کمی فرصت می‌دهیم تماس فعال شود.
    for _ in range(10):
        status = get_call_status(ser)

        if status == "active":
            print("\nتماس ورودی پاسخ داده شد.")
            return True

        if status == "disconnected":
            print("تماس قبل از برقراری قطع شد.")
            return False

        time.sleep(0.4)

    print("وضعیت تماس پس از پاسخ مشخص نشد.")
    return False


# ============================================================
# مکالمه فعال
# ============================================================

def live_conversation(ser, devices, sample_rate):
    streams = []

    try:
        streams = start_audio_bridge(devices, sample_rate)

        print("\n" + "=" * 55)
        print("مکالمه زنده برقرار است.")
        print("برای پایان تماس Ctrl+C را فشار دهید.")
        print("=" * 55)

        unknown_count = 0

        while True:
            status = get_call_status(ser)

            if status == "disconnected":
                print("\nتماس قطع شد.")
                break

            if status == "unknown":
                unknown_count += 1
            else:
                unknown_count = 0

            if unknown_count >= 5:
                print("\nوضعیت تماس قابل دریافت نیست؛ مکالمه متوقف می‌شود.")
                break

            time.sleep(0.3)

    finally:
        stop_audio_bridge(streams)
        clear_audio_queues()


# ============================================================
# انتخاب حالت تماس
# ============================================================

def choose_call_mode():
    print("\n" + "=" * 55)
    print("سامانه تماس صوتی")
    print("=" * 55)
    print("1. تماس خروجی - سیستم با مخاطب تماس می‌گیرد")
    print("2. تماس ورودی - مخاطب تماس می‌گیرد و سیستم خودکار پاسخ می‌دهد")

    while True:
        choice = input("\nحالت اجرا را انتخاب کنید (1 یا 2): ").strip()
        if choice in ("1", "2"):
            return choice
        print("انتخاب نامعتبر است.")


# ============================================================
# برنامه اصلی
# ============================================================

def main():
    ser = None
    call_established = False

    try:
        mode = choose_call_mode()

        phone_number = ""
        if mode == "1":
            phone_number = input(
                "\nشماره تلفن مقصد را وارد کنید: "
            ).strip()

            if not phone_number:
                print("شماره تلفن وارد نشده است.")
                return

        devices = select_audio_devices()
        sample_rate = select_sample_rate(devices)

        print(f"\nSample Rate انتخاب‌شده: {sample_rate} Hz")

        print(f"\nاتصال به {SERIAL_PORT}...")
        ser = serial.Serial(
            port=SERIAL_PORT,
            baudrate=BAUDRATE,
            timeout=0.2,
            write_timeout=2
        )

        time.sleep(1)

        response = send_at(ser, "AT", wait=0.5)
        if "OK" not in response:
            raise RuntimeError("مودم به فرمان AT پاسخ نداد.")

        send_at(ser, "ATE0", wait=0.3)

        # فعال‌سازی نمایش شماره تماس‌گیرنده
        send_at(ser, "AT+CLIP=1", wait=0.4)

        # فعال‌سازی نمایش RING به شکل استاندارد، در صورت پشتیبانی مودم
        send_at(ser, "AT+CRC=0", wait=0.3)

        if mode == "1":
            print("\nدر حال شماره‌گیری...")
            response = send_at(
                ser,
                f"ATD{phone_number};",
                wait=1.0
            )

            if "ERROR" in response:
                print("فرمان شماره‌گیری ناموفق بود.")
                return

            call_established = wait_for_outgoing_answer(ser)

        else:
            # تماس ورودی: تا دریافت RING منتظر می‌مانیم.
            wait_for_incoming_call(ser)

            if AUTO_ANSWER:
                call_established = answer_incoming_call(ser)
            else:
                print("پاسخ خودکار غیرفعال است.")
                return

        if call_established:
            live_conversation(ser, devices, sample_rate)

    except KeyboardInterrupt:
        print("\nدرخواست توقف دریافت شد.")

    except Exception as error:
        print("\nخطا:")
        print(error)

    finally:
        if ser and ser.is_open:
            try:
                print("\nدر حال پایان دادن به تماس...")
                send_at(ser, "ATH", wait=0.5)
            except Exception:
                pass

            try:
                ser.close()
                print("پورت سریال بسته شد.")
            except Exception:
                pass

        print("\nبرنامه پایان یافت.")


if __name__ == "__main__":
    main()
