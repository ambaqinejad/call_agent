import sounddevice as sd

print("\n=== دستگاه‌های صوتی موجود ===\n")

devices = sd.query_devices()

for i, device in enumerate(devices):
    if device["max_output_channels"] > 0:
        print(
            f"Index: {i} | "
            f"Name: {device['name']} | "
            f"Channels: {device['max_output_channels']} | "
            f"Default Rate: {device['default_samplerate']}"
        )