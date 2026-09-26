"""Print YAML tool references for configured HTTP MCP servers; never call tools."""

import argparse
import asyncio
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlsplit

import yaml
from mcp import Client


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "configs/configs/config.yaml"


def configured_servers(config, wingman=None):
    """Enumerate explicit server definitions, including disabled servers."""
    if not isinstance(config, dict):
        raise ValueError("Die Konfiguration muss ein YAML-Mapping sein.")
    wingmen = config.get("wingmen", {}) or {}
    if not isinstance(wingmen, dict):
        raise ValueError("wingmen muss ein Mapping sein.")
    if wingman is not None and wingman not in wingmen:
        raise ValueError(f"Unbekannter Wingman: {wingman}")
    scopes = [("global", config)] if wingman is None else []
    scopes.extend((name, value) for name, value in wingmen.items()
                  if wingman is None or name == wingman)
    for scope, values in scopes:
        if not isinstance(values, dict):
            raise ValueError(f"Ungueltige Konfiguration fuer {scope}.")
        mcp = values.get("mcp", {}) or {}
        if not isinstance(mcp, dict) or not isinstance(mcp.get("servers", {}), dict):
            raise ValueError(f"mcp.servers muss ein Mapping sein ({scope}).")
        for name, options in mcp.get("servers", {}).items():
            yield scope, name, options


async def list_server_tools(options, client_factory=Client):
    if not isinstance(options, dict):
        raise ValueError("Ungueltige Serverkonfiguration")
    url = options.get("url")
    parsed = urlsplit(url) if isinstance(url, str) else None
    timeout = float(options.get("timeout_seconds", 30))
    if (not parsed or parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("HTTP-URL oder Timeout ungueltig")
    async with asyncio.timeout(timeout):
        async with client_factory(url, read_timeout_seconds=timeout) as client:
            tools = []
            cursor = None
            seen = set()
            while True:
                page = await client.list_tools(cursor=cursor)
                tools.extend(page.tools)
                cursor = page.next_cursor
                if not cursor:
                    return sorted(tools, key=lambda tool: tool.name)
                if cursor in seen:
                    raise ValueError("Wiederholter Pagination-Cursor")
                seen.add(cursor)


async def run(config, *, wingman=None, enabled_only=False, details=False,
              stdout=None, stderr=None, client_factory=Client):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    servers = list(configured_servers(config, wingman))
    failures = 0
    queried = 0
    for scope, name, options in servers:
        enabled = isinstance(options, dict) and options.get("enabled", False) is True
        if enabled_only and not enabled:
            continue
        queried += 1
        label = f"{scope}/{name}"
        try:
            tools = await list_server_tools(options, client_factory)
        except Exception as exc:
            # Do not print exception bodies: they may contain URL credentials.
            print(f"{label}: Abfrage fehlgeschlagen ({type(exc).__name__}).", file=stderr)
            failures += 1
            continue
        print("---", file=stdout)
        print(f"# {label} ({'aktiviert' if enabled else 'deaktiviert'}), {len(tools)} Tools", file=stdout)
        print(yaml.safe_dump({name: [tool.name for tool in tools]},
                             sort_keys=False, allow_unicode=True).rstrip(), file=stdout)
        if details:
            for tool in tools:
                # Comments keep the entire output usable as YAML.
                description = tool.description or tool.title or ""
                info = f"{tool.name}\n{description}\n" + json.dumps(tool.input_schema, indent=2, ensure_ascii=False)
                for line in info.splitlines():
                    print(f"# {line}", file=stdout)
    if not queried:
        print("Keine passenden MCP-Server konfiguriert.", file=stderr)
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Wingman-YAML-Konfiguration")
    parser.add_argument("--wingman", help="Nur die Server dieses Wingmans abfragen")
    parser.add_argument("--enabled-only", action="store_true", help="Deaktivierte Server ueberspringen")
    parser.add_argument("--details", action="store_true", help="Beschreibungen und Parameterschemas anzeigen")
    args = parser.parse_args()
    # Preserve Unicode in PowerShell output and redirected files on Windows.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        config = yaml.safe_load(args.config.read_text(encoding="utf-8-sig"))
        return asyncio.run(run(config, wingman=args.wingman,
                               enabled_only=args.enabled_only, details=args.details))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Konfiguration konnte nicht gelesen werden ({type(exc).__name__}).", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
