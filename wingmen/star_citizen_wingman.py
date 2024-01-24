import json
import time
import traceback
import random
import asyncio
from difflib import SequenceMatcher
from openai import OpenAI
from elevenlabs import generate, stream, Voice, voices
from services.printr import Printr
from services.secret_keeper import SecretKeeper
from wingmen.open_ai_wingman import OpenAiWingman

from wingmen.star_citizen_services.ai_context_enum import AIContext
from wingmen.star_citizen_services.keybindings import SCKeybindings
from wingmen.star_citizen_services.uex_api import UEXApi
from wingmen.star_citizen_services.mission_manager import MissionManager 
from wingmen.star_citizen_services.uex_update_service.uex_data_runner import UexDataRunnerManager  
from wingmen.star_citizen_services.overlay import StarCitizenOverlay
from wingmen.star_citizen_services.tdd_manager import TddManager
from wingmen.star_citizen_services.function_manager import StarCitizensAiFunctionsManager, FunctionManager

DEBUG = True


def print_debug(to_print):
    if DEBUG:
        print(to_print)


printr = Printr()
try:
    import pydirectinput as key_module
except AttributeError:
    # TODO: Instead of creating a banner make this an icon in the header
    # printr.print_warn(
    #     "pydirectinput is only supported on Windows. Falling back to pyautogui which might not work in games.",
    #     wait_for_gui=True
    # )
    import pyautogui as key_module


