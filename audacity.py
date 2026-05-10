import numpy as np
import wave

# === SETTINGS ===
sample_rate = 44100      # Hz
duration = 0.5           # seconds per tone
amplitude = 32767        # max for 16-bit audio
flag = "CTF{audio_hidden}"

# Frequency mapping for each character
freq_map = {
    'C': 500, 'T': 600, 'F': 700, '{': 800, 'A': 900, 'U': 1000,
    'D': 1100, 'I': 1200, 'O': 1300, '_': 1400, 'H': 1500,
    'E': 1600, 'N': 1700, '}': 1800
}

# === GENERATE AUDIO ===
audio_data = np.array([], dtype=np.int16)

for char in flag.upper():   # convert to uppercase for mapping
    freq = freq_map.get(char, 1000)  # fallback frequency
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    wave_data = (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.int16)
    audio_data = np.concatenate((audio_data, wave_data))

# === SAVE TO WAV ===
wav_path = "ctf_audio_hidden.wav"
with wave.open(wav_path, "w") as wav_file:
    wav_file.setnchannels(1)   # mono
    wav_file.setsampwidth(2)   # 16-bit
    wav_file.setframerate(sample_rate)
    wav_file.writeframes(audio_data.tobytes())

print(f"[+] WAV file created: {wav_path}")