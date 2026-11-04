import time
import re
import queue
import serial
import sounddevice as sd
import numpy as np


# ============================================================
# تنظیمات مودم
# ============================================================

SERIAL_PORT = "COM5"
BAUDRATE = 115200

# شماره مقصد را وارد کنید
PHONE_NUMBER = input("شماره تلفن مقصد را وارد کنید: ").strip()

# تنظیمات صوتی
CHANNELS = 2
BLOCK_SIZE = 441          # حدود 10 میلی‌ثانیه در 44100Hz
PREFERRED_SAMPLE_RATES = [44100, 48000]

# اندازه صف صوتی؛ حدود 300 میلی‌ثانیه
QUEUE_SIZE = 30

# حداکثر زمان انتظار برای پاسخ مخاطب
CALL_ANSWER_TIMEOUT = 180


# ============================================================
# ابزارهای شناسایی دستگاه‌های صوتی
# ============================================================

def get_hostapi_name(device):
    try:
        return sd.query_hostapis(device["hostapi"])["name"]
    except Exception:
        return "Unknown"


def list_devices(direction):
    devices = []

    for index, device in enumerate(sd.query_devices()):

        if direction == "input":
            channels = device["max_input_channels"]
        else:
            channels = device["max_output_channels"]

        if channels <= 0:
            continue

        devices.append({
            "index": index,
            "name": device["name"],
            "channels": channels,
            "rate": int(device["default_samplerate"]),
            "hostapi": get_hostapi_name(device)
        })

    return devices


def find_preferred_device(devices, keywords):
    for keyword in keywords:
        for device in devices:
            if keyword.lower() in device["name"].lower():
                return device

    return None


def choose_device(title, direction, preferred_keywords=None):
    devices = list_devices(direction)

    if not devices:
        raise RuntimeError(
            f"هیچ دستگاه صوتی برای نقش {title} پیدا نشد."
        )

    preferred = None

    if preferred_keywords:
        preferred = find_preferred_device(
            devices,
            preferred_keywords
        )

    print("\n" + "=" * 65)
    print(title)
    print("=" * 65)

    for i, device in enumerate(devices):

        default_mark = ""

        if preferred and device["index"] == preferred["index"]:
            default_mark = "  <-- انتخاب پیشنهادی"

        print(
            f"{i + 1}. {device['name']}\n"
            f"   نوع اتصال: {device['hostapi']} | "
            f"کانال: {device['channels']} | "
            f"نرخ پیش‌فرض: {device['rate']}"
            f"{default_mark}"
        )

    if preferred:
        default_index = devices.index(preferred) + 1
    else:
        default_index = 1

    while True:

        answer = input(
            f"\nشماره دستگاه برای «{title}» "
            f"[پیش‌فرض {default_index}]: "
        ).strip()

        if answer == "":
            return devices[default_index - 1]

        try:
            selected = int(answer)

            if 1 <= selected <= len(devices):
                return devices[selected - 1]

        except ValueError:
            pass

        print("انتخاب نامعتبر است. دوباره تلاش کنید.")


# ============================================================
# انتخاب چهار دستگاه صوتی
# ============================================================

def select_audio_devices():

    print("\n\nانتخاب دستگاه‌های صوتی")
    print("لطفاً نقش هر دستگاه را با دقت انتخاب کنید.")

    # میکروفون کاربر
    user_microphone = choose_device(
        "میکروفون کاربر - صدای شما را دریافت می‌کند",
        "input",
        ["A4ech FHD 1080P PC Camera", "A4tech"]
    )

    # ورودی کارت صدای مودم
    modem_input = choose_device(
        "ورودی کارت صدای USB - صدای مخاطب تلفنی",
        "input",
        ["Microphone (2- USB PnP Sound Device)",
         "Microphone (USB PnP Sound Device)"]
    )

    # خروجی کارت صدای مودم
    modem_output = choose_device(
        "خروجی کارت صدای USB - ارسال صدای شما به مخاطب",
        "output",
        ["Speakers (2- USB PnP Sound Device)",
         "Speakers (USB PnP Sound Device)"]
    )

    # بلندگوی معمولی کاربر
    user_speaker = choose_device(
        "بلندگوی معمولی سیستم - پخش صدای مخاطب",
        "output",
        ["Microsoft Sound Mapper - Output",
         "Headphones (High Definition Audio Device)"]
    )

    selected = {
        "user_microphone": user_microphone,
        "modem_input": modem_input,
        "modem_output": modem_output,
        "user_speaker": user_speaker
    }

    # جلوگیری از انتخاب یک ورودی برای هر دو نقش
    if user_microphone["index"] == modem_input["index"]:
        raise RuntimeError(
            "میکروفون کاربر و ورودی کارت صدای مودم "
            "نباید یک دستگاه باشند."
        )

    if modem_output["index"] == user_speaker["index"]:
        raise RuntimeError(
            "خروجی کارت صدای مودم و بلندگوی کاربر "
            "نباید یک دستگاه باشند."
        )

    return selected