class StarCitizenWingman(OpenAiWingman):
    """This Wingman uses the OpenAiWingman as basis, but has some major differences:

    1. It has Multi-Wingman Capabilities
    - Execute instant Actions as of OpenAiWingman using the standard configuration -> Great for this!
    - Execute command chains as of OpenAiWingman (combining a series of key presses) -> Great for this!
    
    Big differences starts now:
    - Execute star-citizen commands as specified by your current keybinding-settings for a given release and your custom keybind settings. All it needs is the default keybinding file + your exported keybinds overwrites. You only need to config complex commands or your own instant activation phrases.
    - All ingame commands are available. Instant Activation commands are provided for each of them dynamically. Commands can be filtered. Per Default, commands without keybinds are discarded. All commands can be checked in generated files.
    - incorporates UEX trading API letting you ask for best trade route (1 stop) between locations, best trade route from a given location, best sell option for a commodity, best selling option for a commodity at a location
    - TODO incorporates Galactepedia-Wiki search to get more detailed information about the game world and lore in game
    - DONE incorporates Delivery Mission Management: based on delivery missionS (yes multiple) you are interested in, it will analyse the mission text, extract the payout, the locations from where you have to retrieve a package and the associated delivery location, calculates the best collection and delivery route to have to travel the least possible stops + incorporates profitable trade routes between the stops to earn an extra money on the trip.
    - DONE based on a given trading consoles it will extract the location, commodity prices and stock levels and update the prices automatically in the UEX database
    
    2. smart Action selection with reduced context size
    - The system will get your command and will first ask GPT what kind of Action the user wants to execute (one of the above)
    - The response will be used, to make another call to GPT now with the appropriate context information (commands for keypresses, trading calls, wiki calls, box mission calls...)

    3. TODO Context-Logic cache: depending on your tasks, it will have different conversation-caches that will be selected on demand. Examples
    - If you execute a simple command, there is no need for a history, every gpt call can be fresh, effectively reducing cost of api usage. 
    - If you do a box mission, it will keep the history until you have completed your box mission(s), beeing able to guide you from box to box
    - If you do a trade, it will keep the history until it understands that you start your trading route from a complete different location.
    
    3. TODO Cache-Logic for text-to-speech responses to reduce cost with config parameters to specify the ammount of responses to be cached vs. dropped vs. renewed
    """

    def __init__(
        self,
        name: str,
        config: dict[str, any],
        secret_keeper: SecretKeeper,
        app_root_dir: str,
    ):
        super().__init__(
            name=name,
            config=config,
            secret_keeper=secret_keeper,
            app_root_dir=app_root_dir,
        )
        
        self.contexts_history = {}  # Dictionary to store the state of different conversion contexts
        self.current_context: AIContext = AIContext.CORA  # Name of the current context
        self.current_user_request: str = None  # saves the current user request
        self.switch_context_executed = False  # used to identify multiple switch executions that would be incorrect -> Error
        self.sc_keybinding_service: SCKeybindings = None  # initialised in validate
        self.uex_service: UEXApi = None  # set in validate()
        self.mission_manager_service: MissionManager = None # initialized in validate()
        self.messages_buffer = 10
        self.current_tools = None # init in validate
        self.tdd_voice = self.config["openai"]["contexts"]["tdd_voice"]
        self.config["openai"]["tts_voice"] = self.config["openai"]["contexts"]["cora_voice"]
        self.config["sound"]["play_beep"] = False
        self.config["sound"]["effects"] = ["INTERIOR_HELMET", "ROBOT"]
        self.config["openai"]["conversation_model"] = self.config["openai"]["contexts"][f"context-{AIContext.CORA.name}"]["conversation_model"]
        self.overlay = None # init in validate
        self.ai_functions = {} # init in validate
        self.ai_functions_manager: StarCitizensAiFunctionsManager = None  # init in validate
        
        # init the configuration dynamically based on current star citizen settings.
        # the config is dynamically expanded for all mapped keybinds.
        # the user only configures special commands i.e. combination of keybindings to press

    def validate(self):
        errors = super().validate()
        
        uex_api_key = self.secret_keeper.retrieve(
            requester=self.name,
            key="uex",
            friendly_key_name="UEX API key",
            prompt_if_missing=True,
        )
        if not uex_api_key:
            errors.append(
                "Missing 'uex' API key. Please provide a valid key in the settings."
            )
            return
        
        uex_access_code = self.secret_keeper.retrieve(
            requester=self.name,
            key="uex_access_code",
            friendly_key_name="UEX Data Runner access code",
            prompt_if_missing=True,
        )
        if not uex_access_code:
            errors.append(
                "Missing 'uex_access_code' Data Runner access code key. Please provide a valid access code in the settings."
            )
            return

        try:
            # every conversation starts with the "context" that the user has configured
            self.uex_service = UEXApi.init(uex_api_key, uex_access_code)
            self.mission_manager_service = MissionManager(config=self.config)
            self.sc_keybinding_service = SCKeybindings(self.config, self.secret_keeper)
            self.sc_keybinding_service.parse_and_create_files()

            self.ai_functions_manager = StarCitizensAiFunctionsManager(self.config, self.secret_keeper)

            self.current_tools = self._get_context_tools(self.current_context)
            self.overlay = StarCitizenOverlay()
            self._set_current_context(AIContext.CORA, new=True)

            printr.print_err(
                ("IMPORTANT INFORMATION about this WingmenAI extension! \n"
                "This tool requires an OpenAI API. Data is transmitted to OpenAI. This incures costs. You cannot use this tool without valid API keys. \n"
                "This tool takes Screenshots of ingame elements. It will only make screenshots on given commands and only if the active window is 'Star Citizen'. \n"
                "BUT IT TAKES THEM. Do not use this tool if you are not trusting the source. \n"
                "This tool is open source and comes as is and without waranty. Use at your own risk. \n"
                "With that said, I hope you enjoy the tool and that it will make your game experience in star citizen even better. "
            ), wait_for_gui=True)
            printr.print((
                            "IMPORTANT INFORMATION about this WingmenAI extension! \n"
                            "This tool requires an OpenAI API. Data is transmitted to OpenAI. This incures costs. You cannot use this tool without valid API keys. \n"
                            "This tool takes Screenshots of ingame elements. It will only make screenshots on given commands and only if the active window is 'Star Citizen'. \n"
                            "BUT IT TAKES THEM. Do not use this tool if you are not trusting the source. \n"
                            "This tool is open source and comes as is and without waranty. Use at your own risk. \n"
                            "With that said, I hope you enjoy the tool and that it will make your game experience in star citizen even better. \n\n"
                        ), tags="err", wait_for_gui=True)

            # self.mission_manager_service.get_new_mission()  # TODO nur ein Test auskommentieren
            # self.kiosk_prices_manager.identify_kiosk_prices()  # TODO nur ein Test auskommentieren
        except Exception as e:
            print(e)
            traceback.print_exc()
            errors.append(f"Initialisation Error: {e}. Check console for more information")

    def _set_current_context(self, new_context: AIContext, new: bool = False):
        """Set the current context to the specified context name."""
        self.current_context = new_context

        if new:
            # initialise a new context conversation history
            self.current_tools = self._get_context_tools(current_context=new_context)
            self.current_context = new_context
            context_prompt = f'{self.config["openai"]["contexts"].get(f"context-{new_context.name}")}'
            functions_prompt = " "

            context_switch_prompt = ""
            if new_context == AIContext.CORA:
                context_prompt += (
                    f' The character you are supporting is named "{self.config["openai"]["player_name"]}". '
                    f'His title is {self.config["openai"]["player_title"]}. His ship call id is {self.config["openai"]["ship_name"]}. '
                    f'He wants you to respond in {self.config["sc-keybind-mappings"]["player_language"]}'
                )
                
                context_switch_prompt += f" Switch to context {AIContext.TDD}, if the player is calling a specific Trading Division, like 'Hurston Trading Division, this is Delta 7, Over'."

            if new_context == AIContext.TDD:
                context_switch_prompt += (
                    f" Whenever the player adresses a new Trading Division Location, switch the employee "
                    f"by calling the function switch_tdd_employee and select a different employee_id. "
                    f"If the current user request does not fit the current context, switch to an appropriate context "
                    f"by calling the switch_context function. Do switch to context {AIContext.CORA}, "
                    f"if the player adresses 'Cora' or using words like 'computer' or demanding a specific player or ship action or mission related actions. "
                    f'He wants you to respond in {self.config["sc-keybind-mappings"]["player_language"]}'
                )

            # add all additional function prompts of implemented managers for the given context.
            for ai_function_manager in self.ai_functions_manager.get_managers(new_context):
                ai_function_manager: FunctionManager
                functions_prompt += ai_function_manager.get_function_prompt()
            
            context_prompt += functions_prompt

            self.messages = [{"role": "system", "content": f'{context_prompt}. On a request of the Player you will identify the context of his request. The current context is: {new_context.value}. Follow these rules to switch context: {context_switch_prompt}'}]
        else:
            # get the saved context history
            tmp_new_context_history = self.contexts_history[new_context]
            self.current_tools = tmp_new_context_history.get("tools").copy()
            self.messages = tmp_new_context_history.get("messages").copy()
            self.current_context = new_context

        if new_context == AIContext.CORA:
            self.messages_buffer = 10 # we don't need much memory for a given action
            self.current_tools = self._get_context_tools(current_context=new_context)  # recalculate tools
        elif new_context == AIContext.TDD:
            self.messages_buffer = 20 # dealing on the journey of the player to trade might require more context-information in the conversation
        
    def _save_current_context(self):
        """Save the current conversation history under the current context."""
        if self.current_context is not None:
            self.contexts_history[self.current_context] = { "messages": self.messages.copy(),
                                                            "tools": self.current_tools
                                                        }

    def _switch_context(self, new_context_name):    
        """Switch to a different context, saving the current one."""
        try:
            # Versuche, den Kontext basierend auf dem Namen zu finden
            # context_to_switch_to = AIContext(new_context_name)
            context_to_switch_to = next((context for context in AIContext if context.value == new_context_name), None)

            if context_to_switch_to is None:
                # Handle the case where the context is not found
                # For example, log an error or notify the user
                print(f"Context '{new_context_name}' not found.")
                return

            # Überprüfe, ob der Kontext im Dictionary existiert
            if context_to_switch_to in self.contexts_history:
                # Logik für den Fall, dass der Kontext existiert
                printr.print(f"Lade context {context_to_switch_to}.", tags="info")
                self._save_current_context()
                self._set_current_context(new_context=context_to_switch_to)
                
            else:
                # Logik für den Fall, dass der Kontext nicht existiert
                printr.print(f"Erstelle context {context_to_switch_to}.", tags="info")
                self._save_current_context()
                self._set_current_context(new_context=context_to_switch_to, new=True)

        except AttributeError:
            # Fehlerbehandlung, falls der Kontextname nicht existiert
            print_debug(f"Kontext {new_context_name} ist kein gültiger Kontext.")

    def _get_context_tools(self, current_context: AIContext):
        if current_context == AIContext.CORA:
            return self._get_cora_tools()
        elif current_context == AIContext.TDD:
            tdd_tools = []
            for ai_function_manager in self.ai_functions_manager.get_managers(current_context):
                ai_function_manager: FunctionManager
                tdd_tools.extend(ai_function_manager.get_function_tools())
            tdd_tools.append(self._context_switch_tool(current_context=AIContext.TDD))
            return tdd_tools
        else:
            return self._context_switch_tool()
       
    async def _get_response_for_transcript(
        self, transcript: str, locale: str | None
    ) -> tuple[str, str]:
        """Overwritten to deal with dynamic context switches.

        Summary: This implementation is an extended version of the original, 
        specifically adapted to handle dynamic context switches and additional 
        functionalities related to instant commands and GPT call logic.
        
        Gets the response for a given transcript.

        This function interprets the transcript, runs instant commands if triggered,
        calls the OpenAI API when needed, processes any tool calls, and generates the final response.
        

        Args:
            transcript (str): The user's spoken text transcribed.

        Returns:
            A tuple of strings representing the response to a function call and an instant response.
        """
        self.last_transcript_locale = locale
        self.current_user_request = transcript

        # instant_response = self._execute_instant_activation_command(transcript)
        # if instant_response:
        #     return instant_response, instant_response
        # if instant_response is False:
        #     return False, False

        instant_response = self._try_instant_activation(transcript)  # we try instant activation, else we let gpt decide
        if instant_response:
            return instant_response, instant_response

        self._add_user_message(transcript)
        response_message, tool_calls = self._make_gpt_call()

        if tool_calls:
            instant_response = await self._handle_tool_calls(tool_calls)
            
            # if self.switch_context_executed:
            #     instant_response = None
            #     response_message = None
            #     tool_calls = None
            #     # repeat the gpt call now in the new switched context
            #     print_debug("switched context")
            #     # msg = {"role": "user", "content": transcript}
            #     # self.messages.append(msg)
            #     # response_message, tool_calls = self._make_gpt_call()
            #     self.switch_context_executed = False # might be problematik, if gpt tries to make another context switch.
            #     # if tool_calls:
            #     #     instant_response = await self._handle_tool_calls(tool_calls)

            # if instant_response: # might be "Error"
            #     return instant_response, instant_response

            summarize_response = self._summarize_function_calls()
            return self._finalize_response(str(summarize_response))

        # print_debug(self.messages[1:])
        if not response_message:
            return {"success": False, "instructions": "there has been an error. User should clear history, check logs and retry."}

        return response_message.content, response_message.content

    def _make_gpt_call(self):
        completion = self._gpt_call()

        if completion is None:
            return None, None

        response_message, tool_calls = self._process_completion(completion)

        # do not tamper with this message as it will lead to 400 errors!
        self.messages.append(response_message)
        return response_message, tool_calls

    def _cleanup_conversation_history(self):
        """
        Overwritten from openai_ai_wingman to deal with context switches, as every context has his own message buffer.
        Cleans up the conversation history by removing messages that are too old.
        Overwritten with context switch sensitive message buffers"""
        remember_messages = self.messages_buffer

        if remember_messages is None:
            return

        # Calculate the max number of messages to keep including the initial system message
        # `remember_messages * 2` pairs plus one system message.
        max_messages = (remember_messages * 2) + 1

        # every "AI interaction" is a pair of 2 messages: "user" and "assistant" or "tools"
        deleted_pairs = 0

        while len(self.messages) > max_messages:
            if remember_messages == 0:
                # Calculate pairs to be deleted, excluding the system message.
                deleted_pairs += (len(self.messages) - 1) // 2
                self.reset_conversation_history()
            else:
                while len(self.messages) > max_messages:
                    del self.messages[1:3]
                    deleted_pairs += 1

        if self.debug and deleted_pairs > 0:
            printr.print(
                f"   Deleted {deleted_pairs} pairs of messages from the conversation history.",
                tags="warn",
            )

    def _build_tools(self) -> list[dict]:
        """
        Overwritten. We calculate the tools when we switch contexts.

        Returns:
            list[dict]: A list of tool descriptors in OpenAI format.
        """
        return self.current_tools

    async def _execute_command_by_function_call(
        self, function_name: str, function_args: dict[str, any]
    ) -> tuple[str, str]:
        """
        Overwritten to allow in game commands to be executed by command-name reference.

        Uses an OpenAI function call to execute a command. If it's an instant activation_command, one if its reponses will be played.

        Args:
            function_name (str): The name of the function to be executed.
            function_args (dict[str, any]): The arguments to pass to the function being executed.

        Returns:
            A tuple containing two elements:
            - function_response (str): The text response or result obtained after executing the function.
            - instant_response (str): An immediate response or action to be taken, if any (e.g., play audio).
        """
        
        function_response = ""
        instant_reponse = ""
        # our context switcher. If this is called by GPT, we switch to this context (with its own memory).
        # we have to repeat the user request on this switched context, to get a valid response.
        if function_name == "switch_context":
            return self._execute_switch_context_function(function_args)
        
        if function_name == "execute_command":
            # get the command from config file based on the argument passed by GPT
            command = self._get_command(function_args["command_name"])
            # execute the command
            if command:
                function_response = self._execute_command(command)
            else:
                function_response, instant_reponse = self._execute_star_citizen_keymapping_command(function_args["command_name"])

            # if the command has responses, we have to play one of them
            if command and command.get("responses"):
                instant_reponse = self._select_command_response(command)
                await self._play_to_user(instant_reponse)

        if function_name == "box_delivery_mission_management":
            mission_id = function_args.get("mission_id", None)
            confirmed_deletion = function_args.get("confirm_deletion", None)
            printr.print(f'-> Box Function: {function_args["type"]}', tags="info")
            function_response = json.dumps(self.mission_manager_service.manage_missions(type=function_args["type"], mission_id=mission_id, confirmed_deletion=confirmed_deletion))
            printr.print(f'-> Resultat: {function_response}', tags="info")
            self.current_tools = self._get_cora_tools()  # recalculate, as with every box mission, we have new information for the function call

        if function_name == "next_location_on_delivery_route_for_box_or_delivery_missions":
            printr.print('-> Command: get next delivery route location')
            function_response = json.dumps(self.mission_manager_service.manage_missions(type="get_first_or_next_location_on_delivery_route"))
            printr.print(f'-> Resultat: {function_response}', tags="info")
            self.current_tools = self._get_cora_tools()  # recalculate, as with every box mission, we have new information for the function call

        # finally, check for any function managers implementing the called function
        if function_name in self.ai_functions_manager.get_function_registry():
            function_to_call = self.ai_functions_manager.get_function(function_name)
            if callable(function_to_call):
                function_response = function_to_call(function_args)

        return json.dumps(function_response), instant_reponse

    def _execute_switch_context_function(self, function_args):
        print_debug(f'switching context call: {function_args["context_name"]}')
        # if self.switch_context_executed is True:
        #     # ups, there has already been a context switch before. We do avoid infinite loops here...
        #     printr.print(
        #         "   GPT trying to make multiple context switches, this is not allowed.",
        #         tags="warn",
        #     )
        #     self.switch_context_executed = False
        #     return "Error", None
        # first, we have to remove from the current context old information from the "old" request history, as it belongs to the context that we switch to
        context_messages = None
        if len(self.messages) >= 3:  # bis hierhin wurde hinzugefügt: benutzerrequest und gpt response (tool_call: switch!). Mit der system message,  müssen also mindestens 3 nachrichten vorhanden sein
            # wir entfernen die neuesten 2 nachrichten: user request + tool_call
            context_messages = self.messages[-2:]
            del self.messages[-2:]

            # get the command based on the argument passed by GPT
        context_name_to_switch_to = function_args["context_name"]
        self._switch_context(context_name_to_switch_to)
        if self.current_context == AIContext.CORA:
            self.config["openai"]["tts_voice"] = self.config["openai"]["contexts"]["cora_voice"]
            self.config["sound"]["play_beep"] = False
            self.config["sound"]["effects"] = ["INTERIOR_HELMET", "ROBOT"]
            self.config["openai"]["conversation_model"] = self.config["openai"]["contexts"][f"context-{AIContext.CORA.name}"]["conversation_model"]
        elif self.current_context == AIContext.TDD:
            self.config["openai"]["tts_voice"] = self.tdd_voice
            self.config["sound"]["play_beep"] = True
            self.config["sound"]["effects"] = ["RADIO", "INTERIOR_HELMET"]
            self.config["openai"]["conversation_model"] = self.config["openai"]["contexts"][f"context-{AIContext.TDD.name}"]["conversation_model"]
        self.messages.extend(context_messages)  # we readd the messages to the switched context.
        # self._add_user_message(self.current_user_request) # we readd the user message to the new context to make the same user request in the new context
        # context has been switched, so we can return the contexts swtich request
        # self.switch_context_executed = True
        function_response = f"switched to context {context_name_to_switch_to}, reevaluate the user request, keep the users language"
        instant_reponse = None
        return function_response, instant_reponse

    def _execute_star_citizen_keymapping_command(self, command_name: str):
        """This method will execute a keystroke as defined in the keybinding settings of the game"""
        command = self.sc_keybinding_service.get_command(command_name)

        if not command:
            print_debug(f"Command not found {command_name}")
            return json.dumps({"success": False, "error": f"Command not found {command_name}"}), f"Command not found {command_name}"

        avoid_filter_names = self.config.get("avoid-commands", [])
        avoid_filter_names_set = set(avoid_filter_names)
        if command_name in avoid_filter_names_set:
            print_debug(f"Command not allowed {command_name}")
            return json.dumps({"success": False, "error": f"Command not allowed {command_name}"}), f"Command not allowed {command_name}"

        # Definiere eine Reihenfolge für die Modifiertasten
        order = ["alt", "ctrl", "shift", "altleft", "ctrlleft", "shiftleft", "altright", "ctrlrigth", "shiftright"]
        modifiers = set(order)
        keys = command.get("keyboard-mapping").split("+")
        
        actionname = command.get("actionname")
        category = command.get("category")

        sc_activation_mode = command.get("activationMode")
        
        # we check, if the command is overwritten in the config
        overwrite_commands = self.config["sc-keybind-mappings"].get("overwrite_sc_command_execution",{})
        overwrite_command = overwrite_commands.get(command_name)
        if overwrite_command and overwrite_command.get("hold"):
            old_sc_activation_mode = sc_activation_mode
            sc_activation_mode = overwrite_command.get("hold")
            print_debug(f"overwritten activationMode: was {old_sc_activation_mode} -> {sc_activation_mode}")

        hold = self.config["sc-keybind-mappings"]["key-press-mappings"].get(sc_activation_mode)

        command_desc = None
        if not command.get("action-description-en"):
            if not command.get("action-label-en"):
                command_desc = actionname
            else:
                command_desc = command.get("action-label-en")
        else:
            command_desc = command.get("action-description-en")
        
        command_message = f'{command_desc}: {command.get("keyboard-mapping-en")}'
        
        printr.print(
                f"   Executing command: {command_message}",
                tags="info",
            )

        try: 
            if len(keys) > 1:
                keys = sorted(keys, key=lambda x: order.index(x) if x in order else len(order))
            elif hold == "double_tap":  # double tab is only one key always
                print_debug(f"double tab {keys[0]}")
                key_module.press(keys[0])
                time.sleep(0.050)
                key_module.press(keys[0])
                return "Ok", "Ok"
        
            if hold == "notSupported":
                return json.dumps({"success": "False", "message": f"{command_message}", "error": f"activation mode not supported {sc_activation_mode}"}), None

            active_modifiers = []

            for sc_key in keys:
                key = self.config["sc-keybind-mappings"]["key-mappings"].get(sc_key)  # not all star citizen key names are  equal to key_modul names, therefore we do a mapping
                if not key:  # if there is no mapping, key names are identical
                    key = sc_key

                if key in modifiers:
                    key_module.keyDown(key)
                    print_debug("modifier down: " + key)
                    active_modifiers.append(key)
                    continue

                if hold == "unknown":
                    print_debug("unknown activationMode assuming press: " + key)
                    key_module.press(key)

                if hold > 1:
                    print_debug("hold and release: " + key)
                    key_module.keyDown(key)  # apart of modifiers, we assume, that there is always only one further key that can be pressed ....
                    time.sleep(hold / 1000)  # transform in seconds
                    key_module.keyUp(key)
                else:
                    print_debug("press: " + key)
                    key_module.press(key)
            
            active_modifiers.reverse()  # Kehrt die Liste in-place um

            for modifier_key in active_modifiers:  # release modifiers in inverse order
                print_debug("modifier up: " + modifier_key)
                key_module.keyUp(modifier_key) 

            return "Ok", "Ok"
        except Exception as e:
            # Genereller Fehlerfang
            print_debug(f"Ein Fehler ist aufgetreten: {e.__class__.__name__}, {e}")
            return json.dumps({"success": "False", "error": f"{e}"}), None
      
    def _execute_command(self, command: dict):
        """Triggers the execution of a command. This implementation executes the defined star citizen commands.

        Args:
            command (dict): The command object from the config to execute

        Returns:
            str: the selected response from the command's responses list in the config. "Ok" if there are none.
        """
        if not command:
            return "Command not found"

        printr.print(f"-> Executing sc-command: {command.get('name')}", tags="info")

        if self.debug:
            printr.print(
                "Skipping actual keypress execution in debug_mode...", tags="warn"
            )

        response = None
        if len(command.get("sc_commands", [])) > 0 and not self.debug:
            for sc_command in command.get("sc_commands"):
                self._execute_star_citizen_keymapping_command(sc_command["sc_command"])
                if sc_command.get("wait"):
                    time.sleep(sc_command["wait"])
            if command.get("responses") is not False:
                response = self._select_command_response(command)

        if len(command.get("sc_commands", [])) == 0:  # is a default configuration
            return super()._execute_command(command)

        if not response:
            response = json.dumps({"success": True, "instruction": "Don't make any function call!"})
        return response

    def _context_switch_tool(self, current_context: AIContext = None) -> list[dict]:
        ai_context_values = [context.value for context in AIContext if context != current_context]

        tools = {
                "type": "function",
                "function": {
                    "name": "switch_context",
                    "description": "Switch to a different context of conversation. Only switch, if the player initiate the context switch.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "context_name": {
                                "type": "string",
                                "description": "The available context the player conversion can be switched to",
                                "enum": ai_context_values
                            }
                        },
                        "required": ["context_name"]
                    }
                }
            }
        return tools
    
    def _get_keybinding_commands(self) -> list[dict]:
        # get defined commands in config
        commands = [
            command["name"]
            for command in self.config.get("commands", [])
        ]

        command_set = set(commands)
        sc_commands = set(self.sc_keybinding_service.get_bound_keybinding_names())

        command_set.update(sc_commands)  # manually defined commands overwrites sc_keybindings

        tools = {
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "description": "Executes a player command. On successfull response, do follow the instructions in the response.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command_name": {
                                "type": "string",
                                "description": "The command to execute",
                                "enum": list(command_set)
                            }
                        },
                        "required": ["command_name"]
                    }
                }
            }
        return tools
    
    def _get_box_mission_tool(self):

        if self.mission_manager_service is None:
            print_debug("not yet initialised")
            return []
        
        mission_ids = self.mission_manager_service.get_mission_ids()
        if len(mission_ids) > 0:
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "box_delivery_mission_management",
                        "description": "Allows the player to add a new box mission, to delete a specific mission, to delete all missions or to get information about the next location he has to travel to",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "description": "The type of operation that the player wants to execute",
                                    "enum": ["new_delivery_mission", "delete_or_discard_all_missions", "delete_or_discard_one_mission_with_id", None]
                                },
                                "mission_id": {
                                    "type": "string",
                                    "description": "The id of the mission, the player wants to delete",
                                    "enum": mission_ids
                                },
                                "confirm_deletion": {
                                    "type": "string",
                                    "description": "User confirmed deletion",
                                    "enum": ["confirmed", "notconfirmed", None]
                                }
                            }
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "next_location_on_delivery_route_for_box_or_delivery_missions",
                        "description": (
                            "Identifies the next location where to pickup or drop boxes according to the calculated delivery route for the active delivery missions. "
                            "Always execute this function, if the user ask to get the next location. Do not call this function, if the user want's to have details about the current location."
                        ),
                    }
                },
            ]
        else:
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "box_delivery_mission_management",
                        "description": "Allows the player to add a new box mission, to delete a specific mission or to delete all missions",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "description": "The type of operation that the player wants to execute",
                                    "enum": ["new_delivery_mission"]
                                }
                            }
                        }
                    }
                }
            ]
        return tools
    
    def _get_cora_tools(self) -> list[dict]:
        tools = []
        tools.append(self._get_keybinding_commands())
        tools.extend(self._get_box_mission_tool())
        for ai_function_manager in self.ai_functions_manager.get_managers(AIContext.CORA):
            ai_function_manager: FunctionManager
            tools.extend(ai_function_manager.get_function_tools())
        tools.append(self._context_switch_tool(current_context=AIContext.CORA))
        return tools
