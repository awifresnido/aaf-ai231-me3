#!/bin/bash
# One-command rollback for the backchannel experiment (handover §4 + bot.py patch).
set -e
cd ~/voice-agent
# 1. env: baseline whisper config, no backchannel vars
printf "[Service]\nEnvironment=ASR_BACKEND=whisper\nEnvironment=SPEC_PARTIAL_SOURCE=text\nEnvironment=WHISPER_STREAM=0\n" \
  > ~/.config/systemd/user/me3-local-audio.service.d/asr.conf
rm -f ~/.config/systemd/user/me3-local-audio.service.d/zz-bc.conf
# 2. code: restore the pre-patch bot.py, remove the new module
[ -f ~/voice-agent/bot.py.bak-backchannel ] && cp ~/voice-agent/bot.py.bak-backchannel ~/voice-agent/bot.py
rm -f ~/voice-agent/backchannel.py
systemctl --user daemon-reload && systemctl --user restart me3-local-audio
sleep 3
systemctl --user is-active me3-local-audio