# ============================================================
# انتخاب نرخ نمونه‌برداری مشترک
# ============================================================

def select_sample_rate(devices):

    for rate in PREFERRED_SAMPLE_RATES:

        try:
            sd.check_input_settings(
                device=devices["user_microphone"]["index"],
                channels=1,
                dtype="float32",
                samplerate=rate
            )

            sd.check_input_settings(
                device=devices["modem_input"]["index"],
                channels=1,
                dtype="float32",
                samplerate=rate
            )

            sd.check_output_settings(
                device=devices["modem_output"]["index"],
                channels=2,
                dtype="float32",
                samplerate=rate
            )

            sd.check_output_settings(
                device=devices["user_speaker"]["index"],
                channels=2,
                dtype="float32",
                samplerate=rate
            )

            return rate

        except Exception:
            continue

    raise RuntimeError(
        "هیچ نرخ نمونه‌برداری مشترکی برای چهار دستگاه "
        "انتخاب‌شده پیدا نشد. دستگاه‌ها را دوباره انتخاب کنید."
    )


# ============================================================
# صف‌های انتقال صدا
# ============================================================

mic_to_modem = queue.Queue(maxsize=QUEUE_SIZE)
modem_to_speaker = queue.Queue(maxsize=QUEUE_SIZE)


def put_audio(audio_queue, data):

    try:
        audio_queue.put_nowait(data.copy())

    except queue.Full:
        # حذف قدیمی‌ترین بلوک برای کاهش تأخیر
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            pass

        try:
            audio_queue.put_nowait(data.copy())
        except queue.Full:
            pass


def get_audio(audio_queue, frames, channels):

    output = np.zeros(
        (frames, channels),
        dtype=np.float32
    )

    try:
        data = audio_queue.get_nowait()

        length = min(frames, len(data))

        if data.ndim == 1:
            data = data.reshape(-1, 1)

        if data.shape[1] == 1 and channels == 2:
            data = np.repeat(data, 2, axis=1)

        output[:length] = data[:length, :channels]

    except queue.Empty:
        pass

    return output


# ============================================================
# Callback های صوتی
# ============================================================

def user_microphone_callback(indata, frames, time_info, status):

    # A4Tech -> USB PnP Output
    put_audio(mic_to_modem, indata)


def modem_input_callback(indata, frames, time_info, status):

    # USB PnP Input -> بلندگوی معمولی
    put_audio(modem_to_speaker, indata)


def modem_output_callback(outdata, frames, time_info, status):

    outdata[:] = get_audio(
        mic_to_modem,
        frames,
        2
    )


def user_speaker_callback(outdata, frames, time_info, status):

    outdata[:] = get_audio(
        modem_to_speaker,
        frames,
        2
    )


# ============================================================
# مدیریت جریان‌های صوتی
# ============================================================

def start_audio_bridge(devices, sample_rate):

    print("\nدر حال راه‌اندازی مسیرهای صوتی...")

    streams = []

    try:

        # میکروفون A4Tech
        mic_stream = sd.InputStream(
            device=devices["user_microphone"]["index"],
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=user_microphone_callback
        )

        # ورودی کارت صدای مودم
        modem_input_stream = sd.InputStream(
            device=devices["modem_input"]["index"],
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=modem_input_callback
        )

        # خروجی کارت صدای مودم
        modem_output_stream = sd.OutputStream(
            device=devices["modem_output"]["index"],
            samplerate=sample_rate,
            channels=2,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=modem_output_callback
        )

        # بلندگوی معمولی سیستم
        speaker_stream = sd.OutputStream(
            device=devices["user_speaker"]["index"],
            samplerate=sample_rate,
            channels=2,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=user_speaker_callback
        )

        streams = [
            mic_stream,
            modem_input_stream,
            modem_output_stream,
            speaker_stream
        ]

        for stream in streams:
            stream.start()

        print("تمام جریان‌های صوتی فعال شدند.")
        print("میکروفون A4Tech -> مخاطب تلفنی")
        print("مخاطب تلفنی -> بلندگوی معمولی سیستم")

        return streams

    except Exception:

        for stream in streams:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        raise


def stop_audio_bridge(streams):

    print("\nدر حال بستن جریان‌های صوتی...")

    for stream in streams:

        try:
            stream.stop()
        except Exception:
            pass

        try:
            stream.close()
        except Exception:
            pass

    print("جریان‌های صوتی بسته شدند.")


# ============================================================
# ارتباط سریال با مودم
# ============================================================

