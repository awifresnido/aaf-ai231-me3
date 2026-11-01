"""Profile the installed Pipecat Smart Turn implementation using a test WAV.

Run with the Pipecat venv on the Pi. Uses private analyzer APIs only in this
standalone profiling process; never patches the running voice-agent process.
"""
import argparse
import asyncio
import cProfile
import gc
import io
import json
import os
from pathlib import Path
import pstats
from statistics import median
import time
import wave

import numpy as np
import pipecat.audio.turn.smart_turn.local_smart_turn_v3 as smart


class TimedSession:
    def __init__(self, session, timings):
        self.session, self.timings = session, timings

    def run(self, *args, **kwargs):
        start = time.perf_counter()
        result = self.session.run(*args, **kwargs)
        self.timings["onnx_ms"] = (time.perf_counter() - start) * 1000
        return result


async def profile(audio, threads, repeats, include_cprofile):
    analyzer = smart.LocalSmartTurnAnalyzerV3(cpu_count=threads)
    timings = {}
    original_features = smart.compute_whisper_log_mel_features
    original_resample = analyzer._resample_to_model_rate

    def features(*args, **kwargs):
        start = time.perf_counter()
        result = original_features(*args, **kwargs)
        timings["features_ms"] = (time.perf_counter() - start) * 1000
        return result

    def resample(*args, **kwargs):
        start = time.perf_counter()
        result = original_resample(*args, **kwargs)
        timings["resample_ms"] = (time.perf_counter() - start) * 1000
        return result

    smart.compute_whisper_log_mel_features = features
    analyzer._resample_to_model_rate = resample
    analyzer._session = TimedSession(analyzer._session, timings)
    rows = []
    loop = asyncio.get_running_loop()
    try:
        for iteration in range(repeats + 2):
            queued_at = time.perf_counter()

            def predict():
                started = time.perf_counter()
                result = analyzer._predict_endpoint(audio)
                total = (time.perf_counter() - started) * 1000
                return dict(timings, predict_ms=total,
                            executor_queue_ms=(started - queued_at) * 1000,
                            probability=result["probability"], prediction=result["prediction"])

            row = await loop.run_in_executor(analyzer._model_executor, predict)
            row["caller_elapsed_ms"] = (time.perf_counter() - queued_at) * 1000
            row["other_ms"] = row["predict_ms"] - sum(row[k] for k in ("features_ms", "onnx_ms", "resample_ms"))
            if iteration >= 2:
                rows.append(row)
        medians = {key: median(row[key] for row in rows) for key in rows[0] if key != "prediction"}
        result = dict(threads=threads, warmups=2, samples=rows, median=medians,
                      min_predict_ms=min(row["predict_ms"] for row in rows),
                      max_predict_ms=max(row["predict_ms"] for row in rows))
        if include_cprofile:
            profiler = cProfile.Profile()
            profiler.enable()
            for _ in range(3):
                analyzer._predict_endpoint(audio)
            profiler.disable()
            output = io.StringIO()
            pstats.Stats(profiler, stream=output).sort_stats("cumulative").print_stats(18)
            result["cprofile"] = output.getvalue()
        return result
    finally:
        smart.compute_whisper_log_mel_features = original_features
        analyzer._model_executor.shutdown(wait=True)
        # Release ORT workers before constructing the next thread-count session.
        analyzer._session = None
        analyzer._resample_to_model_rate = None
        del analyzer
        gc.collect()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", required=True)
    parser.add_argument("--threads", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--cprofile", action="store_true")
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    with wave.open(args.wav, "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
            raise SystemExit("Use mono 16 kHz signed 16-bit PCM WAV")
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    info = dict(wav=args.wav, audio_seconds=len(audio) / 16000,
                note="Synthetic/offline prediction timing while the live agent remains running",
                env={key: os.getenv(key) for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")})
    try:
        from threadpoolctl import threadpool_info
        info["threadpools"] = threadpool_info()
    except ImportError:
        info["threadpools"] = "threadpoolctl unavailable"
    info["results"] = []
    for threads in args.threads:
        result = await profile(audio, threads, args.repeats, args.cprofile)
        info["results"].append(result)
        print(json.dumps(dict(threads=threads, median=result["median"],
                              min_predict_ms=result["min_predict_ms"],
                              max_predict_ms=result["max_predict_ms"])), flush=True)
    Path(args.json_output).write_text(json.dumps(info, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
