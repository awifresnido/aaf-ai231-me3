# Jetson capacity for CUDA Laya — 2026-11-01

**Finding: the current stock PyTorch loader has inadequate memory headroom
beside the speech services. A memory-optimized FP16 deployment remains a
candidate for an isolated feasibility test, not a demonstrated fit.** Laya
was not transferred, installed, loaded or timed on the Jetson. Its live CPU
placement and the speakerphone routing configuration remain unchanged.

## Measured host and speech load

Jetson reports **7,485 MiB** system RAM, L4T **R39.2.0**, Ubuntu 24.04,
driver-reported CUDA compatibility **13.2**, and **15 W** power mode.
Before probing, Docker accounted for approximately **1.155 GiB ASR** and
**3.752 GiB TTS**. These are container footprints, not separate VRAM totals.
`nvidia-smi` did not expose memory/process accounting on this device, so the
assessment used `/proc/meminfo`, Docker statistics and `tegrastats`.

| Phase | Samples | Minimum available RAM | Median GPU activity |
|---|---:|---:|---:|
| Before synthetic requests | 6 | **1,665 MiB** | **6%** |
| TTS request with existing live ASR stream | 17 | **1,648 MiB** | **99%** |
| Additional offline ASR + TTS concurrently | 83 | **941 MiB** | **99%** |
| After the probe | 30 | **944 MiB** | **5%** |

The sampler ran for 35 seconds at 250 ms intervals. The probe made one
synthetic TTS request, then four concurrent ASR/TTS pairs over the existing
gRPC services. No generated audio was played through the speakerphone, no
user audio was recorded, and no tools or database operations were invoked.
The ASR calls used offline recognition **in addition to the bot's existing
stream**. This is a stress check and can overstate ordinary single-stream
sequential pipeline usage; it is not another end-to-end voice benchmark.

GPU percentage indicates activation time during the sample interval, not
available memory or a guarantee that another workload can run without
contention. The normal utterance pipeline can serialize ASR, routing and TTS,
but their resident weights and cached allocations still coexist. NVIDIA's
[tegrastats definitions](https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/AT/JetsonLinuxDevelopmentTools/TegrastatsUtility.html)
explain these counters; this reference is used for metric meanings, not
JetPack package compatibility.

The probe increased ASR's accounted footprint to **2.19 GiB**, while TTS was
**3.733 GiB**. Allocations remained resident afterward: available memory was
approximately **949 MiB** and swap use **541 MiB**, versus roughly 3 MiB swap
before. Both speech containers and the SQLite worker stayed running. These
post-probe figures are distinct from the original idle baseline. No containers
were restarted and no caches were flushed to make the figures look smaller.

## Actual Laya parameter footprint

A fresh ThinkPad load of the exact local checkpoint confirmed:

- **421,293,827 parameters**, all **`torch.float32`** under the installed loader.
- Resident parameter storage alone: **1,607 MiB**, approximately **1.57 GiB**.
- Checkpoint file: **842,609,220 bytes**; file size is not resident model size.
- Theoretical FP16 parameter storage: **804 MiB**, approximately **0.78 GiB**.

The inspected Laya 0.4.19 loader builds the model, copies checkpoint tensors
into it and calls `model.to(device)` without converting the stored parameters
to FP16. Its CUDA autocast setting controls operation precision; it does not
establish an all-FP16 resident model. This stock CUDA footprint is inferred
from the installed code and verified CPU parameter dtype, not a Jetson CUDA
load. PyTorch documents autocast as an
[operation-specific mixed-precision mechanism](https://docs.pytorch.org/docs/2.15/amp.html#autocasting).

Even during the TTS-only phase, subtracting the stock **1,607 MiB** parameters
from available **1,648 MiB** leaves only about **41 MiB**, before a new Python/
PyTorch process, CUDA context, activations, workspaces, autocast copies or
temporary loading allocations. Under the concurrent stress phase, the stock
parameter storage exceeds available memory outright. FP16 parameters would
leave only about **137 MiB** at the measured stress minimum, also before those
additional costs. Swap capacity is not evidence that GPU inference will fit
or retain the required latency.

The inspected host Python 3.12 had no PyTorch, Transformers or Laya packages.
Neither speech container had a `python3` executable. A separate Jetson-compatible
Arm64 CUDA environment would be needed; the ThinkPad's x86 Python environment
cannot simply be reused. No packages or images were changed for this assessment.

## Implication and next experiment

CUDA could reduce compute time if a suitable deployment fits, but no Jetson
Laya latency has been measured. The **0.704 s** median CPU server stage is the
cost to target. Eliminating that stage can save roughly 0.7 s per classified
turn with other work fixed; it cannot remove cloud plans, catalog retries,
ASR failures or TTS latency. Any slowdown of speech on the shared GPU can
offset the classifier saving.

Before moving the live router, an isolated experiment should establish a
genuinely reduced-memory loading/inference path, measure peak system and CUDA
allocations across loading/warmup and representative text lengths, verify
route/probability agreement with the pinned question/calibration/gate, and
compare ASR/TTS plus total voice latency under overlap. Preserve ThinkPad
rollback and the current speech services. No claim of feasibility should rely
on the approximately 804 MiB checkpoint file alone.

[Safe capacity samples, probe metadata and parameter accounting](../profiling/jetson-laya-capacity-20261101/summary.json)
are saved alongside the raw numeric samples. This assessment changes no model
placement, power settings, audio settings or stored agent state.
