# Runbook — Llama 3.2 LLM on the VPS (branch `llama32-vps`)

The `llama32-vps` branch replaces the Ollama Cloud LLM with a local
**Llama 3.2 3B Instruct (Q4_K_M GGUF)** served by `llama-server` on the VPS
(`srv1818228`, root@72.62.76.173). The endpoint is OpenAI-compatible, so the
Pipecat `OpenAILLMService` in `pi/bot.py` is a drop-in client.

## 1. Start the LLM server on the VPS

```bash
ssh vps
~/llama.cpp/build/bin/llama-server \
  -m ~/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf \
  --host 0.0.0.0 --port 8010 \
  --ctx-size 4096 --threads 2 \
  --alias llama3.2-3b
```

Notes:
- VPS has 2 vCPU / 7.8 GiB RAM; 3B Q4_K_M (~2 GB) fits comfortably.
- Port 8010 chosen to avoid conflicts; open it if ufw is ever enabled:
  `ufw allow 8010/tcp` (currently ufw is inactive).
- The API needs no key — the bot sends a dummy key (`LLM_API_KEY=none`).

Verify from anywhere:

```bash
curl -s http://72.62.76.173:8010/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"llama3.2-3b","messages":[{"role":"user","content":"Say hi in five words."}],"max_tokens":30}'
```

## 2. Pi-side env (`~/.voice-agent-env`, chmod 600)

```
LLM_BASE_URL=http://72.62.76.173:8010/v1
LLM_MODEL=llama3.2-3b
LLM_API_KEY=none
```

(`pi/bot.py` falls back to these values as defaults, so an empty env also works.)

## 3. Run the agent on the Pi

```bash
cd ~/voice-agent   # checked out on branch llama32-vps
~/pipecat-quickstart/server/.venv/bin/python bot.py -t webrtc --host 0.0.0.0 --port 7860
```

Then from the ThinkPad: `ssh -L 7860:localhost:7860 aldwinrpi4@192.168.5.12`
and open <http://localhost:7860>.

## 4. End-to-end test checklist

1. Greeting plays on connect ("Hello. This is the Raspberry Pi voice agent…").
2. Ask "what time is it?" → `get_time` tool call → spoken answer.
3. Ask "what's the weather in Tacloban?" → `get_weather` → spoken answer.
4. Free-form chat ("tell me a one-sentence fun fact") → llama.cpp latency is
   the main new variable; watch `enable_metrics` usage in the bot log.
5. Barge-in mid-reply still works (VAD path unchanged).

## Latency expectation

3B Q4_K_M on 2 vCPU ≈ 8–15 tokens/s → first spoken token lands ~1–2 s after
the ASR final, full 1–3 sentence reply ~3–6 s. Slower than Ollama Cloud, but
fully self-hosted.
