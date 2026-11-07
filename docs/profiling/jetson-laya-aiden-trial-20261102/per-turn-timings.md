# Jetson Laya + Aiden live timings

Run `016c1ab953`. Seconds. Startup/untimed turns 0–3 excluded from human statistics. E2E is estimated speech end to software bot start; playback uses earliest write.

| Turn | Case | Laya GPU server | Pi wait | Qwen first PCM | E2E | Downstream |
|---:|---|---:|---:|---:|---:|---|
| 4 | partial_hearing_check | 0.095 | 0.110 | 0.173 | 2.995 | route_glm |
| 5 | lights_on | 0.090 | 0.106 | 0.157 | 1.170 | route_tool |
| 6 | color_green_guard_reject | 0.098 | 0.112 | 0.178 | 3.214 | route_glm |
| 7 | thermostat_twenty_classified_other | 0.092 | 0.104 | 0.160 | 3.305 | route_glm |
| 8 | message_request_no_body | 0.118 | 0.134 | 0.498 | 2.701 | route_glm |
| 9 | message_body_smalltalk_promise_without_tool | 0.129 | 0.145 | 0.222 | 1.917 | route_smalltalk |
| 10 | reminder_exercise | — | — | 0.274 | 1.073 | route_tool |
| 11 | music_catalog | 0.118 | 0.131 | 0.262 | 2.189 | route_tool |
| 12 | color_blue_guard_reject | 0.093 | 0.107 | 0.187 | 3.407 | route_glm |
| 13 | compound_red_volume_up_glm_tail | 0.099 | 0.114 | 0.164 | 15.762 | route_glm |
| 14 | weather_classified_other_glm_api_tail | 0.103 | 0.117 | 0.161 | 27.041 | route_glm |
| 15 | no_final_asr | — | — | — | — | — |
| 16 | no_final_asr | — | — | — | — | — |
| 17 | no_final_asr | — | — | — | — | — |
| 18 | hearing_check_noisy_asr_tts_tail | 0.124 | 0.140 | 1.744 | 4.325 | route_glm |
| 19 | time_yes_prefix_guard_reject_tts_tail | 0.093 | 0.114 | 1.426 | 4.481 | route_glm |
| 20 | compound_stop_music_lights_off | — | — | 0.151 | 3.824 | route_glm |
| 21 | hearing_check_transition | 0.128 | 0.141 | 0.167 | 2.848 | route_glm |
| 22 | dark_room | 0.131 | 0.146 | 0.181 | 2.336 | route_glm |
| 23 | brightness_complaint_noisy_asr_clarification | 0.124 | 0.137 | 1.565 | 5.051 | route_glm |
| 24 | brightness_consent_corrected_operation | 0.131 | 0.153 | 0.179 | 3.736 | route_glm |
| 25 | heat_complaint_smalltalk | 0.124 | 0.139 | 0.160 | 2.198 | route_smalltalk |
| 26 | stay_in_room_thermostat | 0.132 | 0.146 | 0.161 | 6.828 | route_glm |
| 27 | alarm_tomorrow_six_noisy_asr | 0.094 | 0.108 | 0.169 | 3.420 | route_glm |
| 28 | blue_preference | 0.118 | 0.132 | 0.161 | 3.448 | route_glm |
| 29 | rain_today | 0.093 | 0.108 | 0.168 | 4.799 | route_glm |
| 30 | manila_time_guard_reject | 0.128 | 0.140 | 0.166 | 4.347 | route_glm |
| 31 | music_too_loud | 0.128 | 0.143 | 0.218 | 4.210 | route_glm |
| 32 | lights_off_idiom_noisy_asr_clarification | 0.120 | 0.136 | 0.517 | 4.649 | route_glm |
| 33 | lights_off_idiom_rephrase | 0.091 | 0.103 | 0.166 | 3.750 | route_glm |
