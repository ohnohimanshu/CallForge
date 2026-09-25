import wave
import sys
import logging

try:
    with wave.open("reference.wav", 'rb') as fin:
        frames = fin.getnframes()
        rate = fin.getframerate()
        print(f"Original frames: {frames}, rate: {rate}")
        max_frames = 6 * rate
        out_frames = min(frames, max_frames)
        data = fin.readframes(out_frames)
        
        with wave.open("short_reference.wav", 'wb') as fout:
            fout.setnchannels(fin.getnchannels())
            fout.setsampwidth(fin.getsampwidth())
            fout.setframerate(rate)
            fout.writeframes(data)
    print("Saved short_reference.wav")

    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, info = model.transcribe("short_reference.wav", language="ja")
    text = "".join([s.text for s in segments])
    print(f"TRANSCRIPTION:{text}")
    with open("transcript.txt", "w") as f:
        f.write(text)
except Exception as e:
    print(f"Error: {e}")
