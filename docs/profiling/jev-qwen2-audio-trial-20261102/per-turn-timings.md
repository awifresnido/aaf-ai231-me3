# Jev + Qwen2-Audio ASR/small model + Aiden timings

Run `72afa542c5`. Seconds. Startup/checks 0–2 excluded. Native E2E measures estimated speech end to software response. Turn 11 inherits speech end from prior segment. Turn 9 reply was interrupted.

| Turn | Case | ASR HTTP requests | Jev client | TTS first PCM | E2E | Downstream |
|---:|---|---:|---:|---:|---:|---|
| 3 | lights_on_after_no_speech_segment | 0.782 | 0.296 | 0.156 | 1.596 | route_tool |
| 4 | color_green_endpoint_delay | 0.597 | 0.343 | 0.179 | 3.863 | route_tool |
| 5 | thermostat_wrapped_asr | 0.742 | 0.293 | 0.177 | 6.917 | route_glm |
| 6 | no_speech_text_tts_stall | 1.264 | 0.269 | 26.697 | 29.884 | route_glm |
| 7 | message_request_wrapped_asr | 2.050 | 0.309 | 0.179 | 9.661 | route_glm |
| 8 | message_body_wrapped_asr | 0.597 | 0.291 | 0.165 | 5.004 | route_glm |
| 9 | no_speech_text_interrupted_reply | 0.464 | 0.284 | 0.269 | 2.475 | route_glm |
| 10 | asr_refusal_then_reminder_continuation | 0.764, 0.760 | 0.290 | — | — | route_glm |
| 11 | reminder_drink_water | — | — | 0.217 | 2.037 | route_tool |
| 12 | asr_refusal_followup | 0.772 | 0.350 | 0.222 | 3.382 | route_glm |
| 13 | music_catalog | 0.729 | 0.292 | 0.171 | 2.715 | route_tool |
| 14 | blue_fragment_glm | 0.769 | 0.323 | 0.185 | 8.535 | route_glm |
| 15 | volume_up | 0.610 | 0.281 | 0.317 | 1.577 | route_tool |
| 16 | weather_answer_like_asr | 0.463 | 0.311 | 0.386 | 3.369 | route_glm |
| 17 | weather_answer_like_repeat | 0.607 | 0.323 | 0.189 | 5.298 | route_glm |
| 18 | clock_answer_like_asr | 0.556 | 0.278 | 0.170 | 5.241 | route_glm |
| 19 | compound_stop_music_lights_off_wrapped | 0.862 | — | 0.755 | 6.532 | route_glm |
| 20 | transition_hearing_check_asr_refusal | 0.828 | 0.288 | 0.179 | 3.255 | route_glm |
| 21 | dark_room | 0.709 | 0.290 | 0.172 | 4.510 | route_glm |
| 22 | room_too_bright | 0.754 | 0.289 | 0.170 | 4.216 | route_glm |
| 23 | heat_complaint | 0.657 | — | 0.181 | 4.651 | route_glm |
| 24 | make_cooler_followup | 0.516 | 0.287 | 0.207 | 3.955 | route_glm |
| 25 | alarm_seven_tomorrow | 1.077 | 0.274 | 0.174 | 4.464 | route_glm |
| 26 | green_preference | 0.842 | 0.263 | 0.165 | 4.494 | route_glm |
| 27 | rain_today | 0.767 | 0.313 | 0.165 | 9.380 | route_glm |
| 28 | manila_time_statement_asr | 0.745 | 0.292 | 0.164 | 4.735 | route_glm |
| 29 | music_too_loud | 0.569 | 0.285 | 0.162 | 3.650 | route_glm |
| 30 | lights_off_extraction_reject | 0.734 | 0.289 | 0.179 | 5.089 | route_glm |
