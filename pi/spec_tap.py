"""Wiring taps for the speculative-Laya layer (bot.py inserts this processor).

SpecTap sits between the transport and the STT service. It:
  - forwards every frame unchanged (transparent),
  - taps InputAudioRawFrame PCM into SpeculativeLaya (audio path: whisper
    partial transcription, used when the ASR backend has no interim text),
  - taps InterimTranscriptionFrame text into SpeculativeLaya (text path:
    streaming ASR backends such as Nemotron already emit partial transcripts —
    classifying those costs zero extra ASR),
  - reacts to VAD start/stop to begin/end speculation per turn,
  - records its own diagnostics only.
"""
from loguru import logger
from pipecat.frames.frames import (Frame, InputAudioRawFrame,
                                   InterimTranscriptionFrame,
                                   VADUserStartedSpeakingFrame,
                                   VADUserStoppedSpeakingFrame)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class SpecTap(FrameProcessor):
    def __init__(self, spec, *, timing_observer=None, stt=None, **kwargs):
        super().__init__(**kwargs)
        self.spec = spec
        self.timing = timing_observer
        self.stt = stt

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            # 16 kHz mono PCM16 expected by the speculator
            if frame.sample_rate == 16000 and frame.num_channels == 1:
                pcm = bytes(frame.audio)
                self.spec.push_audio(pcm)
                if self.stt is not None and hasattr(self.stt, "push_partial_audio"):
                    self.stt.push_partial_audio(pcm)
        elif isinstance(frame, InterimTranscriptionFrame):
            # Streaming ASR partial: classify the partial text directly —
            # no extra ASR round-trip needed.
            text = (getattr(frame, "text", "") or "").strip()
            if text:
                self.spec.push_partial_text(text)
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            turn = self.timing.turn if self.timing else None
            self.spec.on_user_started_speaking(turn)
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            turn = self.timing.turn if self.timing else None
            self.spec.on_user_stopped_speaking(turn)
        await self.push_frame(frame, direction)
