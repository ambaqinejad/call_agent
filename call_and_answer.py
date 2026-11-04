import time
import queue
import threading
import serial
import sounddevice as sd
import numpy as np

# ==================== تنظیمات ====================

PORT = "COM5"
BAUDRATE = 115200

PHONE_NUMBER = "+989025919234"

# دستگاه‌های صوتی بر اساس خروجی فعلی شما
def find_device(name, device_type, channels=1):

    devices = sd.query_devices()

    for i, device in enumerate(devices):

        if name.lower() in device["name"].lower():

            if device_type == "input":
                available = device["max_input_channels"]
            else:
                available = device["max_output_channels"]

            if available >= channels:

                print(
                    f"دستگاه پیدا شد: [{i}] "
                    f"{device['name']}"
                )

                return i

    raise RuntimeError(
        f"دستگاه پیدا نشد: {name}"
    )

SAMPLE_RATE = 44100
CHANNELS = 2
BLOCK_SIZE = 960

ANSWER_TIMEOUT = 60
CALL_CHECK_INTERVAL = 1.0

# ظرفیت بافر صوتی
QUEUE_SIZE = 50

# =================================================


# صف‌های صوتی
mic_to_call = queue.Queue(maxsize=QUEUE_SIZE)
call_to_speaker = queue.Queue(maxsize=QUEUE_SIZE)

running = threading.Event()


def send_at(ser, command, wait=0.5):
    """ارسال فرمان AT و خواندن پاسخ."""

    print(f"\n>> {command}")

    ser.write((command + "\r").encode("ascii"))
    ser.flush()

    time.sleep(wait)

    response = ser.read(ser.in_waiting or 1).decode(
        "utf-8", errors="replace"
    )

    if response.strip():
        print(response.strip())

    return response


def read_modem(ser, duration=0.3):
    """خواندن پیام‌های مودم."""

    time.sleep(duration)

    if ser.in_waiting:
        return ser.read(ser.in_waiting).decode(
            "utf-8", errors="replace"
        )

    return ""


def get_call_status(ser):
    """بررسی وضعیت تماس با AT+CLCC."""

    ser.reset_input_buffer()

    ser.write(b"AT+CLCC\r")
    ser.flush()

    response = read_modem(ser, 0.4)

    if response.strip():
        print("CLCC:", response.strip())

    for line in response.splitlines():

        line = line.strip()

        if line.startswith("+CLCC:"):

            try:
                fields = line.split(":", 1)[1].strip().split(",")
                status = int(fields[2].strip())

                return status

            except (IndexError, ValueError):
                continue

    return None


def wait_for_answer(ser):
    """انتظار تا پاسخ مخاطب."""

    print(
        f"\nمنتظر پاسخ مخاطب هستیم "
        f"(حداکثر {ANSWER_TIMEOUT} ثانیه)..."
    )

    start = time.monotonic()

    while time.monotonic() - start < ANSWER_TIMEOUT:

        incoming = read_modem(ser, 0.2)

        upper = incoming.upper()

        if incoming.strip():
            print("مودم:", incoming.strip())

        if any(x in upper for x in (
            "NO CARRIER",
            "BUSY",
            "NO ANSWER"
        )):
            print("تماس برقرار نشد.")
            return False

        if "CONNECT" in upper:
            print("مودم پیام CONNECT داد.")
            return True

        status = get_call_status(ser)

        if status == 0:
            print("تماس فعال است.")
            return True

        time.sleep(CALL_CHECK_INTERVAL)

    print("مهلت انتظار تمام شد.")

    return False


# =================================================
# مدیریت صف صوتی
# =================================================

def put_audio(audio_queue, data):
    """افزودن صوت به صف بدون مسدود کردن callback."""

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
    """دریافت صوت از صف یا تولید سکوت."""

    result = np.zeros(
        (frames, channels),
        dtype=np.float32
    )

    try:
        data = audio_queue.get_nowait()

        frames_to_copy = min(
            frames,
            data.shape[0]
        )

        channels_to_copy = min(
            channels,
            data.shape[1]
        )

        result[:frames_to_copy, :channels_to_copy] = (
            data[:frames_to_copy, :channels_to_copy]
        )

        # اگر ورودی mono باشد، آن را به stereo تبدیل کن
        if data.shape[1] == 1 and channels == 2:

            result[:frames_to_copy, 1] = (
                data[:frames_to_copy, 0]
            )

    except queue.Empty:
        pass

    return result


# =================================================
# دریافت صدای میکروفون کامپیوتر
# =================================================

def microphone_callback(indata, frames, time_info, status):
    """میکروفون کامپیوتر -> صدای تماس."""

    if status:
        print("وضعیت میکروفون:", status)

    if not running.is_set():
        return

    # ورودی mono را به stereo تبدیل کن
    mono = indata[:, :1].copy()

    stereo = np.repeat(
        mono,
        2,
        axis=1
    )

    put_audio(mic_to_call, stereo)


# =================================================
# پخش صدای میکروفون در خروجی USB
# =================================================

def usb_output_callback(outdata, frames, time_info, status):
    """صدای میکروفون -> خروجی USB -> مخاطب."""

    if status:
        print("وضعیت خروجی USB:", status)

    outdata[:] = get_audio(
        mic_to_call,
        frames,
        CHANNELS
    )


# =================================================
# دریافت صدای مخاطب از USB
# =================================================

