import serial
import time

PORT = "COM5"
BAUDRATE = 115200

try:
    print("در حال اتصال به مودم...")

    ser = serial.Serial(
        PORT,
        BAUDRATE,
        timeout=1,
        write_timeout=2
    )

    print("اتصال موفق شد.")

    ser.write(b"AT\r")
    ser.flush()

    time.sleep(1)

    print("پاسخ مودم:")
    print(ser.read_all().decode("utf-8", errors="replace"))

    ser.close()
    print("پورت بسته شد.")

except Exception as e:
    print(f"خطا: {type(e).__name__}: {e}")