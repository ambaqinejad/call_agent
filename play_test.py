
import sounddevice as sd
import soundfile as sf
import numpy as np
from scipy.signal import resample_poly
from math import gcd

FILE = r".\test.wav"
OUTPUT_DEVICE = 17
TARGET_RATE = 48000

audio, sample_rate = sf.read(FILE, dtype="float32", always_2d=True)

print(f"Original sample rate: {sample_rate}")
print(f"Channels: {audio.shape[1]}")
print(f"Output device: {sd.query_devices(OUTPUT_DEVICE)}")

# تبدیل نرخ نمونه‌برداری فایل به 48000 هرتز
if sample_rate != TARGET_RATE:
    g = gcd(sample_rate, TARGET_RATE)
    audio = resample_poly(
        audio,
        TARGET_RATE // g,
        sample_rate // g,
        axis=0
    ).astype(np.float32)

# پخش از کارت صدای USB PnP
sd.play(audio, samplerate=TARGET_RATE, device=OUTPUT_DEVICE)
sd.wait()

print("Playback finished.")
