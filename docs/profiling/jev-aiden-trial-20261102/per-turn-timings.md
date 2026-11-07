# Jev + Aiden live timings

Run `f0c87b3a33`. Seconds; greeting excluded. E2E is native estimated speech end to software bot start. Playback is the earliest write per turn.

| Turn | Case | Jev client | Qwen first PCM | E2E | First playback | Downstream |
|---:|---|---:|---:|---:|---:|---|
| 1 | hearing_check_direct | 0.295 | 0.176 | 3.481 | 3.479 | route_glm |
| 2 | lights_on | 0.414 | 0.165 | 1.477 | 1.474 | route_tool |
| 3 | color_green | 0.296 | 0.106 | 1.229 | 1.228 | route_tool |
| 4 | thermostat_seventeen | 0.261 | 0.161 | 1.196 | 1.194 | route_tool |
| 5 | message_request_no_body | — | 0.169 | 3.642 | 3.640 | route_glm |
| 6 | message_body_misrouted_greeting | 0.266 | 0.114 | 1.555 | 1.552 | route_smalltalk |
| 7 | reminder_drink_water | — | 0.181 | 1.073 | 1.071 | route_tool |
| 8 | music_catalog | 0.297 | 0.168 | 4.324 | 4.322 | route_glm |
| 9 | color_blue | 0.285 | 0.153 | 1.323 | 1.321 | route_tool |
| 10 | volume_up | 0.264 | 0.107 | 1.274 | 1.272 | route_tool |
| 11 | weather_direct | 0.292 | 0.107 | 2.094 | 2.091 | route_tool |
| 12 | time_direct | 0.281 | 0.170 | 1.313 | 1.311 | route_tool |
| 13 | compound_stop_music_lights_off | — | 0.165 | 3.432 | 3.429 | route_glm |
| 14 | hearing_check_transition | 0.274 | 0.169 | 2.559 | 2.557 | route_glm |
| 15 | dark_room | 0.305 | 0.172 | 4.533 | 4.531 | route_glm |
| 16 | room_too_bright_tts_stall | 0.262 | 3.719 | 7.231 | 7.228 | route_glm |
| 17 | heat_complaint_smalltalk | 0.273 | 0.162 | 2.482 | 2.480 | route_smalltalk |
| 18 | stay_in_room_thermostat | 0.285 | 0.307 | 7.278 | 7.275 | route_glm |
| 19 | alarm_tomorrow_six | 0.315 | 0.180 | 4.160 | 4.158 | route_glm |
| 20 | green_preference | — | 0.164 | 4.960 | 4.958 | route_glm |
| 21 | rain_tomorrow | 0.263 | 0.192 | 5.514 | 5.511 | route_glm |
| 22 | no_final_asr | — | — | — | — | — |
| 23 | no_final_asr | — | — | — | — | — |
| 24 | music_too_loud_glm_tail | 0.485 | 0.495 | 12.086 | 12.083 | route_glm |
| 25 | pause_consent_interrupted_before_reply | 0.269 | — | — | — | route_glm |
| 26 | volume_down_direct_rephrase | 0.256 | 1.409 | 2.406 | 2.404 | route_tool |
