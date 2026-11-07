"""Measure the installed MCP client without replacing its tool-call behavior."""

import uuid

from pipecat.services.mcp_service import MCPClient
from stall_diagnostics import CALL_ID, META_KEY


class ProfiledMCPClient(MCPClient):
    def __init__(self, *args, diagnostics, **kwargs):
        super().__init__(*args, **kwargs)
        self.diagnostics = diagnostics

    async def _open_session(self, *, as_owner):
        with self.diagnostics.span("mcp_open_session", as_owner=as_owner):
            session = await super()._open_session(as_owner=as_owner)
        if not getattr(session, "_voice_diagnostics_wrapped", False):
            original = session.call_tool

            async def measured_call(name, *args, **kwargs):
                call_id = CALL_ID.get()
                if not call_id:
                    return await original(name, *args, **kwargs)
                kwargs["meta"] = {**(kwargs.get("meta") or {}), META_KEY: call_id}
                with self.diagnostics.span("mcp_rpc", tool=name):
                    return await original(name, *args, **kwargs)

            session.call_tool = measured_call
            session._voice_diagnostics_wrapped = True
        return session

    async def _call_tool_text(self, function_name, arguments):
        with self.diagnostics.call(uuid.uuid4().hex):
            with self.diagnostics.span("mcp_client_total", tool=function_name):
                return await super()._call_tool_text(function_name, arguments)
