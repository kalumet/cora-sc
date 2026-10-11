"""Check and install MrKraken's StarStrings release when Cora starts."""

from pathlib import Path

from services.printr import Printr
from services.star_citizen_starstrings import StarStringsUpdater, configured_game_directory
from wingmen.star_citizen_services.ai_context_enum import AIContext
from wingmen.star_citizen_services.function_manager import FunctionManager


class StarStringsManager(FunctionManager):
    DEFAULT_ENABLED = True
    MANAGER_CONTEXT = AIContext.CORA
    MANAGER_DESCRIPTION = "Keeps the StarStrings English LIVE language pack up to date at Cora startup."
    MANAGER_CAPABILITIES = ["Install StarStrings LIVE language pack", "Check GitHub releases at startup"]

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        options = config.get("features", {}).get(self.name, {})
        options = options if isinstance(options, dict) else {}
        self.updater = StarStringsUpdater(configured_game_directory(config),
            Path(config.get("data-root-directory", "star_citizen_data")) / "starstrings",
            timeout=options.get("timeout_seconds", 15), report=self._report_update)

    def _report_update(self, result):
        printer = Printr()
        status = result["status"]
        if status == "failed":
            printer.print_warn(f"StarStrings: update failed: {result['error']}")
        elif status in {"installed", "updated", "current"}:
            printer.print(f"StarStrings: {status}: {result['release']}", tags="info")
        elif status == "skipped":
            printer.print(f"StarStrings: skipped: {result['reason']}", tags="info")

    def on_manager_enabled(self, source="manual"):
        self.updater.start()

    def on_manager_disabled(self, source="manual"):
        self.updater.close()

    def close_speech_sessions(self):
        self.updater.close()

    def get_context_mapping(self):
        return AIContext.CORA

    def register_functions(self, function_register):
        pass

    def get_function_tools(self):
        return []

    def get_function_prompt(self):
        return ""
