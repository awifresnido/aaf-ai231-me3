# Evaluation: what was measured

The 6–7 November 2026 overnight session compared the same pipeline with direct speech sockets and with Pi-hosted ASR/TTS MCP proxies. It used the [AI231 full-duplex benchmarking project](https://github.com/trueshotjames/ai231-me3-full-duplex-benchmarking), natural Laya routing, simulated tool state, and disabled filler audio in the isolated benchmark session. Normal voice service was restored after each run. The benchmark was run from the ThinkPad; model services remained distributed across the cluster.

## Results and boundaries

| Measure | Direct: mean / p95 (n) | Pi speech MCP: mean / p95 (n) | Project target |
| --- | ---: | ---: | ---: |
| E2E, VAD end to audio output | 5.32 / 8.16 s (30) | 5.44 / 8.56 s (30) | < 4.0 s |
| ASR final | 1.39 / 1.93 s (30) | 1.11 / 1.33 s (30) | < 0.8 s |
| LLM time to first token | 3.59 / 6.72 s (27) | 3.48 / 5.82 s (27) | < 1.5 s |
| TTS time to first audio | 0.18 / 0.38 s (30) | 0.52 / 0.76 s (30) | < 0.6 s |
| Word error rate | 3.8% (30) | 3.8% (30) | — |

The thirty observations are **10 phrases × 3 passes**, not 30 independent prompts. The same phrases ran in the same order with 15-second gaps; this was not a randomized or causal comparison. LLM first-token marks were available for 27 observations in each configuration, so its denominator differs. Missing marks are not zero-latency successes. Results describe one hardware/network session and a mixture of naturally selected routes; they do not separately estimate local and cloud latency.

E2E uses the Pi's VAD-end-to-audio-output marks rather than an acoustic measurement from the end of a prerecorded prompt. The standard reply window counted 26/30 direct and 25/30 proxy replies. Extended recordings contained relevant answers for the remaining cases on transcript review; late answers do not pass the standard window merely because they eventually arrived.

## Interruption and response quality

A separate direct-configuration interruption test attempted 30 distinct clips. Playback overlap occurred in 27; 25 yielded measurable stop times: **0.32 s mean, 0.53 s p95, 1.31 s maximum**, versus a 0.8 s target. The benchmark observed a follow-up turn in 25 of the 27 played overlaps. An enabled GPT-4o judge rated the 25 usable follow-up answers **4.0/5 mean relevance**. This is an automated model judgment, not a human score; the three unplayed overlaps and two missing stop measurements must not be counted as successes.

One separate physical check played a question through the ThinkPad speaker into the Pi's JV801P microphone; recognition, an appropriate answer, and output audio were observed. A single check cannot characterize room acoustics or general real-world performance.

## Provenance and reproducibility limits

These figures transcribe the local `benchmark-results/overnight-report.md` and its direct, proxy, and interruption summaries for the 6–7 November session. Full raw recordings and trial artifacts are retained locally outside this repository; they have not been committed or independently reproduced from this checkout. Re-running the benchmark requires its external repository, datasets, a compatible cluster, and the appropriate adapters/configuration. Review and redact transcripts, device identifiers, and credentials before publishing raw artifacts.

Additional instrumented live-demo observations, including failures and follow-up fixes, are in the [demo evidence report](../runbooks/demo-evidence-20261107.md). Historical component experiments and their original data are under [profiling](../profiling/); their model configurations and measurement boundaries vary.
