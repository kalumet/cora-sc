import xml.etree.ElementTree as ET
import csv
import json
import re


DEBUG = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class SCKeybindings():

    def __init__(self, config: dict[str, any]):
        self.config = config
        
        self.data_root_path = f'{self.config["data-root-directory"]}{self.config["sc-keybind-mappings"]["keybindings-directory"]}'
        self.json_path = f"{self.data_root_path}/keybindings_existing.json"
        self.json_path_miss = f"{self.data_root_path}/keybindings_missing.json"
        self.json_path_knowledge = f"{self.data_root_path}/keybindings_existing_knowledge.json"
        self.json_path_miss_knowledge = f"{self.data_root_path}/keybindings_missing_knowledge.json"
        self.keybindings: dict = None # will be filled on first access
        self.sc_installation_dir = self.config["sc-keybind-mappings"]["sc_installation_dir"]
        self.user_keybinding_file_name = self.config["sc-keybind-mappings"]["user_keybinding_file_name"]
        self.sc_active_channel = self.config["sc-keybind-mappings"]["sc_active_channel"]
        self.sc_channel_version = self.config["sc-keybind-mappings"]["sc_channel_version"]
        self.en_translation_file = self.config["sc-keybind-mappings"]["en_translation_file"]
        user_keybinding_file_config = f"{self.sc_installation_dir}/{self.sc_active_channel}/USER/Client/0/Controls/Mappings/{self.user_keybinding_file_name}"
        self.user_keybinding_file = user_keybinding_file_config.format(sc_channel_version=self.sc_channel_version)
        self.default_keybinds_file = f'{self.data_root_path}/{self.sc_channel_version}/{self.config["sc-keybind-mappings"]["sc_unp4k_file_default_keybindings_filter"]}'
        self.keybindings_localization_file = f'{self.data_root_path}/{self.sc_channel_version}/{self.config["sc-keybind-mappings"]["sc_unp4k_file_keybinding_localization_filter"]}'
        self.sc_translations_en = f"{self.data_root_path}/{self.sc_channel_version}/{self.en_translation_file}"
        self.player_language = self.config["sc-keybind-mappings"]["player_language"]
        self.sc_translations_player_language = f"{self.data_root_path}/{self.sc_channel_version}/global_{self.player_language}.ini"
        self.keybind_categories_to_ignore = set(self.config["keybind_categories_to_ignore"])
        self.keybind_actions_to_include_from_category = set(self.config["include_actions"]) 

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
                
        return filtered
    
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

    def _filter_actions(self, actions, onlyMissing):
        """Filters the actions according to param onlyMissing
        
            onlyMissing = True -> returns only actions with no keyboard keybinds available
            onlyMissing = False -> returns only actions that have a keybind
        """
        return (details for details in actions.values() if self._include_action(details, onlyMissing))

    def _include_action(self, action_details, onlyMissing):
        keybinding = action_details.get("keyboard-mapping", "")
        # Prüfe auf leere oder None-Werte
        keybinding_exists = bool(keybinding and keybinding.strip())
        return (onlyMissing and not keybinding_exists) or (not onlyMissing and keybinding_exists)

    def _write_csv(self, path, actions, onlyMissing):
        headers = [
            "actionname",
            "activationMode",
            "keyboard-mapping",
            "action-label-en",
            f"action-label-{self.player_language}",
            "action-description-en",
            f"action-description-{self.player_language}",
            "keyboard-mapping-en",
            f"keyboard-mapping-{self.player_language}",
            # "keyboard-mapping-ui",
            # "label-ui",
            # "description-ui",
        ]

        with open(path, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, delimiter=";", quotechar='"', quoting=csv.QUOTE_ALL)
            writer.writerow(headers)
            for action_details in self._filter_actions(actions, onlyMissing):
                writer.writerow([action_details.get(header, "") for header in headers])

    def _should_include_action(self, action_details, onlyMissing):
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



        if onlyMissing:
            return not keybinding_exists or not_supported_activation_mode or excludedCategory  # True, wenn keybinding leer ist
        
        return keybinding_exists and not not_supported_activation_mode and not excludedCategory  # True, wenn keybinding einen Wert hat

    def _create_json_data(self, actions, only_missing, content_keys, mode):
        json_data = {}
        for action_name, action_details in actions.items():
            if not self._should_include_action(action_details, only_missing):
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

            json_key = ''.join([char if char.isalnum() else '_' for char in key_value])
            json_key = re.sub(r'_+', '_', json_key)
            # Entfernt einen Unterstrich am Ende, falls vorhanden
            if json_key.endswith('_'):
                json_key = json_key[:-1]

            if not json_key:
                continue  # Leer oder keine gültigen Zeichen, Eintrag überspringen

            json_data[json_key] = json_entry

        return json_data

    def _write_json(self, actions, path, only_missing):
        content_keys = [
            "category",
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
        json_data = self._create_json_data(actions, only_missing, content_keys, "actionname")

        with open(path, mode="w", encoding="utf-8") as file:
            json.dump(json_data, file, indent=4, ensure_ascii=False)

        return path

    def _write_openai_knowledge_json(self, actions, path, only_missing):
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
        ]
        json_data = self._create_json_data(actions, only_missing, content_keys, "functionname")

        with open(path, mode="w", encoding="utf-8") as file:
            json.dump(json_data, file, indent=4, ensure_ascii=False)

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
        # Load the XML file
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

        # for duplicate in duplicates:
        #     print_debug(f"Duplikat: {duplicate}")

        # Next, I will parse the layout_kalumet_3_19_exported.xml file to update the keybindings in the actions list.
        # The structure of this file is different, so I'll adapt my parsing accordingly.

        # Load the layout_kalumet_3_19_exported.xml file
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
                actions[action_name]["keyboard-mapping"] = layout_keybindings[action_name]

        # Now, I will parse the keybinding_localization.xml file to map the keybindings to their UI variable names.
        # This is needed to replace the keybindings in our actions list with their respective localization strings.

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

        # Load German translations and update actions
        translations_de = self._load_translations(self.sc_translations_player_language)
        self._update_actions_with_translations(actions, translations_de, self.player_language)

        # Creating the CSV file
        # csv_file_path_miss = "data/keybindings/keybindings_missing.csv"
        # csv_file_path = "data/keybindings/keybindings_existing.csv"

        # writeCSV(csv_file_path_miss, actions, onlyMissing=True)
        # writeCSV(csv_file_path, actions, onlyMissing=False)
        self._write_json(actions, self.json_path_miss, only_missing=True)
        self._write_json(actions, self.json_path, only_missing=False)
        self._write_openai_knowledge_json(actions, self.json_path_miss_knowledge, only_missing=True)
        self._write_openai_knowledge_json(actions, self.json_path_knowledge, only_missing=False)
        self.keybindings = None # reset buffer


if __name__ == "__main__":
    KeyService = SCKeybindings()
    KeyService.parse_and_create_files()
