# Laya live benchmark: per-turn timings

Run `26c376b1c3`. Units are seconds except where marked. First response is estimated speech-end to software playback. Raw speech is not included.

## Direct set

| Turn | Case | Laya server | Pi wait | Downstream | GLM calls / summed seconds | MCP calls / summed ms | First response |
|---:|---|---:|---:|---|---:|---:|---:|
| 3 | hearing_check | 0.732 | 0.750 | Llama | 0 / 0.000 | 0 / 0.0 | 3.638 |
| 4 | lights_on_noisy_asr | 0.692 | 0.707 | GLM | 2 / 3.567 | 1 / 32.4 | 6.309 |
| 5 | light_color_blue | 0.692 | 0.708 | GLM | 2 / 2.186 | 1 / 29.0 | 4.807 |
| 6 | thermostat_twenty | 0.706 | 0.724 | GLM | 2 / 2.539 | 1 / 32.9 | 5.027 |
| 7 | message_request_no_body | 0.684 | 0.702 | GLM | 1 / 1.533 | 0 / 0.0 | 4.113 |
| 8 | no_final_asr | — | — | — | 0 / 0.000 | 0 / 0.0 | no independent reply |
| 9 | reminder_creation | 0.693 | 0.723 | GLM | 2 / 2.878 | 1 / 28.1 | 5.434 |
| 10 | music_catalog_repeated_searches | 0.744 | 0.762 | GLM | 6 / 8.692 | 5 / 23091.8 | 34.543 |
| 11 | interrupted_color_fragment | — | interrupted | — | 0 / 0.000 | 0 / 0.0 | no independent reply |
| 12 | color_and_volume_continuation | 0.690 | 0.708 | GLM | 2 / 3.074 | 2 / 113.7 | 5.573 |
| 13 | current_weather | 0.711 | 0.726 | direct MCP | 0 / 0.000 | 1 / 1274.8 | 3.827 |
| 14 | current_time | 0.681 | 0.694 | direct MCP | 0 / 0.000 | 1 / 10.4 | 2.460 |
| 15 | compound_stop_music_lights_off | — | bypass | GLM | 2 / 2.700 | 2 / 67.3 | 4.594 |

## Context set

| Turn | Case | Laya server | Pi wait | Downstream | GLM calls / summed seconds | MCP calls / summed ms | First response |
|---:|---|---:|---:|---|---:|---:|---:|
| 16 | dark_room | 0.741 | 0.756 | GLM | 3 / 4.149 | 2 / 56.0 | 6.902 |
| 17 | room_too_bright_noisy_asr | 0.705 | 0.723 | GLM | 2 / 3.371 | 1 / 25.7 | 5.899 |
| 18 | no_final_asr | — | — | — | 0 / 0.000 | 0 / 0.0 | no independent reply |
| 19 | heat_complaint | 0.689 | 0.706 | GLM | 2 / 3.683 | 1 / 969.2 | 7.290 |
| 20 | thermostat_consent_misrouted_smalltalk | 0.689 | 0.703 | Llama | 0 / 0.000 | 0 / 0.0 | 3.306 |
| 21 | alarm_tomorrow_six | 0.748 | 0.772 | GLM | 2 / 3.830 | 1 / 31.8 | 6.362 |
| 22 | blue_preference | 0.734 | 0.757 | GLM | 2 / 3.108 | 1 / 28.3 | 5.699 |
| 23 | rain_question | 0.742 | 0.756 | GLM | 2 / 2.923 | 1 / 1028.9 | 9.024 |
| 24 | manila_time_intent_lost_in_asr_weather_answer | 0.704 | 0.718 | GLM | 2 / 3.061 | 1 / 910.3 | 6.557 |
| 25 | music_too_loud | 0.694 | 0.711 | GLM | 2 / 2.914 | 1 / 28.4 | 5.497 |
| 26 | lights_off_idiom | 0.738 | 0.760 | GLM | 2 / 2.600 | 1 / 26.2 | 5.270 |

MCP call totals can include parallel operations. GLM totals sum individual generation calls and exclude tool waits. These columns are not an exact additive latency decomposition. P95 uses nearest rank on small samples.
