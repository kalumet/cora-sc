import json
import os
import traceback
import datetime
from openai import AzureOpenAI

from services.printr import Printr
from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext

# Beispielhafter Prompt für Zusammenfassungen
SUMMARIZE_PROMPT = """
    Du bist ein Assistent, der Log-Einträge ultrakompakt zusammenfassen und in einer 
    Skeleton-Struktur speichern soll.
    Füge keine Erklärungen, Kommentare, oder Codeblöcke hinzu. 
    Gib nur reines JSON zurück.    
"""

DEBUG = True
printr = Printr()


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class AdvancedGenericLogManager(FunctionManager):
    """
    Ein erweiterter Log-Manager, der:
    1) Alle Logs dauerhaft in 'full_logs' speichert (Datei bleibt vollständig).
    2) Eine In-Memory-Liste 'recent_logs' mit bis zu 100 Einträgen hält (aktuelles Wissen).
    3) Zusammenfassungen in 'summaries' speichert, sobald Daten älter sind oder man Filter-Abfragen stellt.
    4) Standardmäßig bei 'list_logs' nur die letzten 100 Einträge (recent_logs) zurückgibt,
       es sei denn, man möchte explizit ältere / zusammengefasste Logs oder Filter.
    5) Grenzen checkt (max. 100 Einträge / 10.000 Zeichen in-memory).
       Wird dies überschritten, werden die ältesten Einträge in-memory zusammengefasst
       und als "MEMORY"-Log in 'summaries' abgelegt. Die Datei mit 'full_logs' bleibt unverändert.

    Datei-Struktur (Beispiel):
    {
      "full_logs": [...],
      "summaries": {
        "custom_summaries": [...],  # Manuell erstellte Zusammenfassungen via build_summary
        "memory_summaries": [...],  # Automatisch erstellte Zusammenfassungen (ältere in-memory Logs)
      }
    }
    """

    MAX_LOG_ENTRIES = 100          # maximal 100 Einträge in recent_logs
    MAX_LOG_CHARACTERS = 10000     # maximal 10.000 Zeichen als JSON in-memory

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        self.config = config
        
        # Pfad zur JSON-Datei, in der wir alles speichern
        self.log_file_path = config.get("AdvancedGenericLogManager", {}).get("log_file_path", "star_citizen_data/logs/log_memories.json")

        # OpenAI-API-Key aus SecretKeeper
        self.openai_api_key = self.secret_keeper.retrieve(
                requester=AdvancedGenericLogManager,
                key="azure_conversation",
                friendly_key_name="Azure Conversation API key",
                prompt_if_missing=True,
            )

        # Aktuelle Spielversion
        self.current_game_version = config.get("sc-keybind-mappings", {}).get("sc_channel_version", "UNSET_VERSION")

        # Datei laden oder neu anlegen
        self.full_logs = []  # Alle jemals erstellten Logs
        self.summaries = {
            "custom_summaries": [],   # vom Nutzer/dir erstellte Filter-Zusammenfassungen
            "memory_summaries": []    # automatisches Zusammenfassen bei Limit-Überschreitungen
        }
        if os.path.exists(self.log_file_path):
            self._load_from_file()

        # Die letzten 100 Einträge für aktives "Wissen"
        # => Holen wir aus full_logs (Ende), wenn vorhandene Logs < 100, dann eben alle.
        self.recent_logs = self.full_logs[-self.MAX_LOG_ENTRIES:]

    def get_context_mapping(self) -> AIContext:
        """
        Verortet diesen Manager im CORA-Kontext.
        """
        return AIContext.CORA

    def register_functions(self, function_register):
        """
        Hier registrieren wir die Funktionen,
        die Cora via ChatGPT-Funktion-Calling aufrufen kann.
        """
        function_register[self.add_log_entry.__name__] = self.add_log_entry
        function_register[self.get_logs_entries.__name__] = self.get_logs_entries
        function_register[self.build_log_entry_summary.__name__] = self.build_log_entry_summary

    def get_function_prompt(self):
        """
        Beschreibt, wie Cora diese Funktionen nutzen kann.
        """
        return (
            "Du kannst folgende Funktionen nutzen, um Logs zu verwalten:\n"
            f"- '{self.add_log_entry.__name__}': Rufe diese funktion auf, wenn ein neuer Log-Eintrag erstellt werden soll. \n"
            "                Du kannst den Typ des Eintrags, Notizen und strukturierte Daten angeben.\n"
            "                Wenn der Text auch sinnvolle strukturierbare Daten beinhaltet, erstelle ein JSON Datenobjekt daraus, welches Du an das Log anhängst. \n"
            "                Nutze die Informationen aus dem aktuellen Kontext, um die Daten sinnvoll zu erweitern.\n"
            "                Beispiel: {'location': 'Daymar', 'amount': 1000, 'commodity': 'Gold'}\n"
            f"- '{self.get_logs_entries.__name__}': Gibt Log-Einträge zurück, standardmäßig die letzten 100.\n"
            "                Mit Filtern (z.B. log_type, version, older_than) können gezielt Einträge abgefragt werden.\n"
            f"- '{self.build_log_entry_summary.__name__}': Erzeugt eine Zusammenfassung aus dem Log-Buch zu bestimmten Filter-Kriterien (z.B. alle Mining-Logs).\n"
        )

    def get_function_tools(self):
        """
        OpenAI-Function-Signaturen für die oben genannten Methoden.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": self.add_log_entry.__name__,
                    "description": "Speichert einen neuen Log-Eintrag (mit automatisch gesetztem Zeitstempel). ",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "log_type": {
                                "type": "string",
                                "description": f"Art des Eintrags. Nutze einen vorhandenen ({self._get_log_types()} oder erstelle selbst einen passenden z.B. 'SALVAGE', 'NOTE', 'MINING', 'COMBAT', ...). ."
                            },
                            "notes": {
                                "type": "string",
                                "description": "Beschreibung oder Notizen zum Eintrag."
                            },
                            "structured_data": {
                                "type": "object",
                                "description": "Aus dem log eintrag strukturierte Daten. Optional. Beispiel: {'location': 'Daymar', 'amount': 1000, 'commodity': 'Gold'}"
                            }
                        },
                        "required": ["log_type", "notes"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": self.get_logs_entries.__name__,
                    "description": (
                        "Gibt Log-Einträge zurück. Standardmäßig nur die letzten 100 (in-memory). "
                        "Über Filter kann man ältere Einträge anfragen (dann ggf. als Zusammenfassung)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "log_type": {
                                "type": "string",
                                "description": f"Filter nach Log-Type ({self._get_log_types()}). Optional."
                            },
                            "game_version": {
                                "type": "string",
                                "description": "Filter nach Spielversion (z.B. '3.20.1'). Optional."
                            },
                            "older_than": {
                                "type": "string",
                                "description": "Datum-String (YYYY-MM-DD HH:MM:SS). "
                                               "Alle Einträge, die älter sind als dieses Datum. Optional."
                            },
                            "fetch_full": {
                                "type": "boolean",
                                "description": "Wenn True, werden ALLE Logs berücksichtigt. Nutze dies nur in Kombination mit einem Filter."
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": self.build_log_entry_summary.__name__,
                    "description": (
                        "Erzeugt eine Zusammenfassung bestimmter Logs. "
                        "Wird in 'summaries.custom_summaries' gespeichert."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "log_type": {
                                "type": "string",
                                "description": f"Filter nach Log-Type ({self._get_log_types()})."
                            },
                            "game_version": {
                                "type": "string",
                                "description": "Filter nach Spielversion, z.B. '3.20.1'."
                            },
                            "older_than": {
                                "type": "string",
                                "description": "Datum-String (YYYY-MM-DD HH:MM:SS). Optional."
                            }
                        }
                    }
                }
            }
        ]

    # ----------------------------------------------------------------
    # Öffentliche Funktionen, die via ChatGPT-Funktionen aufgerufen werden können
    # ----------------------------------------------------------------

    def add_log_entry(self, args):
        """
        Speichert einen neuen Log-Eintrag, automatisch mit Zeitstempel.
        """
        printr.print(f"Executing function '{self.add_log_entry.__name__}'.", tags="info")

        log_type = args.get("log_type")
        notes = args.get("notes")
        structured_data = args.get("structured_data", {})

        timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_entry = {
            "timestamp": timestamp_str,
            "game_version": self.current_game_version,
            "type": log_type,
            "notes": notes,
            "data": structured_data
        }

        # In vollem Log speichern (Datei bleibt immer intakt)
        self.full_logs.append(new_entry)

        # Auch in der in-memory-Liste (aktuelles Wissen)
        self.recent_logs.append(new_entry)

        # Check, ob wir die 100 Einträge in-memory überschreiten
        if len(self.recent_logs) > self.MAX_LOG_ENTRIES or self._char_count_exceeds_limit():
            self._consolidate_memory_logs()

        # Persistieren (full_logs + summaries) in Datei
        self._persist_to_file()

        printr.print(f"Stored\n {json.dumps(new_entry, indent=2)}", tags="info")

        return {
            "success": True,
            "message": f"Neuer Log-Eintrag '{log_type}' gespeichert.",
            "total_in_memory": len(self.recent_logs),
            "additional_instructions": "Bestätige nur, dass der Log-Eintrag gespeichert wurde."
        }

    def get_logs_entries(self, args):
        """
        Gibt Logs zurück. Standardmäßig nur die letzten 100 (recent_logs).
        Kann Filter enthalten:
            - log_type
            - game_version
            - older_than (Datum)
        Wenn fetch_full=True, liefert alle Logs (full_logs) – kann sehr groß sein.
        Ansonsten, wenn Logs älter als was in memory ist, kann es sein,
        dass wir nur Summaries zurückgeben.
        """
        printr.print(f"Executing function '{self.get_logs_entries.__name__}'.", tags="info")
        log_type = args.get("log_type", None)
        game_version = args.get("game_version", self.current_game_version)
        older_than_str = args.get("older_than", None)
        fetch_full = args.get("fetch_full", False)

        # Versuche Datum zu parsen
        older_than_dt = None
        if older_than_str:
            try:
                older_than_dt = datetime.datetime.strptime(older_than_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass  # Falls Parsing fehlschlägt, ignorieren wir es

        if not fetch_full:
            # Wir geben nur recent_logs oder gefilterte Ausschnitte davon zurück
            filtered = self._filter_logs(self.recent_logs, log_type, game_version, older_than_dt)
            return {
                "success": True,
                "logs_returned": len(filtered),
                "logs": filtered,
                "message": (
                    "Fasse die Logs narrativ und ohne formatierung zusammen, dass sie gut für eine TTS-Engine ausgesprochen werden können, "
                    " damit der Spieler einen Überblick bekommt ohne zu sehr ins Detail zu gehen. "
                    "Achte auf die Ansprache, da Du die Informationen dem Spieler präsentierst. "
                    "Kristallisiere die wichtigsten Eckdaten zusammen. Gehe nicht zu sehr in die zeitlichen Details, insbesondere gebe keine Jahreszahlen an. "
                    "Frage nach, ob er mehr Details benötigt. "
                )
            }
        else:
            # fetch_full => sehr große Menge an Logs!
            # Wir holen ALLE aus full_logs (und filtern optional)
            filtered = self._filter_logs(self.full_logs, log_type, game_version, older_than_dt)
            return {
                "success": True,
                "logs_returned": len(filtered),
                "logs": filtered,
                "message": (
                    "Du hast ALLE logs angefordert. "
                    "Hinweis: Ältere In-Memory-Logs wurden zu MEMORY-Einträgen zusammengefasst. "
                    "Formuliere diese aus, ohne neue Details zu erfinden. "
                )
            }

    def build_log_entry_summary(self, args):
        """
        Erstellt eine Zusammenfassung (z.B. aller MINING-Logs) und speichert sie in
        'summaries.custom_summaries'.
        Filter: log_type, game_version, older_than
        """
        printr.print(f"Executing function '{self.build_log_entry_summary.__name__}'.", tags="info")
        log_type = args.get("log_type", None)
        game_version = args.get("game_version", self.current_game_version)
        older_than_str = args.get("older_than", None)

        older_than_dt = None
        if older_than_str:
            try:
                older_than_dt = datetime.datetime.strptime(older_than_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass

        # Filter aus full_logs
        relevant_logs = self._filter_logs(self.full_logs, log_type, game_version, older_than_dt)
        if not relevant_logs:
            return {
                "success": True,
                "summary": "",
                "message": "Keine passenden Logs zum Zusammenfassen gefunden."
            }

        # per OpenAI zusammenfassen
        try:
            summary_text = self._openai_summarize_logs(relevant_logs)
        except Exception as e:
            summary_text = f"(Fehler bei Zusammenfassung: {e})"
            print_debug(f"Error in Zusammenfassung: {e}")
            print_debug(traceback.format_exc())

        # Zusammenfassung in custom_summaries ablegen
        summary_entry = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "filter": {
                "log_type": log_type,
                "game_version": game_version,
                "older_than": older_than_str
            },
            "summary_text": summary_text
        }
        self.summaries["custom_summaries"].append(summary_entry)
        self._persist_to_file()

        printr.print(f"Summary:\n{json.dumps(summary_text, indent=2)}", tags="info")
        return {
            "success": True,
            "summary": summary_text,
            "message": "Zusammenfassung gespeichert",
            "additional_instructions": (
                "Fasse die Zusammenfassung narrativ zusammen, dass sie gut für eine TTS-Engine ausgesprochen werden können, "
                "damit der Spieler einen Überblick bekommt ohne zu sehr ins Detail zu gehen. "
                "Achte auf die Ansprache, da Du die Informationen dem Spieler präsentierst. "
                "Gebe keine Jahreszahlen an. "
            )
        }

    # ----------------------------------------------------------------
    # Interne Hilfsfunktionen
    # ----------------------------------------------------------------

    def _get_log_types(self):
        """
        Gibt eine Liste von einzigartigen Log-Typen zurück.
        """
        return list(set([log.get("type") for log in self.full_logs]))
    
    def _filter_logs(self, logs_list, log_type, game_version, older_than_dt):
        """
        Hilfsfunktion, um die übergebene Liste von Logs nach log_type,
        game_version und older_than_dt zu filtern.
        """
        result = []
        for log_item in logs_list:
            if log_type and log_item.get("type") != log_type:
                continue
            if game_version and log_item.get("game_version") != game_version:
                continue
            if older_than_dt:
                # timestamp aus log parsen
                try:
                    log_dt = datetime.datetime.strptime(log_item["timestamp"], "%Y-%m-%d %H:%M:%S")
                    if not (log_dt < older_than_dt):
                        continue
                except ValueError:
                    # Falls Timestamp kaputt ist, skippen
                    continue
            # Falls alle Filter durch sind, Log aufnehmen
            result.append(log_item)
        return result

    def _char_count_exceeds_limit(self):
        """
        Prüft, ob die JSON-Repräsentation von recent_logs die MAX_LOG_CHARACTERS übersteigt.
        """
        as_json = json.dumps(self.recent_logs, ensure_ascii=False)
        return len(as_json) > self.MAX_LOG_CHARACTERS

    def _consolidate_memory_logs(self):
        """
        Wird aufgerufen, wenn wir mehr als 100 In-Memory-Logs oder
        >10.000 Zeichen haben. Wir fassen einen Teil (typischerweise ~50%)
        der älteren Einträge in memory zusammen zu einem 'MEMORY'-Eintrag.
        Der Speicher wird also verkleinert.
        ABER: in 'full_logs' bleiben ALLE Einträge unverändert.
        """
        # Nehmen wir die ältesten 50% von recent_logs, fassen sie zusammen.
        cutoff = len(self.recent_logs) // 2
        logs_to_summarize = self.recent_logs[:cutoff]
        try:
            summary_text = self._openai_summarize_logs(logs_to_summarize)
        except Exception as e:
            summary_text = f"(Fehler bei Zusammenfassung in _consolidate_memory_logs: {e})"

        # Erzeuge einen MEMORY-Eintrag und hänge ihn in 'recent_logs'
        memory_log = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "game_version": self.current_game_version,
            "type": "MEMORY",
            "notes": summary_text,
            "data": {}
        }

        # Die 'memory_summaries' in self.summaries (Datei) erweitern
        self.summaries["memory_summaries"].append({
            "timestamp": memory_log["timestamp"],
            "summary_text": summary_text,
            "count_merged": len(logs_to_summarize)
        })

        # Nun entfernen wir die zusammengefassten Einträge aus recent_logs
        self.recent_logs = self.recent_logs[cutoff:]
        self.recent_logs.insert(0, memory_log)  # Den Zusammenfassungs-Eintrag an den Anfang setzen

    def _openai_summarize_logs(self, log_entries):
        """
        Ruft OpenAI auf, um die übergebenen Log-Einträge (log_entries) zu einem knappen
        Text zu komprimieren.
        """
        logs_json = json.dumps(log_entries, ensure_ascii=False)
        
        # TODO get from config
        api_base_url = "https://cora-ai.openai.azure.com/"
        api_version = "2024-08-01-preview"
        deployment_name = "gpt-4o"
        conversation_model = "gpt-4o"
        
        client = AzureOpenAI(
                api_key=self.openai_api_key,
                azure_endpoint=api_base_url,
                api_version=api_version,
                azure_deployment=deployment_name,
            )

        completion = client.chat.completions.create(
            model=conversation_model,
            messages=[
                {
                    "role": "system",
                    "content": SUMMARIZE_PROMPT
                },
                {
                    "role": "user",
                    "content": (
                        """
                        Hier sind mehrere Log-Einträge im JSON-Format. Bitte erstelle daraus ein Skeleton in folgender JSON Struktur:

                        {
                        "summary_title": "Kurzer Titel oder Thema der Logs",
                        "entries": [
                            {
                            "date": "YYYY-MM-DD HH:MM",
                            "type": "z.B. MINING, TRAVEL, COMBAT",
                            "key_points": [
                                "Stichwort A",
                                "Stichwort B",
                                ...
                            ]
                            },
                            ...
                        ]
                        }
                        Nenne nur die wichtigsten Infos.
                        Wandle Fließtext in Stichpunkte um.
                        Keine Listen oder Unterpunkte außerhalb von key_points.
                        Fass dich so kurz wie möglich.
                        Nenne unbedingt das Datum (oder Timestamp) und den Typ (type).
                        Erfinde nichts Neues, sondern übernimm reale Fakten aus den Logs.
                        Gib als Ergebnis nur das JSON-Skeleton zurück, 
                        Füge keine Erklärungen, Kommentare, oder Codeblöcke hinzu. 
                        Gib nur reines JSON zurück.
                        """
                        f"Hier sind die Log-Einträge:\n{logs_json}")
                }
            ],
            max_tokens=512,
            temperature=0.7,
        )
        print_debug(f"OpenAI completion: {completion}")

        raw_answer = completion.choices[0].message.content.strip()

        # Falls das Modell Backticks für Codeblöcke verwendet:
        if raw_answer.startswith("```json"):
            # Entferne leading ``` (ggf. mit oder ohne "json") 
            raw_answer = raw_answer.split("```json", 1)[-1]
        if raw_answer.endswith("```"):
            raw_answer = raw_answer.rsplit("```", 1)[0]

        return json.loads(raw_answer)

    def _load_from_file(self):
        """
        Lädt 'full_logs' und 'summaries' aus der JSON-Datei, falls vorhanden.
        """
        try:
            with open(self.log_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.full_logs = data.get("full_logs", [])
                self.summaries = data.get("summaries", {
                    "custom_summaries": [],
                    "memory_summaries": []
                })
        except Exception as e:
            print(f"[WARN] Datei '{self.log_file_path}' konnte nicht geladen werden: {e}")

    def _persist_to_file(self):
        """
        Schreibt full_logs und summaries in die Datei.
        """
        # Verzeichnis extrahieren und ggf. anlegen
        directory = os.path.dirname(self.log_file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

        data = {
            "full_logs": self.full_logs,
            "summaries": self.summaries
        }
        try:
            with open(self.log_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARN] Konnte Datei '{self.log_file_path}' nicht speichern: {e}")
