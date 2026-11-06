"""Resident Laya HTTP adapter for the existing two-brain classifier slot.

The server uses the exact trained question; the caller's Jev question is never
sent as an inference override. No model/tool/cloud execution occurs here.
"""

import math
import os
from types import SimpleNamespace

import httpx

if os.getenv("LAYA_SCHEMA", "").strip().lower() == "v2":
    from laya_contract_v2 import CONTRACT, gate
else:
    from laya_contract import CONTRACT, gate


class LayaClassifier:
    def __init__(self):
        self.timeout = float(os.getenv("LAYA_ROUTER_TIMEOUT_SECS", "2"))
        self.url = os.getenv("LAYA_ROUTER_URL", "http://127.0.0.1:18082").rstrip("/")
        self.client = httpx.AsyncClient(timeout=self.timeout, trust_env=False)

    async def setup(self, _task_manager):
        response = await self.client.get(self.url + "/health")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("ready") is not True or payload.get("contract") != CONTRACT:
            raise ValueError("Resident Laya service is not ready with the pinned contract")

    async def cleanup(self):
        await self.client.aclose()

    async def choice(self, state, _questions):
        text = state.get("utterance")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Laya requires a transcript")
        response = await self.client.post(self.url + "/classify", json={"text": text})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("contract") != CONTRACT:
            raise ValueError("Laya response contract mismatch")
        decision = gate({"choice": payload.get("raw_choice"),
                         "probabilities": payload.get("probabilities")})
        server_s = payload.get("classifier_s")
        if type(server_s) not in (int, float) or not math.isfinite(server_s) or server_s < 0:
            raise ValueError("Invalid server inference duration")
        return {"intent": SimpleNamespace(choice=decision["raw_choice"],
                    probabilities=decision["probabilities"],
                    server_classifier_s=server_s, gate_result=decision)}