def usb_input_callback(indata, frames, time_info, status):
    """صدای مخاطب -> میکروفون USB."""

    if status:
        print("وضعیت ورودی USB:", status)

    if not running.is_set():
        return

    # صدای مخاطب را برای بلندگوی کامپیوتر ارسال کن
    data = indata.copy()

    if data.shape[1] == 1:

        data = np.repeat(
            data,
            2,
            axis=1
        )

    put_audio(
        call_to_speaker,
        data
    )


# =================================================
# پخش صدای مخاطب در بلندگوی معمولی کامپیوتر
# =================================================

def speaker_callback(outdata, frames, time_info, status):
    """صدای USB -> بلندگوی معمولی کامپیوتر."""

    if status:
        print("وضعیت بلندگو:", status)

    outdata[:] = get_audio(
        call_to_speaker,
        frames,
        CHANNELS
    )


# =================================================
# شروع مکالمه زنده
# =================================================

def start_live_audio():

    print("\nشروع مکالمه زنده...")

    running.set()

    mic_stream = None
    usb_output_stream = None
    usb_input_stream = None
    speaker_stream = None

    try:

        # -----------------------------------------
        # میکروفون کامپیوتر
        # -----------------------------------------

        mic_stream = sd.InputStream(
            device=USB_INPUT_DEVICE,
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=microphone_callback
        )

        # -----------------------------------------
        # ارسال صدای میکروفون به مودم
        # -----------------------------------------

        usb_output_stream = sd.OutputStream(
            device=USB_OUTPUT_DEVICE,
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=usb_output_callback
        )

        # -----------------------------------------
        # دریافت صدای مخاطب از مودم
        # -----------------------------------------

        usb_input_stream = sd.InputStream(
            device=USB_INPUT_DEVICE,
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=usb_input_callback
        )

        # -----------------------------------------
        # پخش صدای مخاطب در بلندگوی معمولی
        # -----------------------------------------

        speaker_stream = sd.OutputStream(
            device=PC_SPEAKER_DEVICE,
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=speaker_callback
        )

        # شروع همه جریان‌ها
        mic_stream.start()
        usb_output_stream.start()

        usb_input_stream.start()
        speaker_stream.start()

        print("\n===================================")
        print("مکالمه زنده برقرار است.")
        print("برای قطع تماس Ctrl+C را فشار دهید.")
        print("===================================\n")

        while running.is_set():
            time.sleep(0.5)

    finally:

        running.clear()

        for stream in (
            mic_stream,
            usb_output_stream,
            usb_input_stream,
            speaker_stream
        ):

            if stream is not None:

                try:
                    stream.stop()
                except Exception:
                    pass

                try:
                    stream.close()
                except Exception:
                    pass

        print("جریان‌های صوتی بسته شدند.")


# =================================================
# برنامه اصلی
# =================================================

def main():
    global USB_INPUT_DEVICE
    global USB_OUTPUT_DEVICE
    global PC_SPEAKER_DEVICE

    USB_INPUT_DEVICE = find_device(
        "Microphone (2- USB PnP Sound Device)",
        "input",
        1
    )

    USB_OUTPUT_DEVICE = find_device(
        "Speakers (2- USB PnP Sound Device)",
        "output",
        2
    )

    PC_SPEAKER_DEVICE = find_device(
        "Microsoft Sound Mapper - Output",
        "output",
        2
    )

    ser = None
    call_started = False

    try:

        # بررسی دستگاه‌های صوتی
        print("\nدستگاه میکروفون:")
        print(sd.query_devices(USB_INPUT_DEVICE))

        print("\nدستگاه خروجی USB:")
        print(sd.query_devices(USB_OUTPUT_DEVICE))

        print("\nدستگاه بلندگوی معمولی:")
        print(sd.query_devices(PC_SPEAKER_DEVICE))

        # -----------------------------------------
        # اتصال به مودم
        # -----------------------------------------

        print(f"\nاتصال به {PORT}...")

        ser = serial.Serial(
            PORT,
            BAUDRATE,
            timeout=0.2,
            write_timeout=2
        )

        time.sleep(1)

        response = send_at(
            ser,
            "AT",
            0.5
        )

        if "OK" not in response.upper():
            raise RuntimeError(
                "مودم به فرمان AT پاسخ نداد."
            )

        # -----------------------------------------
        # شماره‌گیری
        # -----------------------------------------

        response = send_at(
            ser,
            f"ATD{PHONE_NUMBER};",
            1.0
        )

        call_started = True

        if any(word in response.upper() for word in (
            "ERROR",
            "BUSY",
            "NO CARRIER"
        )):
            print("شماره‌گیری موفق نبود.")
            return

        # -----------------------------------------
        # انتظار برای پاسخ
        # -----------------------------------------

        if not wait_for_answer(ser):
            return

        # مکث برای آماده شدن مسیر صوتی
        time.sleep(1)

        # -----------------------------------------
        # شروع مکالمه زنده
        # -----------------------------------------

        start_live_audio()

    except KeyboardInterrupt:

        print("\nمکالمه توسط کاربر متوقف شد.")

    except Exception as exc:

        print(
            f"\nخطا: {type(exc).__name__}: {exc}"
        )

    finally:

        running.clear()

        if ser is not None and ser.is_open:

            if call_started:

                try:
                    send_at(
                        ser,
                        "ATH",
                        0.5
                    )

                except Exception as exc:
                    print("خطا هنگام قطع تماس:", exc)

            ser.close()

        print("\nپورت سریال بسته شد.")


if __name__ == "__main__":
    main()