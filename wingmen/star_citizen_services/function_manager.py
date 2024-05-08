import pkgutil
import importlib
from pathlib import Path
from abc import ABC, abstractmethod

from wingmen.star_citizen_services.ai_context_enum import AIContext

DEBUG = False


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
                        manager_instance = attribute(config, secret_keeper)
                        manager_instance.register_functions(self.function_registry)
                        print(f"{attribute.__name__} registered")
                        self.register_manager(manager_instance.get_context_mapping(), manager_instance)
                        manager_instance.after_init()
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
