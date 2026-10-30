"""Pipecat 1.13 handoff experiment. Real local WebRTC; deterministic model substitutes.
No external services, credentials, repository edits, or installed-package patches.
"""

import argparse
import asyncio
from dataclasses import dataclass
import json
from importlib.metadata import version
import platform
from pathlib import Path
import sys
import time
import wave
from uuid import uuid4

import numpy as np
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from loguru import logger
from av import AudioResampler

from pipecat.frames.frames import (
    ControlFrame,
    InterruptionFrame,
    SpeechOutputAudioRawFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import (
    SmallWebRTCTransport,
    SmallWebRTCOutputTransport,
)
from pipecat.workers.runner import WorkerRunner

RESULTS_ROOT = None
RUN_ID = None
RATE = 24000


def pcm(hz, seconds, rate):
    x = np.arange(round(seconds * rate)) / rate
    return np.round(5000 * np.sin(2 * np.pi * hz * x)).astype("<i2").tobytes()


def tone_label(audio, rate):
    x = np.asarray(audio, dtype=float).reshape(-1)
    if len(x) < 40 or np.sqrt(np.mean(x * x)) < 180:
        return "silence"
    t = np.arange(len(x)) / rate
    energies = [abs(np.dot(x, np.exp(-2j * np.pi * hz * t))) for hz in (440, 880)]
    return "pp" if energies[0] > energies[1] else "cascade"


@dataclass
class PersonaAudio(SpeechOutputAudioRawFrame):
    epoch: int = -1


@dataclass
class Fence(ControlFrame):
    token: str = ""


class ToneTTS(TTSService):
    """Exercise real Pipecat TTS context/playback code without a model service."""

    def __init__(self, session):
        super().__init__(
            sample_rate=22050,
            push_start_frame=True,
            push_stop_frames=True,
            stop_frame_timeout_s=0.1,
            settings=TTSSettings(model=None, voice=None, language=None),
        )
        self.session = session

    async def run_tts(self, text, context_id):
        epoch, duration = text.split(":")
        self.session.context_epochs[context_id] = int(epoch)
        self.session.event("tts_generated", context=context_id, epoch=int(epoch))
        data = pcm(880, float(duration), 22050)
        for i in range(0, len(data), 882):
            yield TTSAudioRawFrame(data[i : i + 882], 22050, 1, context_id=context_id)


class Identity(FrameProcessor):
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


class GuardedOutput(SmallWebRTCOutputTransport):
    """Branch-local admission guard. No changes to installed Pipecat sources.

    Uses client/params constructor fields from 1.13 only; transport/media queue
    internals are neither cleared nor replaced. Interruption does the clearing.
    """

    def __init__(self, client, params, session):
        super().__init__(client, params)
        self.session = session

    async def process_frame(self, frame, direction):
        s = self.session
        if s.guarded and direction == FrameDirection.DOWNSTREAM:
            source, epoch = None, None
            if isinstance(frame, PersonaAudio):
                source, epoch = "pp", frame.epoch
            elif isinstance(
                frame,
                (TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame, TTSTextFrame),
            ):
                source, epoch = "cascade", s.context_epochs.get(frame.context_id)
            if source and (source != s.owner or epoch != s.epoch):
                # Preserve common processor housekeeping for deliberately dropped data.
                await FrameProcessor.process_frame(self, frame, direction)
                s.event(
                    "stale_rejected", source=source, epoch=epoch, current_epoch=s.epoch
                )
                return
        await super().process_frame(frame, direction)


class Tail(FrameProcessor):
    def __init__(self, session):
        super().__init__()
        self.session = session

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, Fence):
            self.session.event("fence_played", token=frame.token)
            self.session.fences[frame.token].set()
        await self.push_frame(frame, direction)


