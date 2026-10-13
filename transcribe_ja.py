from faster_whisper import WhisperModel

model = WhisperModel("small", device="cpu", compute_type="int8")
segments, info = model.transcribe("reference.wav", language="ja")
text = "".join([segment.text for segment in segments])
print("TRANSCRIPTION:", text)
