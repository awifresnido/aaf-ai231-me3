"""Headless integration test: drive the REAL bot PP code path end-to-end.

Replays synthetic speech-shaped audio through:
    PersonaPlexClient.send_pcm (ogg/opus mux) -> PP websocket (tunnel)
    -> PP generates -> decode (exact page parser) -> PPOutputGate.on_pp_audio
    -> fake transport.send_audio (records OutputAudioRawFrame)

Proves the conversation loop works without a human or browser. Asserts:
  - PP handshake completes
  - PP returns audio packets (speech) AND text transcript
  - decoded PCM reaches the output gate
  - writes the decoded reply to /tmp/pp_conversation_reply.wav for inspection

Run on the Pi (PP tunnel must be up):
  ~/pipecat-quickstart/server/.venv/bin/python test_pp_conversation.py
"""

import asyncio
import io
import sys
import time
import wave

import numpy as np

sys.path.insert(0, "/home/aldwinrpi4/handoff-lab/pi")
import bot_handoff as bh  # noqa: E402


class FakeOutput:
    """Records OutputAudioRawFrames instead of pushing to WebRTC."""

    def __init__(self):
        self.frames = []  # list of np.int16 arrays (24k mono)

    async def send_audio(self, frame):
        self.frames.append(np.frombuffer(frame.audio, dtype=np.int16))


def synth_speech(dur_s: float = 4.0, rate: int = 24000) -> np.ndarray:
    """Speech-cadence noise burst (proven to trigger PP in duplex5)."""
    total = int(rate * dur_s)
    env = np.zeros(total, dtype=np.float32)
    pos = 0
    while pos < total:
        on = min(int(rate * 0.8), total - pos)
        env[pos:pos + on] = 0.35
        pos += on + int(rate * 0.25)
    pcm = (env * np.random.randn(total).astype(np.float32) * 32767 * 0.4).astype(np.int16)
    return pcm


async def main():
    state = bh.HandoffState()
    out = FakeOutput()
    gate = bh.PPOutputGate(state, out)  # fake transport exposing send_audio

    texts = []
    seg_ends = []

    async def on_text(t):
        texts.append(t)

    async def on_seg_end():
        seg_ends.append(time.monotonic())

    pp = bh.PersonaPlexClient(
        "http://127.0.0.1:8998/api/chat?voice_prompt=NATF0.pt"
        "&text_prompt=You%20are%20a%20friendly%20frontdesk.%20Greet%20the%20user.",
        gate.on_pp_audio,
        on_text,
        on_seg_end,
    )
    pp.on_audio = gate.on_pp_audio  # mirror run_bot wiring

    print("[test] connecting to PP ...")
    await pp.start()
    print("[test] handshake OK")

    state.owner = bh.Owner.PERSONAPLEX
    state.pp_session_id = pp.session_id

    # stream synthetic speech in 20ms chunks (mimics the MicTee cadence)
    pcm = synth_speech()
    chunk = bh.PP_SAMPLE_RATE // 50
    print(f"[test] streaming {len(pcm)/bh.PP_SAMPLE_RATE:.1f}s synthetic speech ...")
    for i in range(0, len(pcm), chunk):
        await pp.send_pcm(pcm[i:i + chunk])
        await asyncio.sleep(0.02)

    # listen for PP response (longer window; PP needs a moment to produce audio)
    print("[test] listening for PP reply ...")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if texts and out.frames:
            break
        await asyncio.sleep(0.5)

    audio_samples = sum(len(f) for f in out.frames)
    reply_text = "".join(texts)

    print("[test] ============ RESULTS ============")
    print(f"[test] text transcript: {reply_text!r}")
    print(f"[test] audio frames: {len(out.frames)}, samples: {audio_samples} "
          f"({audio_samples/bh.PP_SAMPLE_RATE:.2f}s @ 24k)")
    print(f"[test] segment ends: {len(seg_ends)}")

    # write reply WAV for offline listening
    if out.frames:
        all_pcm = np.concatenate(out.frames)
        with wave.open("/tmp/pp_conversation_reply.wav", "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(bh.PP_SAMPLE_RATE)
            w.writeframes(all_pcm.tobytes())
        print("[test] wrote /tmp/pp_conversation_reply.wav")
    else:
        print("[test] NO AUDIO decoded")

    await pp.close()

    assert reply_text.strip(), "PP returned no text transcript"
    assert len(out.frames) > 0, "PP returned no audible audio"
    print("[test] PASS: PP conversed (speech + text reached the output)")


if __name__ == "__main__":
    asyncio.run(main())