class Session:
    def __init__(self, name, *, guarded=False, identity=False):
        self.name = name
        self.guarded = guarded
        self.identity = identity
        self.events = []
        self.raw = []
        self.remote = []
        self.tasks = []
        self.context_epochs = {}
        self.fences = {}
        self.flushes = {}
        self.epoch = 0
        self.owner = "pp"
        self.errors = []
        self.track_queue_peak = 0
        self.connections = []
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.pc.addTransceiver("audio", direction="recvonly")
        self.dc = self.pc.createDataChannel("pipecat")
        self.conn = SmallWebRTCConnection(ice_servers=[])

    def event(self, event, **kw):
        item = {"event": event, "t": time.perf_counter(), **kw}
        self.events.append(item)
        return item

    async def __aenter__(self):
        try:
            return await self._start()
        except BaseException:
            await self._cleanup()
            self._save()
            raise

    async def _start(self):
        @self.pc.on("connectionstatechange")
        def state():
            self.connections.append(self.pc.connectionState)

        @self.pc.on("track")
        def track_started(track):
            async def receive():
                resampler = AudioResampler(format="s16", layout="mono", rate=48000)
                try:
                    while True:
                        received = await track.recv()
                        for f in resampler.resample(received):
                            a = f.to_ndarray().reshape(-1).astype("<i2")
                            self.remote.append(
                                {
                                    "t": time.perf_counter(),
                                    "pts": f.pts,
                                    "rate": f.sample_rate,
                                    "samples": len(a),
                                    "audio": a,
                                }
                            )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.event("receiver_closed", kind=type(e).__name__)

            self.tasks.append(asyncio.create_task(receive()))

        await self.pc.setLocalDescription(await self.pc.createOffer())
        await self.conn.initialize(
            self.pc.localDescription.sdp, self.pc.localDescription.type
        )
        answer = self.conn.get_answer()
        await self.pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
        )
        params = TransportParams(
            audio_out_enabled=True,
            audio_out_sample_rate=RATE,
            audio_out_10ms_chunks=2,
            audio_in_enabled=False,
            audio_out_end_silence_secs=0,
        )
        self.transport = SmallWebRTCTransport(self.conn, params)
        if self.guarded:
            # Isolated output factory adaptation, pinned to the inspected 1.13 layout.
            self.transport._output = GuardedOutput(self.transport._client, params, self)
        self.output = self.transport.output()
        self.tts = ToneTTS(self)
        self.tail = Tail(self)

        @self.tts.event_handler("on_tts_request")
        async def tts_request(service, context_id, text):
            self.context_epochs[context_id] = int(text.split(":")[0])

        processors = [self.tts]
        if self.identity:
            processors.append(Identity())
        processors.extend([self.output, self.tail])
        self.worker = PipelineWorker(
            Pipeline(processors),
            params=PipelineParams(audio_out_sample_rate=RATE),
            enable_rtvi=False,
            enable_turn_tracking=False,
        )
        ready = asyncio.Event()

        @self.worker.event_handler("on_pipeline_started")
        async def started(w, f):
            ready.set()

        @self.worker.event_handler("on_pipeline_error")
        async def error(w, f):
            self.errors.append(str(f))
            self.event("pipeline_error", message=str(f))

        @self.output.event_handler("on_after_process_frame")
        async def processed(p, f):
            if isinstance(f, InterruptionFrame):
                self.event("flush_processed", frame_id=f.id)
                if f.id in self.flushes:
                    self.flushes[f.id].set()

        self.runner = WorkerRunner(handle_sigint=False)
        await self.runner.add_workers(self.worker)
        self.runner_task = asyncio.create_task(self.runner.run())
        await asyncio.wait_for(ready.wait(), 10)
        async with asyncio.timeout(10):
            while self.pc.connectionState != "connected" or len(self.remote) < 4:
                await asyncio.sleep(0.01)
        track = self.transport._client._audio_output_track
        original_recv = track.recv

        # Observation only: return exactly the same AudioFrame, with unchanged timing.
        async def observed_recv():
            self.track_queue_peak = max(self.track_queue_peak, len(track._chunk_queue))
            f = await original_recv()
            a = f.to_ndarray().reshape(-1).copy()
            self.raw.append(
                {
                    "t": time.perf_counter(),
                    "pts": f.pts,
                    "rate": f.sample_rate,
                    "audio": a,
                    "label": tone_label(a, f.sample_rate),
                }
            )
            return f

        track.recv = observed_recv

        async def keepalive():
            while True:
                if self.dc.readyState == "open":
                    self.dc.send("ping " + str(time.time()))
                await asyncio.sleep(2)

        self.tasks.append(asyncio.create_task(keepalive()))
        self.event("ready")
        return self

    async def __aexit__(self, *exc):
        await self._cleanup()
        self._save()

    async def _cleanup(self):
        if hasattr(self, "runner_task"):
            try:
                await asyncio.wait_for(self.runner.cancel(), 8)
                await asyncio.wait_for(self.runner_task, 8)
            except (Exception, asyncio.CancelledError) as error:
                self.event("cleanup_error", kind=type(error).__name__)
                self.runner_task.cancel()
                await asyncio.gather(self.runner_task, return_exceptions=True)
        # initialize() may have succeeded even when the worker never started.
        await self.conn.disconnect()
        await self.pc.close()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def _save(self):
        target = RESULTS_ROOT / self.name
        target.mkdir(parents=True, exist_ok=True)
        (target / "events.json").write_text(json.dumps(self.events, indent=2))
        for name, frames in [("sender", self.raw), ("receiver", self.remote)]:
            if not frames:
                continue
            with wave.open(str(target / (name + ".wav")), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(frames[0]["rate"])
                w.writeframes(
                    b"".join(f["audio"].astype("<i2").tobytes() for f in frames)
                )
        meta = {
            "run_id": RUN_ID,
            "name": self.name,
            "guarded": self.guarded,
            "identity": self.identity,
            "connections": self.connections,
            "track_queue_peak_10ms": self.track_queue_peak,
            "pipeline_errors": self.errors,
            "sender_timing": [
                {k: v for k, v in f.items() if k != "audio"} for f in self.raw
            ],
            "receiver_timing": [
                {k: v for k, v in f.items() if k != "audio"} for f in self.remote
            ],
        }
        (target / "timing.json").write_text(json.dumps(meta, indent=2))

    async def persona(self, duration=0.4, epoch=None):
        await self.output.send_audio(
            PersonaAudio(
                pcm(440, duration, RATE),
                RATE,
                1,
                epoch=self.epoch if epoch is None else epoch,
            )
        )

    async def speak(self, duration=0.4, epoch=None, token=None):
        frames = [TTSSpeakFrame(f"{self.epoch if epoch is None else epoch}:{duration}")]
        if token:
            self.fences[token] = asyncio.Event()
            frames.append(Fence(token))
        await self.worker.queue_frames(frames)

    async def switch(self, owner):
        self.owner = None
        self.epoch += 1
        requested = self.event("handoff_requested", owner=owner, epoch=self.epoch)
        f = InterruptionFrame()
        ack = asyncio.Event()
        self.flushes[f.id] = ack
        await self.worker.queue_frames([f])
        await asyncio.wait_for(ack.wait(), 2)
        self.owner = owner
        self.event("owner_granted", owner=owner, epoch=self.epoch)
        return requested

    async def wait_tone(self, label, after, timeout=2):
        async with asyncio.timeout(timeout):
            while not any(f["label"] == label and f["t"] >= after for f in self.raw):
                await asyncio.sleep(0.005)
        return next(f for f in self.raw if f["label"] == label and f["t"] >= after)


def receiver_tone_seconds(session, label):
    return sum(
        len(f["audio"]) / f["rate"]
        for f in session.remote
        if tone_label(f["audio"], f["rate"]) == label
    )


def stats(values):
    return {
        "count": len(values),
        "median": float(np.median(values)),
        "p95": float(np.percentile(values, 95)),
        "max": float(max(values)),
    }


async def main():
    checks = []
    summary = {
        "run_id": RUN_ID,
        "platform": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "checks": checks,
        "limits": [
            "Model audio is synthetic, not live PersonaPlex or Jetson.",
            "Peer is aiortc on this machine, not a ThinkPad browser or physical audio devices.",
        ],
    }

    def check(name, ok, **detail):
        entry = {"name": name, "passed": bool(ok), **detail}
        checks.append(entry)
        print(json.dumps(entry), flush=True)
        return bool(ok)

    for identity in (False, True):
        name = "identity_after_tts" if identity else "baseline"
        async with Session(name, identity=identity) as s:
            await s.persona(0.32)
            await asyncio.sleep(0.4)
            await s.speak(0.4, token="end")
            await asyncio.wait_for(s.fences["end"].wait(), 3)
            await asyncio.sleep(0.25)
            pp = receiver_tone_seconds(s, "pp")
            cascade = receiver_tone_seconds(s, "cascade")
            check(
                name + "_both_sources_received",
                pp > 0.25 and cascade > 0.32,
                pp_seconds=pp,
                cascade_seconds=cascade,
            )
            check(name + "_no_pipeline_errors", not s.errors)
    async with Session("negative_without_flush") as s:
        await s.persona(1.0)
        await asyncio.sleep(0.1)
        request = s.event("unsafe_switch")
        await s.speak(0.3, token="end")
        first = await s.wait_tone("cascade", request["t"])
        delay = (first["t"] - request["t"]) * 1000
        summary["negative_without_flush_ms"] = delay
        check("negative_control_exposes_fifo_backlog", delay > 600, delay_ms=delay)
        await asyncio.wait_for(s.fences["end"].wait(), 3)
        await asyncio.sleep(0.15)
    async with Session("guarded_handoffs", guarded=True) as s:
        transitions = []
        gaps = []
        tails = []
        acks = []
        for i in range(30):
            for target in ("cascade", "pp"):
                # Current source has excess queued audio when deliberately interrupted.
                if s.owner == "pp":
                    await s.persona(0.7)
                else:
                    await s.speak(0.7)
                current = s.owner
                await s.wait_tone(current, time.perf_counter())
                await asyncio.sleep(0.035)
                e = await s.switch(target)
                flush = s.events[-2]
                acks.append((flush["t"] - e["t"]) * 1000)
                if target == "pp":
                    await s.persona(0.22)
                else:
                    await s.speak(0.22)
                first = await s.wait_tone(target, e["t"])
                await asyncio.sleep(0.035)
                old = [
                    f
                    for f in s.raw
                    if f["label"] == current and e["t"] <= f["t"] < first["t"] + 0.025
                ]
                prior = [
                    f for f in s.raw if f["label"] == current and f["t"] < first["t"]
                ]
                tail = max([0] + [(f["t"] - e["t"]) * 1000 for f in old])
                gap = (first["t"] - prior[-1]["t"]) * 1000 - 10 if prior else None
                transitions.append(
                    {
                        "from": current,
                        "to": target,
                        "requested": e["t"],
                        "first": first["t"],
                        "switch_to_audio_ms": (first["t"] - e["t"]) * 1000,
                        "old_tail_ms": tail,
                        "gap_ms": gap,
                    }
                )
                tails.append(tail)
                if gap is not None:
                    gaps.append(max(0, gap))
            if i % 10 == 9:
                print(f"completed {2 * (i + 1)} guarded transitions", flush=True)
        await asyncio.sleep(0.3)
        check("sixty_guarded_transitions_completed", len(transitions) == 60)
        check(
            "switch_output_gap_p95_under_300ms",
            np.percentile(gaps, 95) <= 300,
            metrics_ms=stats(gaps),
        )
        check(
            "old_sender_audio_tail_p95_under_300ms",
            np.percentile(tails, 95) <= 300,
            metrics_ms=stats(tails),
        )
        check(
            "same_webrtc_connection",
            s.connections.count("connected") == 1,
            states=s.connections,
        )
        # Deliberately send late audio through both routes after revoking their epochs.
        old_epoch = s.epoch
        e = await s.switch("cascade")
        before = len([x for x in s.events if x["event"] == "stale_rejected"])
        await s.persona(0.18, epoch=old_epoch)
        s.context_epochs["late"] = old_epoch
        await s.output.send_audio(
            TTSAudioRawFrame(pcm(880, 0.18, 22050), 22050, 1, context_id="late")
        )
        await s.output.queue_frame(TTSStartedFrame(context_id="late"))
        await s.output.queue_frame(TTSStoppedFrame(context_id="late"))
        await asyncio.sleep(0.12)
        rejected = len([x for x in s.events if x["event"] == "stale_rejected"]) - before
        check("late_audio_and_tts_lifecycle_rejected", rejected == 4, rejected=rejected)
        await s.speak(0.34, token="final")
        await asyncio.wait_for(s.fences["final"].wait(), 3)
        await asyncio.sleep(0.25)
        # A final fence follows PCM delivery into WebRTC, not model generation.
        fence = next(x for x in reversed(s.events) if x["event"] == "fence_played")
        gen = next(x for x in reversed(s.events) if x["event"] == "tts_generated")
        check(
            "playback_fence_after_generation",
            fence["t"] - gen["t"] > 0.25,
            separation_ms=(fence["t"] - gen["t"]) * 1000,
        )
        check("no_guarded_pipeline_errors", not s.errors)
        summary["guarded"] = {
            "transitions": transitions,
            "gap_ms": stats(gaps),
            "tail_ms": stats(tails),
            "flush_ack_ms": stats(acks),
            "track_queue_peak_10ms": s.track_queue_peak,
            "receiver_frames": len(s.remote),
        }
        check(
            "receiver_rtp_timestamps_continuous",
            len(s.remote) > 1
            and all(
                b["pts"] - a["pts"] == a["samples"]
                for a, b in zip(s.remote, s.remote[1:])
            ),
        )
    async with Session("delayed_backend", guarded=True) as s:
        await s.switch("cascade")
        old_epoch = s.epoch

        async def delayed():
            await asyncio.sleep(0.12)
            await s.speak(0.3, epoch=old_epoch, token="stale_backend_done")

        request = asyncio.create_task(delayed())
        e = await s.switch("pp")
        await s.persona(0.5)
        await request
        await asyncio.wait_for(s.fences["stale_backend_done"].wait(), 3)
        await asyncio.sleep(0.2)
        check(
            "delayed_backend_does_not_speak_after_return",
            not any(f["label"] == "cascade" for f in s.raw),
        )
        check(
            "stale_backend_lifecycle_and_audio_rejected",
            len([x for x in s.events if x["event"] == "stale_rejected"]) >= 3,
        )
        check("delayed_backend_no_pipeline_errors", not s.errors)
    summary["all_passed"] = all(c["passed"] for c in checks)
    summary["versions"] = {}
    for name in ("pipecat-ai", "aiortc", "av"):
        summary["versions"][name] = version(name)
    (RESULTS_ROOT / "summary.json").write_text(json.dumps(summary, indent=2))
    print(
        "RESULT",
        json.dumps({"passed": sum(c["passed"] for c in checks), "checks": len(checks)}),
        flush=True,
    )
    if not summary["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New results directory; existing directories are never overwritten.",
    )
    args = parser.parse_args()
    if version("pipecat-ai") != "1.13.0":
        parser.error(
            "This experiment uses inspected Pipecat 1.13.0 interfaces. Use an isolated compatible environment."
        )
    RESULTS_ROOT = args.output_dir.resolve()
    RESULTS_ROOT.mkdir(parents=True, exist_ok=False)
    RUN_ID = uuid4().hex
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    asyncio.run(main())
