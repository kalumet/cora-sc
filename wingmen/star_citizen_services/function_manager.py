import pkgutil
import importlib
import re
from pathlib import Path
from abc import ABC, abstractmethod
from openai import OpenAI, APIStatusError, AzureOpenAI

from services.open_ai import AzureConfig
from services.printr import Printr

from wingmen.star_citizen_services.ai_context_enum import AIContext

DEBUG = False

printr = Printr()


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class StarCitizensAiFunctionsManager:
    def __init__(self, config, secret_keeper):
        self.managers = {}
        """ 
            Every function manager is associated to a specific AIContext. Per AI Context, you get a list of all registered managers for this context.
            { AIContext: [list of associated managers]}
        """
        self.function_registry = {}
        """ 
            defines the method that needs to be executed when openAI is making a function call of the given name
            openai.function.name: manager.function(openai.function.function_args)
        """
        self.initialize_function_managers(config, secret_keeper)

    def register_manager(self, ai_context: AIContext, manager):
        ai_context_managers = self.managers.get(ai_context, [])
        ai_context_managers.append(manager)
        self.managers[ai_context] = ai_context_managers

    def register_function(self, function_name, function):
        self.function_registry[function_name] = function

    def get_function_registry(self):
        return self.function_registry
    
    def get_function(self, function_name):
        return self.function_registry.get(function_name)

    def initialize_function_managers(self, config, secret_keeper):
        # Define the package name where the managers are located
        package_name = 'wingmen.star_citizen_services.functions'
        
        # Import the package
        package = importlib.import_module(package_name)
        print_debug(f"Scanning package {package.__name__} for FunctionManagers")
        
        # Recursively import all modules and submodules
        def import_submodules(package):
            for loader, module_name, is_pkg in pkgutil.iter_modules(package.__path__, package.__name__ + '.'):
                # Import the module
                module = importlib.import_module(module_name)
                print_debug(f"  Scanning module {module.__name__} for FunctionManagers")
                
                # Iterate through attributes of the module
                for attribute_name in dir(module):
                    attribute = getattr(module, attribute_name)
                    print_debug(f"    Checking if {attribute_name} is a FunctionManager")

                    if isinstance(attribute, type) and issubclass(attribute, FunctionManager) and attribute is not FunctionManager:
                        print_debug(f"     -> YES")
                        # This is a FunctionManager subclass, register it accordingly
                        activate_module = config["features"].get(attribute.__name__, False)
                        if activate_module:
                            manager_instance = attribute(config, secret_keeper)
                            manager_instance.register_functions(self.function_registry)
                            print(f"{attribute.__name__} registered")
                            self.register_manager(manager_instance.get_context_mapping(), manager_instance)
                            manager_instance.after_init()
                        else: 
                            print(f"Skipping {attribute.__name__} as it is not activated in the config.")
                    else:
                        print_debug(f"     -> NO")
                        
                # If it's a package, we need to import its submodules as well
                if is_pkg:
                    subpackage = importlib.import_module(module_name)
                    import_submodules(subpackage)
        
        # Start the import process from the root package
        import_submodules(package)

    def get_managers(self, ai_context: AIContext) -> list:
        if ai_context in self.managers:
            return self.managers[ai_context]
        return []


