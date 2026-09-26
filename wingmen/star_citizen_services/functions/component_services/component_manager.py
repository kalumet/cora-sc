from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext


class ComponentManager(FunctionManager):
    """Owns MCP component tools and their CORA response guidance."""

    MANAGER_CONTEXT = AIContext.CORA
    MANAGER_DESCRIPTION = (
        "Provides ship component information, purchase locations, compatible parts, "
        "and loadout comparisons through configured MCP tools."
    )
    MANAGER_CAPABILITIES = [
        "Look up component details and performance stats",
        "Find and rank components by type, size, class, grade, and ship compatibility",
        "Find purchase locations and prices",
        "Look up ship loadouts and calculate component swaps",
    ]

    def get_context_mapping(self) -> AIContext:
        return AIContext.CORA

    def register_functions(self, function_register):
        # MCP discovery and execution belong to the central manager integration.
        pass

    def get_function_tools(self) -> list[dict]:
        return []

    def get_function_prompt(self) -> str:
        return (
            "For ship component questions, use the available MCP tools according to "
            "their descriptions: component details, filtered or ranked searches and "
            "ship compatibility, purchase locations and prices, ship loadouts, or "
            "calculations of component swaps. Only call tools present in the current "
            "tool list. If the needed tool is unavailable or its request fails, explain "
            "that the requested component information is currently unavailable. "
            "There is no local component lookup fallback. Do not invent component "
            "stats, prices, or purchase locations when data is missing. "
            "Provide a concise, TTS-friendly answer focused on the user's question, "
            "without mentioning URLs or technical API details."
        )
