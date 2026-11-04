"""Wiring taps for the speculative-Laya layer (bot.py inserts this processor).

SpecTap sits between the transport and the STT service. It:
  - forwards every frame unchanged (transparent),
  - taps InputAudioRawFrame PCM into SpeculativeLaya,
  - reacts to VAD start/stop to begin/end speculation per turn,
  - records its own diagnostics only.
"""
from loguru import logger
from pipecat.frames.frames import (Frame, InputAudioRawFrame,
                                   VADUserStartedSpeakingFrame,
                                   VADUserStoppedSpeakingFrame)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class SpecTap(FrameProcessor):
    def __init__(self, spec, *, timing_observer=None, **kwargs):
        super().__init__(**kwargs)
        self.spec = spec
        self.timing = timing_observer

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            # 16 kHz mono PCM16 expected by the speculator
            if frame.sample_rate == 16000 and frame.num_channels == 1:
                self.spec.push_audio(bytes(frame.audio))
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            turn = self.timing.turn if self.timing else None
            self.spec.on_user_started_speaking(turn)
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            turn = self.timing.turn if self.timing else None
            self.spec.on_user_stopped_speaking(turn)
        await self.push_frame(frame, direction)