class FunctionManager(ABC):
    def __init__(self, config, secret_keeper):
        self.config = config
        self.secret_keeper = secret_keeper
        self.conversation_client: OpenAI = None
        self.name = self.__class__.__name__
        self.conversation_model = "gpt-4o"

    def after_init(self):
        """  
            This method can be implemented to execute logic that needs to be run after all initialization steps.
        """
        pass

    def cora_start_information(self):
        """  
            This method can be implemented to retrieve information from the manager, that Cora should provide to the user on startup.
        """
        return ""
    
    def ask_ai(self, system_prompt: str, user_prompt: str, max_tokens=512, temperature=0.7, response_format={"type": "json_object"}):
        """
        Ask configured conversation provider for a response to the given prompts.
            Params:
                system_prompt: str - The system prompt to be sent to the conversation provider
                user_prompt: str - The user prompt to be sent to the conversation provider
                max_tokens: int - The maximum number of tokens to generate
                temperature: float - The sampling temperature
                response_format: dict - The response format to be returned. Default is a JSON object.
        """
        self._init_conversation_client()
        try: 
            completion = self.conversation_client.chat.completions.create(
                model=self.conversation_model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                response_format=response_format,
            )
            return completion
        except APIStatusError as e:
            self._handle_api_error(e)
            return None
        except UnicodeEncodeError:
            printr.print_err(
                "The OpenAI API key you provided is invalid. Please check the GUI settings or your 'secrets.yaml'"
            )
            return None
    
    @abstractmethod
    def register_functions(self, function_register):
        """  
            This method is used to register all implemented functions in this manager that the AI can execute.
        """
        pass

    @abstractmethod
    def get_function_tools(self) -> list[dict]:
        """  
            This method returns all OpenAI function definitions that are implemented by this manager.
        """
        pass

    @abstractmethod
    def get_function_prompt(self) -> str:
        """  
            This method allows to append specific instructions to the OpenAI systems message.
        """
        pass

    @abstractmethod
    def get_context_mapping(self) -> AIContext:
        """  
            This method returns the context this manager is associated to
        """
        pass

    def _init_conversation_client(self):
        """
            This method initializes the conversation client for the manager on first use.
        """
        if not self.conversation_client:
            openai_api_key = self.secret_keeper.retrieve(
                requester=self.name,
                key="openai",
                friendly_key_name="OpenAI API key",
                prompt_if_missing=True,
            )
            if not openai_api_key:
                print("Missing 'openai' API key. Please provide a valid key in the settings.")
            else:
                openai_organization = self.config["openai"].get("organization")
                openai_base_url = self.config["openai"].get("base_url")
                self.conversation_client = OpenAI(
                    api_key=openai_api_key,
                    organization=openai_organization,
                    base_url=openai_base_url,
            )
                
            self.conversation_model = self.config["openai"].get("conversation_model")

            if self.config["features"].get(
                "conversation_provider", "openai"
            ) == "azure":
                azure_api_key = self.secret_keeper.retrieve(
                        requester=self.name,
                        key="azure_conversation",
                        friendly_key_name="Azure Conversation API key",
                        prompt_if_missing=True,
                    )
                
                self.conversation_client = AzureOpenAI(
                    api_key=azure_api_key,
                    azure_endpoint=self.config["azure"]
                    .get("conversation", {})
                    .get("api_base_url", None),
                    api_version=self.config["azure"].get("conversation", {}).get("api_version", None),
                    azure_deployment=self.config["azure"]
                    .get("conversation", {})
                    .get("deployment_name", None),
                )

    def _handle_api_error(self, api_response):
        printr.print_err(
            f"The OpenAI API send the following error code {api_response.status_code} ({api_response.type})"
        )
        # get API message from appended JSON object in the "message" part of the exception
        m = re.search(
            r"'message': (?P<quote>['\"])(?P<message>.+?)(?P=quote)",
            api_response.message,
        )
        if m is not None:
            message = m["message"].replace(". ", ".\n")
            printr.print(message, tags="err")
        elif api_response.message:
            printr.print(api_response.message, tags="err")
        else:
            printr.print("The API did not provide further information.", tags="err")

# ─────────────────────────────────── ↓ EXAMPLE ↓ ─────────────────────────────────────────
# from wingmen.star_citizen_services.function_manager import FunctionManager
# from wingmen.star_citizen_services.ai_context_enum import AIContext
# class ExampleManager(FunctionManager):
#     """  
#         This is an example implementation structure that can be copy pasted for new managers.
#     """
#     def __init__(self, config, secret_keeper):
#         super().__init__(config, secret_keeper)
#         # do further initialisation steps here

#     # @abstractmethod - overwritten
#     def get_context_mapping(self) -> AIContext:
#         """  
#             This method returns the context this manager is associated to. This means, that this function will only be callable if the current context matches the defined context here.
#         """
#         return AIContext.CORA         

#     # @abstractmethod - overwritten
#     def register_functions(self, function_register):
#         """  
#             You register a method(s) that can be called by openAI.
#         """
#         function_register[self.example_function.__name__] = self.example_function

#     # @abstractmethod - overwritten
#     def get_function_prompt(self) -> str:
#         """  
#            This is the function definition for OpenAI, provided as a list of tool definitions:
#            Location names (planet, moons, cities, tradeports / outposts) are given in the system context, 
#            so no need to make reference to it here.
#         """
#         return (
#             f"Call the function {self.example_function.__name__} if the user wants an example. Be aware of the following rules that apply:"
#         ) 
        
#     # @abstractmethod - overwritten
#     def get_function_tools(self) -> list[dict]:
#         """  
#             This is the function definition for OpenAI, provided as a list of tool definitions:
#         """
#         tools = [
#             {
#                 "type": "function",
#                 "function": {
#                     "name": "execute_command",
#                     "description": "Executes a command",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "command_name": {
#                                 "type": "string",
#                                 "description": "The command to execute",
#                                 "enum": commands,
#                             },
#                         },
#                         "required": ["command_name"],
#                     },
#                 },
#             },
#         ]
#         return tools

#     def example_function(self, args):
#         # this must always return a json.dumps thing
#         return json.dumps(
#             {"success": True, "instructions": "Provide an example joke about Chuck Norris with the given theme.", "message": {"joke_theme": "coding"}}
#         )
