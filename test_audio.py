#
# import time
# import serial
#
# PORT = "COM5"
# BAUD = 115200
#
# COMMANDS = [
#     "AT",
#     "ATI",
#     "AT+CPIN?",
#     "AT+CREG?",
#     "AT+CSQ",
#     "AT+CMEDPLAY=?",
#     "AT+CMEDPLAY?",
#     "AT+CFSLFILE",
#     "AT+CTTS=?",
#     "AT+CTTS?",
# ]
#
# def read_response(ser, timeout=3):
#     deadline = time.time() + timeout
#     result = bytearray()
#
#     while time.time() < deadline:
#         waiting = ser.in_waiting
#         data = ser.read(waiting if waiting else 1)
#         if data:
#             result.extend(data)
#             text = result.upper()
#             if b"\nOK\r\n" in text or b"\nERROR\r\n" in text:
#                 break
#             if b"+CME ERROR:" in text:
#                 time.sleep(0.1)
#                 break
#
#     return result.decode("utf-8", errors="replace").strip()
#
# with serial.Serial(PORT, BAUD, timeout=0.2) as ser:
#     time.sleep(0.5)
#
#     for command in COMMANDS:
#         ser.reset_input_buffer()
#         print(f"\n> {command}")
#         ser.write((command + "\r").encode("ascii"))
#         ser.flush()
#         print(read_response(ser))
#
# print("\nDiagnostic complete.")


import sounddevice as sd

print("\n========== INPUT DEVICES ==========")
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0:
        print(
            f"Index: {i} | "
            f"Name: {d['name']} | "
            f"Channels: {d['max_input_channels']} | "
            f"Rate: {d['default_samplerate']}"
        )

print("\n========== OUTPUT DEVICES ==========")
for i, d in enumerate(sd.query_devices()):
    if d["max_output_channels"] > 0:
        print(
            f"Index: {i} | "
            f"Name: {d['name']} | "
            f"Channels: {d['max_output_channels']} | "
            f"Rate: {d['default_samplerate']}"
        )