def read_serial(ser, duration=0.8):

    result = ""
    deadline = time.time() + duration

    while time.time() < deadline:

        try:
            data = ser.read(ser.in_waiting or 1)

            if data:
                result += data.decode(
                    "utf-8",
                    errors="ignore"
                )

        except Exception:
            break

    if result.strip():
        print(result.strip())

    return result


def send_at(ser, command, wait=0.8):

    print(f"\n>> {command}")

    ser.write((command + "\r").encode())
    ser.flush()

    return read_serial(ser, wait)


def get_call_status(ser):

    response = send_at(
        ser,
        "AT+CLCC",
        wait=0.7
    )

    if "NO CARRIER" in response:
        return "disconnected"

    if "BUSY" in response:
        return "disconnected"

    if "NO DIALTONE" in response:
        return "disconnected"

    matches = re.findall(
        r"\+CLCC:\s*\d+,\d+,(\d+),",
        response
    )

    if not matches:
        return "unknown"

    status = int(matches[0])

    if status == 0:
        return "active"

    if status in (2, 3, 4, 5):
        return "waiting"

    if status == 6:
        return "disconnected"

    return "unknown"


# ============================================================
# انتظار برای پاسخ مخاطب
# ============================================================

def wait_for_answer(ser):

    print("\nمنتظر پاسخ مخاطب هستیم...")

    start_time = time.time()

    while True:

        if time.time() - start_time > CALL_ANSWER_TIMEOUT:
            print("زمان انتظار برای پاسخ به پایان رسید.")
            return False

        status = get_call_status(ser)

        if status == "active":
            print("\nتماس برقرار شد.")
            return True

        if status == "disconnected":
            print("\nتماس برقرار نشد یا قطع شد.")
            return False

        time.sleep(0.8)


# ============================================================
# مکالمه زنده و بررسی قطع تماس
# ============================================================

def live_conversation(ser, devices, sample_rate):

    streams = []

    try:

        streams = start_audio_bridge(
            devices,
            sample_rate
        )

        print("\n" + "=" * 55)
        print("مکالمه زنده شروع شد.")
        print("برای پایان تماس Ctrl+C را فشار دهید.")
        print("=" * 55)

        missing_call_count = 0

        while True:

            status = get_call_status(ser)

            if status == "disconnected":
                print("\nمخاطب تماس را قطع کرد.")
                break

            if status == "unknown":
                missing_call_count += 1
            else:
                missing_call_count = 0

            # اگر سه بار وضعیت تماس دریافت نشود،
            # احتمالاً تماس قطع شده است.
            if missing_call_count >= 3:
                print("\nوضعیت تماس دریافت نمی‌شود؛ بررسی پایان تماس.")
                break

            time.sleep(0.3)

    finally:

        if streams:
            stop_audio_bridge(streams)


# ============================================================
# برنامه اصلی
# ============================================================

def main():

    ser = None

    try:

        if not PHONE_NUMBER:
            print("شماره تلفن وارد نشده است.")
            return

        # انتخاب دستگاه‌ها
        devices = select_audio_devices()

        print("\nدستگاه‌های انتخاب‌شده:")
        print("--------------------------------------------")

        for role, device in devices.items():
            print(f"{role}: {device['name']}")
            print(f"Host API: {device['hostapi']}")

        # نرخ مشترک
        sample_rate = select_sample_rate(devices)

        print(f"\nSample Rate: {sample_rate}")

        # اتصال به مودم
        print(f"\nاتصال به {SERIAL_PORT}...")

        ser = serial.Serial(
            port=SERIAL_PORT,
            baudrate=BAUDRATE,
            timeout=0.1,
            write_timeout=2
        )

        time.sleep(1)

        # تست ارتباط
        response = send_at(
            ser,
            "AT",
            wait=0.5
        )

        if "OK" not in response:
            raise RuntimeError(
                "پاسخی از مودم دریافت نشد. پورت سریال را بررسی کنید."
            )

        send_at(ser, "ATE0", wait=0.3)
        send_at(ser, "AT+CLCC", wait=0.5)

        # شماره‌گیری
        print("\nدر حال شماره‌گیری...")

        send_at(
            ser,
            f"ATD{PHONE_NUMBER};",
            wait=1
        )

        # انتظار برای پاسخ
        answered = wait_for_answer(ser)

        if not answered:
            return

        # شروع مکالمه
        live_conversation(
            ser,
            devices,
            sample_rate
        )

    except KeyboardInterrupt:
        print("\nدرخواست پایان تماس دریافت شد.")

    except Exception as error:
        print("\nخطا:")
        print(error)

    finally:

        if ser and ser.is_open:

            try:
                print("\nدر حال قطع تماس...")
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