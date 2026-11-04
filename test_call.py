
import time
import serial

PORT = "COM5"
BAUD = 115200
PHONE = "+989025919234"

def send_command(ser, cmd, timeout=2):
    ser.reset_input_buffer()
    ser.write((cmd + "\r").encode("ascii"))
    ser.flush()

    deadline = time.time() + timeout
    response = bytearray()

    while time.time() < deadline:
        data = ser.read(ser.in_waiting or 1)
        if data:
            response.extend(data)
            upper = response.upper()
            if b"\nOK\r\n" in upper or b"\nERROR\r\n" in upper:
                break

    result = response.decode("utf-8", errors="replace").strip()
    print(f"> {cmd}\n{result}")
    return result

def main():
    with serial.Serial(PORT, BAUD, timeout=0.3) as ser:
        time.sleep(0.5)
        print(send_command(ser, "AT"))

        input("Press Enter to call the destination number...")

        result = send_command(ser, f"ATD{PHONE};", timeout=5)
        if "ERROR" in result.upper():
            print("Call command failed.")
            return

        print("\nMonitoring call. Press Ctrl+C to hang up.")

        try:
            while True:
                time.sleep(2)
                result = send_command(ser, "AT+CLCC", timeout=2)

                if "ERROR" in result.upper():
                    print("Could not query call status; continuing.")
                    continue

                # No +CLCC line means there are no active calls.
                if "+CLCC:" not in result:
                    print("No active call detected. Exiting.")
                    break

        except KeyboardInterrupt:
            print("\nManual hang-up requested.")

        finally:
            send_command(ser, "ATH", timeout=3)
            print("Call monitoring ended.")

if __name__ == "__main__":
    main()
