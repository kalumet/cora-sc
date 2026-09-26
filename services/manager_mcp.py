"""MCP tools with explicit manager ownership, using the official Python SDK.

No SDK client survives an operation: audio requests run on different event loops.
The registry holds only configuration and discovered tool schemas.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
import json
import logging
import math
import re
import threading
import time
from urllib.parse import urlsplit


logger = logging.getLogger(__name__)
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class ToolBinding:
    server: str
    tool: str
    managers: set[str] = field(default_factory=set)
    definition: dict | None = None


def _sdk_client(url, timeout):
    # Import lazily: configurations without MCP still work without the SDK.
    from mcp import Client

    return Client(url, read_timeout_seconds=timeout)


class ManagerMcpTools:
    def __init__(self, config, *, is_manager_available, reserved_names,
                 report_warning=None, client_factory=None):
        self.config = deepcopy(config or {})
        self.is_manager_available = is_manager_available
        self.reserved_names = reserved_names
        self.report_warning = report_warning or logger.warning
        self.client_factory = client_factory or _sdk_client
        self.servers = {}
        self.bindings = {}
        self._ambiguous_names = set()
        self._discovery_lock = threading.Lock()
        self._read_config()

    def _read_config(self):
        if not isinstance(self.config, dict):
            self.report_warning("MCP configuration must be a mapping; MCP is disabled.")
            return
        servers = self.config.get("servers", {})
        mappings = self.config.get("manager_tools", {})
        if not isinstance(servers, dict) or not isinstance(mappings, dict):
            self.report_warning("MCP servers and manager_tools must be mappings; MCP is disabled.")
            return
        for name, options in servers.items():
            if not isinstance(name, str) or not _TOOL_NAME.fullmatch(name) or not isinstance(options, dict):
                self.report_warning("Invalid MCP server configuration; entry ignored.")
                continue
            if options.get("enabled", False) is not True:
                continue
            url = options.get("url")
            try:
                parsed = urlsplit(url) if isinstance(url, str) else None
                timeout = float(options.get("timeout_seconds", 30))
                valid = (parsed and parsed.scheme in ("http", "https") and parsed.hostname
                         and not parsed.username and not parsed.password
                         and math.isfinite(timeout) and timeout > 0)
            except (ValueError, TypeError):
                valid = False
            if not valid:
                self.report_warning(f"Invalid MCP URL or timeout for {name}; server disabled.")
                continue
            self.servers[name] = {"url": url, "timeout": timeout}

        for manager, grants in mappings.items():
            if not isinstance(manager, str) or not isinstance(grants, dict):
                self.report_warning("Invalid MCP manager_tools entry; entry ignored.")
                continue
            for server, tool_names in grants.items():
                if server not in servers:
                    self.report_warning(f"Unknown MCP server in grants for {manager}: {server}")
                    continue
                if not isinstance(tool_names, list):
                    self.report_warning(f"MCP grants for {manager}/{server} must be a list.")
                    continue
                for tool in tool_names:
                    if not isinstance(tool, str) or not _TOOL_NAME.fullmatch(tool):
                        self.report_warning(f"Invalid MCP tool name for {manager}/{server}; entry ignored.")
                        continue
                    alias = f"{server}_{tool}"
                    if not _TOOL_NAME.fullmatch(alias):
                        self.report_warning(f"MCP tool alias is invalid or longer than 64 characters: {alias}")
                        continue
                    binding = self.bindings.get(alias)
                    if binding and (binding.server, binding.tool) != (server, tool):
                        self._ambiguous_names.add(alias)
                        self.report_warning(f"Ambiguous MCP tool alias disabled: {alias}")
                        continue
                    if binding is None:
                        binding = self.bindings[alias] = ToolBinding(server, tool)
                    binding.managers.add(manager)

    def validate_managers(self, known_managers):
        for binding in self.bindings.values():
            for manager in binding.managers - set(known_managers):
                self.report_warning(f"Unknown manager in MCP grants: {manager}")

    def handles(self, name):
        # Keep configured names even while unavailable, so stale calls are denied.
        return name in self.bindings

    def _allowed(self, name, context):
        binding = self.bindings[name]
        return (
            name not in self._ambiguous_names
            and name not in self.reserved_names()
            and binding.server in self.servers
            and any(self.is_manager_available(manager, context) for manager in binding.managers)
        )

    def discover_for_manager(self, manager):
        """Bridge the synchronous manager lifecycle to a short-lived SDK session."""
        if not self.is_manager_available(manager, None):
            return
        servers = {b.server for b in self.bindings.values()
                   if manager in b.managers and b.server in self.servers}
        if not servers:
            return
        with self._discovery_lock:
            # Activation can run inside an audio request's event loop. Never nest
            # asyncio.run there or retain SDK resources across audio requests.
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="mcp-discovery") as pool:
                for server in sorted(servers):
                    for binding in self.bindings.values():
                        if binding.server == server:
                            binding.definition = None
                    try:
                        definitions = pool.submit(lambda: asyncio.run(self._discover(server))).result()
                        for alias, binding in self.bindings.items():
                            if binding.server != server:
                                continue
                            if alias in self.reserved_names() or alias in self._ambiguous_names:
                                self.report_warning(f"MCP tool name collision; tool disabled: {alias}")
                                continue
                            definition = definitions.get(binding.tool)
                            if definition is None:
                                self.report_warning(f"MCP tool unavailable: {server}/{binding.tool}")
                                continue
                            binding.definition = {
                                "type": "function",
                                "function": {
                                    "name": alias,
                                    "description": definition["description"],
                                    "parameters": definition["parameters"],
                                },
                            }
                    except Exception as exc:
                        # Exception messages can contain URLs/headers; log only the type.
                        self.report_warning(
                            f"MCP discovery failed for {server} ({type(exc).__name__}). "
                            "Local tools remain available. Re-enable the manager to retry."
                        )

    async def _discover(self, server):
        options = self.servers[server]
        async with asyncio.timeout(options["timeout"]):
            async with self.client_factory(options["url"], options["timeout"]) as client:
                definitions = {}
                cursor = None
                seen_cursors = set()
                while True:
                    result = await client.list_tools(cursor=cursor)
                    for tool in result.tools:
                        if not isinstance(tool.input_schema, dict) or tool.input_schema.get("type") != "object":
                            continue
                        definitions[tool.name] = {
                            "description": tool.description or tool.title or tool.name,
                            "parameters": deepcopy(tool.input_schema),
                        }
                    cursor = result.next_cursor
                    if not cursor:
                        return definitions
                    if cursor in seen_cursors:
                        raise ValueError("Repeated MCP pagination cursor")
                    seen_cursors.add(cursor)

    def get_tools(self, context):
        return [deepcopy(binding.definition) for name, binding in self.bindings.items()
                if binding.definition is not None and self._allowed(name, context)]

    @staticmethod
    def _result(binding, *, success, data=None, error=None):
        result = {"success": success, "source": binding.server, "tool": binding.tool,
                  "data": data, "do_not_cache": True}
        if error:
            result["error"] = error
        return result

    @staticmethod
    def _decode_result(result):
        if result.structured_content is not None:
            return result.structured_content
        texts = []
        for block in result.content:
            if block.type == "text":
                try:
                    texts.append(json.loads(block.text))
                except (ValueError, TypeError):
                    texts.append(block.text)
        if not texts:
            raise ValueError("MCP returned no text or structured data")
        return texts[0] if len(texts) == 1 else texts

    async def call_tool(self, name, arguments, context):
        binding = self.bindings[name]
        if not self._allowed(name, context) or binding.definition is None:
            return self._result(binding, success=False, error="MCP tool is not available in this manager/context.")
        if not isinstance(arguments, dict):
            return self._result(binding, success=False, error="MCP arguments must be an object.")

        # Validate with the server's schema, without fetching external references.
        from jsonschema.validators import validator_for
        from referencing import Registry
        from referencing.exceptions import NoSuchResource

        def no_remote_schema(uri):
            raise NoSuchResource(ref=uri)

        schema = binding.definition["function"]["parameters"]
        try:
            validator = validator_for(schema)(schema, registry=Registry(retrieve=no_remote_schema))
            if not validator.is_valid(arguments):
                return self._result(binding, success=False, error="Arguments do not match the MCP tool schema.")
        except Exception:
            return self._result(binding, success=False, error="MCP tool schema could not be validated.")

        options = self.servers[binding.server]
        started = time.monotonic()
        try:
            async with asyncio.timeout(options["timeout"]):
                async with self.client_factory(options["url"], options["timeout"]) as client:
                    # A manager may have been disabled during connection setup.
                    if not self._allowed(name, context):
                        return self._result(binding, success=False, error="MCP permission changed before execution.")
                    result = await client.call_tool(binding.tool, arguments)
            data = self._decode_result(result)
            response = self._result(binding, success=not result.is_error, data=data,
                                    error="MCP tool reported an error." if result.is_error else None)
        except TimeoutError:
            response = self._result(binding, success=False, error="MCP request timed out. Please try again.")
        except Exception as exc:
            response = self._result(binding, success=False,
                                    error=f"MCP request failed ({type(exc).__name__}). Please try again.")
        logger.info("MCP server=%s tool=%s context=%s success=%s duration=%.2fs",
                    binding.server, binding.tool, context, response["success"], time.monotonic() - started)
        return response
