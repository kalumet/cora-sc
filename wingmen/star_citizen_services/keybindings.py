import xml.etree.ElementTree as ET
import csv
import json
import re
import json
import traceback
import os
import copy
import requests
import time

from services.secret_keeper import SecretKeeper

DEBUG = True


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class SCKeybindings():

    def __init__(self, config: dict[str, any], secret_keeper: SecretKeeper):
        self.config = config
        
        self.data_root_path = f'{self.config["data-root-directory"]}{self.config["sc-keybind-mappings"]["keybindings-directory"]}'
        self.sc_installation_dir = self.config["sc-keybind-mappings"]["sc_installation_dir"]
        self.user_keybinding_file_name = self.config["sc-keybind-mappings"]["user_keybinding_file_name"]
        self.sc_active_channel = self.config["sc-keybind-mappings"]["sc_active_channel"]
        self.sc_channel_version = self.config["sc-keybind-mappings"]["sc_channel_version"]
        self.json_path = f"{self.data_root_path}{self.sc_channel_version}/sc_all_keybindings.json"
        self.json_path_knowledge = f"{self.data_root_path}{self.sc_channel_version}/keybindings_existing_knowledge.json"
        self.json_path_miss_knowledge = f"{self.data_root_path}{self.sc_channel_version}/keybindings_missing_knowledge.json"
        self.keybindings: dict = None # will be filled on first access
        self.en_translation_file = self.config["sc-keybind-mappings"]["en_translation_file"]
        user_keybinding_file_config = f"{self.sc_installation_dir}/{self.sc_active_channel}/USER/Client/0/Controls/Mappings/{self.user_keybinding_file_name}"
        self.user_keybinding_file = user_keybinding_file_config.format(sc_channel_version=self.sc_channel_version)
        self.default_keybinds_file = f'{self.data_root_path}/{self.sc_channel_version}/{self.config["sc-keybind-mappings"]["sc_unp4k_file_default_keybindings_filter"]}'
        self.keybindings_localization_file = f'{self.data_root_path}/{self.sc_channel_version}/{self.config["sc-keybind-mappings"]["sc_unp4k_file_keybinding_localization_filter"]}'
        self.sc_translations_en = f"{self.data_root_path}/{self.sc_channel_version}/{self.en_translation_file}"
        self.player_language = self.config["openai"]["player_language"]
        self.sc_translations_player_language = f"{self.data_root_path}/{self.sc_channel_version}/global_{self.player_language}.ini"
        self.keybind_categories_to_ignore = set(self.config["keybind_categories_to_ignore"])
        self.keybind_actions_to_include_from_category = set(self.config["include_actions"]) 
        self.command_phrases_included = False # will be set to true on first update of instant activation commands
        self.open_api_key = secret_keeper.retrieve(
            requester="openai",
            key="openai",
            friendly_key_name="OpenAI API key",
            prompt_if_missing=False,
        )

        self.instant_activation_commands_built = False
        self.correct_keybinding_activations = False  # set to true, if ai response structure is slightly different and implement corrections method _correct_instant_activation_commands

    def _correct_instant_activation_commands(self):

        if not self.correct_keybinding_activations:
            return
        
        print("correcting instant activations commands")
        chunk = 4
        path = f"{self.data_root_path}{self.sc_channel_version}/completion_message_command_phrases_{chunk}.json"
        try: 
            response = ""
            with open(path, "r", encoding="utf-8") as file:
                response = json.load(file)

            keybindings = self._load_keybindings()
            
            updated_keybindings = response["choices"][0]["message"]["content"]["command-phrases"]

            # Da der "content" selbst ein JSON-String ist, müssen Sie diesen parsen
            updated_keybindings = json.loads(updated_keybindings)

            for key, value in updated_keybindings.items():
                print_debug(f"updating {key}")
                if key in keybindings:
                    command_phrases = value["command-phrases"]
                    keybindings.get(key)["command-phrases"] = command_phrases

            with open(self.json_path_knowledge, mode="w", encoding="utf-8") as file:
                json.dump(keybindings, file, indent=4, ensure_ascii=False)
        except Exception:
            traceback.print_exc()
            return
    
    def get_bound_keybinding_names(self) -> list:
        self._load_keybindings()

        filtered = []
        
        avoid_commands = set(self.config["ignored_actionnames"])
        include_actions = set(self.config["include_actions"])

        avoid_commands.difference_update(include_actions)

        for key, keybindingEntry in self.keybindings.items():
            if keybindingEntry["actionname"] in avoid_commands and not keybindingEntry["category"] in self.keybind_categories_to_ignore:
                continue
            filtered.append(key)

        if not self.instant_activation_commands_built:
            self._build_instant_activation_commands(filtered)
            self.instant_activation_commands_built = True
               
        return filtered
    
    def _build_instant_activation_commands(self, commands_to_consider):
        try: 
            custom_commands_list = [
                command["name"]
                for command in self.config.get("commands", [])
            ]

            custom_commands = set(custom_commands_list)  
            self._load_keybindings()

            for key, keybinding_entry in self.keybindings.items():
                if key in custom_commands or key not in commands_to_consider:
                    continue  # we skip actions that have been customized in config or that we don't consider
                
                command = {}
                command["name"] = key
                
                sc_commands = []
                sc_commands.append({"sc_command": key})
                command["sc_commands"] = sc_commands
                
                player_language = "en"
                instant_activations = []
                command_phrases = {}
                if keybinding_entry.get("command-phrases"):
                    command_phrases = keybinding_entry.get("command-phrases")

                for command_phrase in command_phrases.get(player_language, []):
                    instant_activations.append(command_phrase)

                if self.player_language and not self.player_language.startswith("en"):
                    player_language = self.player_language

                    for command_phrase in command_phrases.get(player_language, []):
                        instant_activations.append(command_phrase)
                
                command["instant_activation"] = instant_activations

                command["responses"] = False  # we don't want any AI reaction for player actions

                self.config["commands"].append(command)
        except Exception:
            traceback.print_exc()

    def _create_instant_activation_value(self):
        print("creating command phrases first time, this can take several minutes.")

        keybindings = self._load_keybindings()
        keybindings_reduce = copy.deepcopy(keybindings)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.open_api_key}",
        }
        model = "gpt-4-1106-preview"

        attributes_to_remove = [
            "actionname",
            "activationMode",
            "keyboard-mapping",
            "keyboard-mapping-en",
            f"keyboard-mapping-{self.player_language}",
        ]

        # Entfernen der spezifizierten Attribute aus jedem Eintrag in der JSON-Struktur
        keybindings_to_update = {}
        for action, item in keybindings_reduce.items():
            for key in attributes_to_remove:
                item.pop(key, None)
                if self.config["regenerate_all_instant_commands"]:
                    item.pop("command-phrases", None)
                    keybindings_to_update[action] = item
                else:
                    # only update the item, if it has no "command-phrases"
                    if not item.get("command-phrases", None):
                        keybindings_to_update[action] = item

        chunk_size = 40
        chunk = 0
        totalItems = len(list(keybindings_to_update.keys()))
        items_list = list(keybindings_to_update)
        print_debug(f"retrieving command phrases for a total of {totalItems} actions")
        index = 0

        while index < totalItems:
            keybindings_message_chunk = []
            chunk += 1
            print_debug(f"updating chunk {chunk} with index {index}")

            while index < chunk_size * chunk and index < totalItems:
                item = items_list[index]
                keybindings_message_chunk.append(item)

                index += 1
            
            messages = [
                {"role": "system", "content": "You are expert in handling json files and translations."},
                {"role": "user",    "content": (
                                        "Analyse the following json an fill in for each action the attribute 'command-phrases' which should contain a list of sentences the user can call out as commands. "
                                        "A command phrase should have at least 1 word and not more then 4. "
                                        "The command phrases must be intuitive, and be in the style of a command a user would call out to somebody that must execute the action. "
                                        "Each entry must only contain the command, nothing else, therefore, it should not contain any abbreviations, punctuation marks or any other non alphanumerical characters. "
                                        "Further, the sentences should be simple, but it must be unique among all actions in the json-file."
                                        "Provide - if possible and - a 1 word command phrase, 2 two word command phrases and 1 three word command phrase."
                                        "For each action, provide command phrases in the available languages of the action. "
                                        "An example for the 'command-phrases' attribute is: 'instant-activation-sentences': {'en': ['Roll left', 'Left roll'], 'de_DE': ['Links rollen', 'Rolle links']}. "
                                        f"Apart of en, provide {self.player_language} commands as well. "
                                        "The commands should have as much context information as possible, be as precise as possible and as short as possible. Try to avoid combind words. Example 'Toggles the docking camera.' should not lead to a phrase 'Camera mode'. A good phrase would be 'Change docking view'"
                                        "The commands should not provide information on how to execute them. Example 'Engage Quantum Drive (Hold)' should not lead to a phrase 'Hold quantum' or 'Quantum standby'. A good phrase would be 'Engage Quantum Drive'. "
                                        "Whenever you process a command that is a toggle, provide at least 2 additional opposite command phrases. Example 'Open/Close Doors (Toggle) should lead at least to the two following command phrases: 'Open doors', 'Close doors'. In such a case, provide also a single word phrase like 'doors'.  "
                                        "Your response only contains the following json, nothing more, that you update with the provided command phrases for each entry. "
                                        f"json file: {json.dumps(keybindings_message_chunk)}"
                                    ) 
                }
            ]
            response = None
            try:
                # # client = OpenAI()

                payload = {
                    "model": model,
                    "response_format": { "type": "json_object" },
                    "messages": messages
                }

                response = requests.post(
                    "https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=300
                )
            
                print_debug("got response")
                response_json = response.json()

                if response_json.get("error", False):
                    print(f'Error during request: {response_json["error"]["type"]} skipping. {response_json}')
                    return # stop the program, as we can't continue without the response

                path = f"{self.data_root_path}{self.sc_channel_version}/completion_message_command_phrases_{chunk}.json"
                
                updated_keybindings = response_json["choices"][0]["message"]["content"]
                # Da der "content" selbst ein JSON-String ist, müssen Sie diesen parsen
                updated_keybindings = json.loads(updated_keybindings)
                with open(path, mode="w", encoding="utf-8") as file:
                    json.dump(updated_keybindings, file, indent=4)
                
                for key, value in updated_keybindings.items():
                    print_debug(f"updating {key}")
                    if key in keybindings:
                        command_phrases = value["command-phrases"]
                        keybindings.get(key)["command-phrases"] = command_phrases

                with open(self.json_path_knowledge, mode="w", encoding="utf-8") as file:
                    json.dump(keybindings, file, indent=4, ensure_ascii=False)
            except Exception:
                traceback.print_exc()
                return
    
    def get_command(self, command_name: str) -> dict:
        self._load_keybindings()
        command = self.keybindings.get(command_name)
        if command:
            return command
        
        return None

    def _load_keybindings(self) -> dict:
        if not self.keybindings:
            with open(self.json_path_knowledge, "r", encoding="utf-8") as file:
                self.keybindings = json.load(file)
        return self.keybindings
    
    def _load_sc_all_keybindings(self) -> dict:
        with open(self.json_path, "r", encoding="utf-8") as file:
            actions = json.load(file)
        return actions

    def _load_translations(self, file_path):
        """Load translations from a given INI file."""
        translations = {}
        print_debug(f"loading localisation {file_path}")
        with open(file_path, "r", encoding="utf-8", errors='ignore') as file:
            for line in file:
                if "=" in line:
                    key, value = line.split("=", 1)
                    translations[key.strip()] = value.strip()
        return translations

    def _update_actions_with_translations(self, actions, translations, language_suffix):
        """Update actions with translations for a specified language."""
        for action_name, action_details in actions.items():
            # Prüfe, ob die UI-Labels vorhanden und nicht None sind
            ui_label_key = action_details.get("label-ui")
            ui_description_key = action_details.get("description-ui")

            if ui_label_key:
                ui_label_key = ui_label_key.lstrip("@")
                action_details[f"action-label-{language_suffix}"] = translations.get(ui_label_key, "")
            else:
                action_details[f"action-label-{language_suffix}"] = ""

            if ui_description_key:
                ui_description_key = ui_description_key.lstrip("@")
                action_details[f"action-description-{language_suffix}"] = translations.get(ui_description_key, "")
            else:
                action_details[f"action-description-{language_suffix}"] = ""

            keybinding_ui = action_details.get("keyboard-mapping-ui", "")
            if keybinding_ui:
                localized_parts = [translations.get(part.strip().lstrip("@"), part.strip().lstrip("@")) for part in keybinding_ui.split("+") if part.strip()]
                action_details[f"keyboard-mapping-{language_suffix}"] = "+".join(localized_parts)
            else:
                action_details[f"keyboard-mapping-{language_suffix}"] = ""

    # Helper function to replace key names with their localization strings
    def _localize_keybinding(self, localization_map, keybinding):
        if not keybinding or keybinding.isspace():
            return keybinding  # Return as is if no keybinding is present
        parts = keybinding.split("+")
        localized_parts = [localization_map.get(part, part) for part in parts]
        return "+".join(localized_parts)

    def _filter_actions(self, actions, inclusion_mode):
        """Filters the actions according to param onlyMissing
        
            onlyMissing = True -> returns only actions with no keyboard keybinds available
            onlyMissing = False -> returns only actions that have a keybind
        """
        return (details for details in actions.values() if self._include_action(details, inclusion_mode))

    def _include_action(self, action_details, inclusion_mode):
        keybinding = action_details.get("keyboard-mapping", "")
        # Prüfe auf leere oder None-Werte
        keybinding_exists = bool(keybinding and keybinding.strip())
        return (inclusion_mode and not keybinding_exists) or (not inclusion_mode and keybinding_exists)

    def _should_exclude_action(self, action_details, inclusion_mode):
        """ Checks if the action should be included in the final file
            if onlyMissing = False: we discard any actions with 
            - unsupported activation modes
            - missing keybinds
            - categories that we don't want at all

            if onlyMissing = True, we'll only keep the above ones

        """
        keybinding = action_details.get("keyboard-mapping", "")  # Standardwert als leerer String
        keybinding_exists = bool(keybinding.strip())  # Prüft, ob keybinding nicht leer ist
        
        not_supported_activation_mode = False
        if action_details.get("activationMode") == "hold" or action_details.get("activationMode") == "hold_toggle":
            not_supported_activation_mode = True

        excludedCategory = False
        if action_details.get("category") in self.keybind_categories_to_ignore and action_details.get("actionname") not in self.keybind_actions_to_include_from_category:
            excludedCategory = True

        if inclusion_mode == "discarded_keybindings_only":  # action should be written to file "missing"
            return not (not keybinding_exists or not_supported_activation_mode or excludedCategory)
        elif inclusion_mode == "only_allowed_keybindings":  # action should be written to file "existing"
            return not (keybinding_exists and not not_supported_activation_mode and not excludedCategory) 
        
        return False  # all keybindings should be included

    def _create_json_data(self, actions, inclusion_mode, content_keys, mode):
        json_data = {}
        print_debug(f"writing for inclusion mode {inclusion_mode}")
        for action_name, action_details in actions.items():
            if self._should_exclude_action(action_details, inclusion_mode):
                continue
            key_value = action_details.get("actionname", "").strip()

            # we want to have the most descriptive functionname
            if mode == "functionname":  
                if len(action_details.get("action-label-en", "")) > 5 or len(action_details.get("action-label-en", "")) > len(key_value):
                    key_value = action_details.get("action-label-en", "").strip()
                elif len(action_details.get("action-description-en", "")) > 5 and len(action_details.get("action-description-en", "")) > len(key_value):
                    key_value = action_details.get("action-description-en", "").strip()
                
                # and we want to have the category code in front, as it provides further context:
                if action_details.get("category"):
                    key_value = f'{action_details.get("category").strip()}_{key_value}'
                  
            json_entry = {key: action_details.get(key, "") for key in content_keys}

            json_key = ''.join([char if char.isalnum() else '_' for char in key_value])  # replace non alphanumerical values with _
            json_key = re.sub(r'_+', '_', json_key)  # remove duplicate _
            # Entfernt einen Unterstrich am Ende, falls vorhanden
            if json_key.endswith('_'):
                json_key = json_key[:-1]

            if not json_key:
                continue  # Leer oder keine gültigen Zeichen, Eintrag überspringen

            if json_key == "actionname":
                json_data[json_key] = action_name  # we always want the action name in our values
            else:
                json_data[json_key] = json_entry

        return json_data

    def _write_json(self, actions, path, inclusion_mode):
        content_keys = [
            "category",
            "actionname",
            "activationMode",
            "keyboard-mapping",
            "action-label-en",
            f"action-label-{self.player_language}",
            "action-description-en",
            f"action-description-{self.player_language}",
            "keyboard-mapping-en",
            f"keyboard-mapping-{self.player_language}",
            "keyboard-mapping-ui",
            "label-ui",
            "description-ui",
        ]
        json_data = self._create_json_data(actions, inclusion_mode, content_keys, "actionname")

        with open(path, mode="w", encoding="utf-8") as file:
            json.dump(json_data, file, indent=4, ensure_ascii=False)

        return path

    def _write_openai_knowledge_json(self, actions, path, inclusion_mode):
        content_keys = [
            "category",
            "actionname",
            "activationMode",
            "keyboard-mapping",
            "action-label-en",
            f"action-label-{self.player_language}",
            "action-description-en",
            f"action-description-{self.player_language}",
            "keyboard-mapping-en",
            f"keyboard-mapping-{self.player_language}",
            "command-phrases",
        ]
        json_data = self._create_json_data(actions, inclusion_mode, content_keys, "functionname")

        # Lade bestehende Daten, falls vorhanden
        if os.path.exists(path):
            print_debug(f"actualizing data {path}")
            with open(path, mode="r", encoding="utf-8") as file:
                existing_data = json.load(file)
            # Aktualisiere bestehende Daten basierend auf json_data
            for key in list(existing_data.keys()):
                print_debug(f"key: {key}")
                if key in json_data:
                    # the keybinding files already exist, and the action key are still the same-> we keep the first generated command-phrases (as the user is used to them)
                    command_phrases = existing_data[key].get("command-phrases", "")
                    existing_data[key] = json_data[key]  # this deletes the command-phrases ...
                    existing_data[key]["command-phrases"] = command_phrases
                else:
                    # Entferne Schlüssel, die nicht in json_data vorhanden sind
                    del existing_data[key]
            merged_data = existing_data
        else:
            merged_data = json_data

        # Schreibe die gemergten Daten zurück in die Datei
        with open(path, mode="w", encoding="utf-8") as file:
            json.dump(merged_data, file, indent=4, ensure_ascii=False)

        return path

    def _remove_prefix(self, keybinding):
        # prefix = "kb1_" # TODO, es können mehr prefixe existieren die entfernt werden müssen, sie sind immer mit "_" und tauchen nur in überschriebenen keybindings auf
        prefix_separator = "_"
        # Teile den String bei jedem "+" und entferne das Prefix von jedem Teil
        parts = keybinding.split("+")
        cleaned_parts = []
        for part in parts:
            prefixed_parts = part.strip().split(prefix_separator)
            if len(prefixed_parts) == 1:
                cleaned_parts.append(prefixed_parts[0])
            if len(prefixed_parts) == 2:
                cleaned_parts.append(prefixed_parts[1])

        # Füge die bereinigten Teile wieder zusammen
        return "+".join(cleaned_parts)

    def parse_and_create_files(self):
        if os.path.exists(self.json_path_knowledge) and self.config["update_keybindings"] is False:
            print_debug(f"keybind files already exist, delete file for full regeneration: {self.json_path_knowledge}")
            # we might want to correct some of the instant activation commands
            # correction can only be made through implementation of this function + setting the boolean to true.
            self._correct_instant_activation_commands()
            return
        elif os.path.exists(self.json_path_knowledge) and os.path.exists(self.json_path) and self.config["update_keybindings"] is True:
            print_debug("update keybinding information based on existing. ")
            actions = self._load_sc_all_keybindings()
            print_debug(f"loaded actions: {len(actions)}")
        else:
            # rebuild actions list from scratch
            # Load the XML file
            actions = self._build_sc_keybinding_default_actions()

        # Load the custom player keybindings file
        actions = self.load_custom_keybinds(actions)
        print(f"updated with player keybindings: {len(actions)}")

        if not os.path.exists(self.json_path):  # we only create this file, if it is not existing
            self._write_json(actions, self.json_path, inclusion_mode="all")
            print_debug(f"wrote actions to file: {len(actions)}")
        self._write_openai_knowledge_json(actions, self.json_path_miss_knowledge, inclusion_mode="discarded_keybindings_only")
        self._write_openai_knowledge_json(actions, self.json_path_knowledge, inclusion_mode="only_allowed_keybindings")

        self._create_instant_activation_value()
        self.keybindings = None 

    def _build_sc_keybinding_default_actions(self):
        file_path = self.default_keybinds_file
        print_debug("loading default keybinds")
        tree = ET.parse(file_path)
        root = tree.getroot()

        # Extracting the required information from the XML structure and checking for duplicates
        actions = {}
        duplicates = []

        for actionmap in root.findall(".//actionmap"):
            category_code = actionmap.get("name")
            for action in actionmap.findall(".//action"):
                action_name = action.get("name")
                activation_mode = action.get("activationMode")
                keyboard_mapping = action.get("keyboard", None)
                label_ui = action.get("UILabel")
                description_ui = action.get("UIDescription")

                # Überspringe die Aktion, wenn das Attribut "keyboard" im XML fehlt
                if keyboard_mapping is None:
                    continue

                entry = {
                        "category": category_code,
                        "actionname": action_name,
                        "activationMode": activation_mode,
                        "keyboard-mapping": keyboard_mapping,
                        "label-ui": label_ui,
                        "description-ui": description_ui,
                    }

                # Check for duplicate action names
                if action_name in actions:
                    duplicates.append(entry)
                else:
                    actions[action_name] = entry

        print_debug(f"loaded keybindings from sc filed: {len(actions)}")
        # Load the keybinding_localization.xml file
        file_path_localization = self.keybindings_localization_file
        print_debug("loading keybinds localisations")
        tree_localization = ET.parse(file_path_localization)
        root_localization = tree_localization.getroot()

        # Creating a mapping of key names to their localization strings
        localization_map = {}
        for device in root_localization.findall(".//device"):
            for key in device.findall(".//Key"):
                key_name = key.get("name")
                localization_string = key.get("localizationString")
                localization_map[key_name] = localization_string

        # Updating the keybindings in the actions list with their localized strings
        for action_name in actions:
            actions[action_name]["keyboard-mapping-ui"] = self._localize_keybinding(localization_map, actions[action_name]["keyboard-mapping"])

        # Load English translations and update actions
        
        translations_en = self._load_translations(self.sc_translations_en)
        self._update_actions_with_translations(actions, translations_en, "en")

        # Load Player-Language translations and update actions
        translations_de = self._load_translations(self.sc_translations_player_language)
        self._update_actions_with_translations(actions, translations_de, self.player_language)

        return actions

    def load_custom_keybinds(self, actions):
        file_path_layout = self.user_keybinding_file
        print_debug("loading user keybinds")
        tree_layout = ET.parse(file_path_layout)
        root_layout = tree_layout.getroot()

        # Creating a mapping of action names to their new keybindings from the layout file
        layout_keybindings = {}
        for actionmap in root_layout.findall(".//actionmap"):
            for action in actionmap.findall(".//action"):
                action_name = action.get("name")
                rebind = action.find(".//rebind")
                if rebind is not None:
                    new_keybinding = self._remove_prefix(rebind.get("input"))
                    layout_keybindings[action_name] = new_keybinding

        # Updating the keybindings in the actions list with the new ones from the layout file
        for action_name in actions:
            if action_name in layout_keybindings:
                actions[action_name]["keyboard-mapping"] = layout_keybindings[action_name]# reset buffer

        return actions


if __name__ == "__main__":
    KeyService = SCKeybindings()
    KeyService.parse_and_create_files()
