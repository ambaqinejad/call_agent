
import time
import serial
from serial.tools import list_ports

PORT = "COM5"
BAUD_RATES = [115200, 9600, 57600, 38400, 19200]

def main():
    print("=== Available serial ports ===")
    for p in list_ports.comports():
        print(f"{p.device}: {p.description}")

    for baud in BAUD_RATES:
        print(f"\n=== Testing {PORT} at {baud} baud ===")

        try:
            with serial.Serial(
                port=PORT,
                baudrate=baud,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=1,
                write_timeout=2
            ) as ser:
                time.sleep(0.5)
                ser.reset_input_buffer()

                ser.write(b"AT\r")
                ser.flush()
                time.sleep(1)

                response = ser.read(ser.in_waiting or 1)
                print("AT response:", repr(response))

                if b"OK" not in response.upper():
                    print("No valid AT response at this baud rate.")
                    continue

                commands = [
                    "ATI",
                    "AT+CGMI",
                    "AT+CGMM",
                    "AT+CGMR",
                    "AT+CCMXPLAYWAV=?",
                    "AT+CCMXPLAY=?",
                    "AT+CLAC",
                ]

                for cmd in commands:
                    ser.reset_input_buffer()
                    print(f"\n> {cmd}")
                    ser.write((cmd + "\r").encode("ascii"))
                    ser.flush()

                    deadline = time.time() + 3
                    chunks = []

                    while time.time() < deadline:
                        data = ser.read(ser.in_waiting or 1)
                        if data:
                            chunks.append(data)
                            text = b"".join(chunks).upper()
                            if b"\nOK\r" in text or b"\nERROR\r" in text:
                                break

                    print(b"".join(chunks).decode(
                        "utf-8", errors="replace"
                    ).strip() or "(no response)")

                print("\nDiagnostics finished.")
                return

        except serial.SerialException as e:
            print("Serial error:", e)
            print("Close any serial terminal using COM5 first.")

    print("\nCould not establish AT communication.")
    print("Check the port, baud rate and device documentation.")

if __name__ == "__main__":
    main()
