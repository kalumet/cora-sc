from abc import ABC, abstractmethod

from wingmen.star_citizen_services.ai_context_enum import AIContext


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
        for cls in FunctionManager.__subclasses__():
            manager_instance = cls(config, secret_keeper)
            manager_instance.register_functions(self.function_registry)
            self.register_manager(manager_instance.get_context_mapping(), manager_instance)

    def get_managers(self, ai_context: AIContext) -> list:
        if ai_context in self.managers:
            return self.managers[ai_context]
        return []


class FunctionManager(ABC):
    def __init__(self, config, secret_keeper):
        self.config = config
        self.secret_keeper = secret_keeper

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


# class ExampleManager(FunctionManager):
#     """  
#         This is an example implementation structure that can be copy pasted for new managers.
#     """
#     def __init__(self, config, secret_keeper):
#         super().__init__(config, secret_keeper)
#         # do further initialisation steps here
      
#     # @abstractmethod - overwritten
#     def register_functions(self, function_register):
#         """  
#             You register a method(s) that can be called by openAI.
#         """
#         function_register[self.example_function.__name__] = self.example_function
    
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
    
#     # @abstractmethod - overwritten
#     def get_function_prompt(self) -> str:
#         """  
#             Here you can provide instructions to open ai on how to use this function. 
#         """
#         return (
#             f"Call the function {self.example_function.__name__} if the user wants an example. Be aware of the following rules that apply:"
#         )
    
#     # @abstractmethod - overwritten
#     def get_context_mapping(self) -> AIContext:
#         """  
#             This method returns the context this manager is associated to. This means, that this function will only be callable if the current context matches the defined context here.
#         """
#         return AIContext.CORA    

#     def example_function(self, args):
#         # this must always return a json.dumps thing
#         return json.dumps(
#             {"success": True, "instructions": "Provide an example joke about Chuck Norris with the given theme.", "message": {"joke_theme": "coding"}}
#         )
