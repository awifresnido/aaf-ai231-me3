# Qwen TTS live timings

Run `147f31abef`. Seconds. E2E is native estimated speech end to software bot start. Playback uses the earliest write per turn; repeated markers are not additional replies. Turns 29 and 34 inherit native timing across speech fragments and have no same-turn speech-end marker.

| Turn | Case | Laya server | Pi classifier wait | Qwen first PCM | E2E | First playback |
|---:|---|---:|---:|---:|---:|---:|
| 1 | hearing_check_initial | — | — | 0.163 | 5.155 | 5.152 |
| 2 | identity_question | 0.704 | 0.728 | 0.157 | 3.533 | 3.531 |
| 3 | weather_initial | 0.708 | 0.725 | 0.165 | 2.598 | 2.596 |
| 4 | time_initial | 0.730 | 0.747 | 0.194 | 1.771 | 1.769 |
| 5 | hearing_check_tts_stall | 0.747 | 0.766 | 11.371 | 14.401 | 14.396 |
| 6 | no_final_asr | — | — | — | — | — |
| 7 | hearing_check_direct_set | 0.783 | 0.801 | 0.177 | 4.945 | 4.941 |
| 8 | lights_on | 0.705 | 0.722 | 0.176 | 1.788 | 1.785 |
| 9 | color_green | 0.721 | 0.738 | 0.159 | 4.114 | 4.111 |
| 10 | thermostat_twenty | 0.740 | 0.755 | 0.473 | 4.348 | 4.345 |
| 11 | no_final_asr | — | — | — | — | — |
| 12 | message_request_no_body | 0.703 | 0.719 | 0.168 | 3.718 | 3.715 |
| 13 | message_body_followup | 0.731 | 0.749 | 0.169 | 9.301 | 9.297 |
| 14 | reminder_study | — | — | 1.169 | 1.954 | 1.952 |
| 15 | music_catalog | 0.750 | 0.766 | 0.505 | 2.882 | 2.879 |
| 16 | color_blue | 0.759 | 0.777 | 0.165 | 3.899 | 3.897 |
| 17 | color_red_fragment | 0.802 | 0.823 | 0.176 | 5.816 | 5.814 |
| 18 | volume_down_direct | 0.752 | 0.770 | 0.159 | 4.293 | 4.290 |
| 19 | weather_direct | 0.834 | 0.850 | 0.321 | 3.083 | 3.080 |
| 20 | time_direct | 0.748 | 0.765 | 0.151 | 1.656 | 1.654 |
| 21 | lights_off_direct | 0.747 | 0.769 | 0.170 | 1.714 | 1.712 |
| 22 | dark_room | 0.763 | 0.781 | 0.207 | 3.092 | 3.089 |
| 23 | lights_on_consent | 0.747 | 0.762 | 0.161 | 4.586 | 4.582 |
| 24 | room_too_bright | 0.760 | 0.780 | 0.159 | 4.947 | 4.945 |
| 25 | heat_complaint | 0.763 | 0.780 | 0.159 | 4.384 | 4.381 |
| 26 | lower_temperature_followup | 0.753 | 0.769 | 0.171 | 4.461 | 4.459 |
| 27 | alarm_tomorrow_six | 0.778 | 0.795 | 0.173 | 4.031 | 4.029 |
| 28 | color_preference_fragment | — | — | — | — | — |
| 29 | color_preference_continuation | — | — | 0.176 | 6.274 | — |
| 30 | rain_question | 0.755 | 0.776 | 0.162 | 6.166 | 6.164 |
| 31 | manila_time | 0.768 | 0.785 | 0.179 | 7.680 | 7.678 |
| 32 | music_too_loud | 0.724 | 0.741 | 0.381 | 4.668 | 4.666 |
| 33 | lights_off_idiom_fragment | — | — | — | — | — |
| 34 | lights_off_idiom_continuation | 0.712 | 0.727 | 0.155 | 7.726 | — |
