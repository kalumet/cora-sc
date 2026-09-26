# StarHead-MCP ausprobieren

Die Anbindung verwendet das offizielle Python-SDK `mcp` (Version 2.2.0).
Der MiningManager ergänzt seine lokale Signaturerkennung und Raffinerieaufträge
um `sc_mining`. Der ComponentManager verwendet ausschließlich MCP. Beide Manager
geben ihre zugeordneten Tools nur im aktivierten Zustand im CORA-Kontext frei.

## Installation und Konfiguration

In der Python-Umgebung der Anwendung die aktualisierten Abhängigkeiten installieren:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Unter `wingmen.star-citizen-ai` in der verwendeten Datei
`configs/configs/config.yaml` ergänzen (gleiche Einrückungsebene wie `features`):

```yaml
mcp:
  servers:
    starhead:
      enabled: true
      url: https://wingman-ai-mcp-servers.wingman-ai.workers.dev/starhead/mcp
      timeout_seconds: 30
  manager_tools:
    MiningManager:
      starhead:
        - sc_mining
    ComponentManager:
      starhead:
        - sc_component_info
        - sc_find_components
        - sc_where_to_buy
        - sc_ship_loadout
        - sc_loadout_calc
```

Die Beispielkonfiguration enthält diesen Abschnitt bereits. Bestehende persönliche
Konfigurationen werden beim Start nicht automatisch mit dem Beispiel zusammengeführt.
Die Codex-MCP-Konfiguration wird von der Anwendung nicht eingelesen.

Wingman neu starten und den MiningManager über die vorhandene Manager-Steuerung
aktivieren, oder in seiner bestehenden Feature-Konfiguration `enabled: true` setzen.
Die vorhandenen `signature_observer`-Einstellungen bleiben dabei erhalten.
MCP aktiviert den MiningManager und dessen HUD-Beobachtung nicht selbstständig.

Beispielfragen:

- „Was kann ich auf Daymar mit einem ROC abbauen?“ → `starhead_sc_mining`
- „Wo finde ich Quantanium?“ → `starhead_sc_mining`
- „Welche Ressource passt zu Signatur 10800?“ → lokale Signatursuche
- „Zeige meine Raffinerieaufträge.“ → lokale Auftragsverwaltung

## ComponentManager

Nach dem Neustart „Aktiviere Komponenten Manager“ sagen oder unter `features`
`ComponentManager: true` setzen. `ComponentManager: false` lässt ihn deaktiviert;
die MCP-Zuordnung aktiviert ihn nicht automatisch. „Deaktiviere Komponenten Manager“
sperrt seine Tools wieder, sofern kein anderer aktiver Manager sie ebenfalls freigibt.

Der Manager enthält nur Kontext, Fähigkeiten und Hinweise zur Sprachausgabe.
Komponentensuche, Leistungswerte, Kaufmöglichkeiten und Loadout-Vergleiche werden
zentral über die oben aufgeführten fünf MCP-Tools abgewickelt. Beispiele:

- „Welche Werte hat der FR-76?“ → `starhead_sc_component_info`
- „Welche S2-Schilde haben die meisten Schildpunkte?“ → `starhead_sc_find_components`
- „Wo kann ich einen FR-76 kaufen?“ → `starhead_sc_where_to_buy`
- „Welche Waffen hat eine Gladius ab Werk?“ → `starhead_sc_ship_loadout`
- „Wie verändert sich eine Gladius mit drei Attrition-3?“ → `starhead_sc_loadout_calc`

Die bisherige Funktion `search_ship_component` und der Wiki-API-Zugriff entfallen.
Veraltete Instant-Command-Cache-Einträge dieser Funktion werden bei Verwendung
verworfen und die Anfrage wird neu verarbeitet; die Argumente werden nicht übersetzt.
Ohne konfigurierte, erreichbare MCP-Tools ist keine Komponentenabfrage verfügbar.
CORA soll fehlende Verfügbarkeit oder Daten erklären; es gibt keinen lokalen Fallback.

## Freigaben und Tool-Namen

Beschreibungen und Parameterschemas kommen über `list_tools()` vom Server.
Die KI sieht `<server>_<original-toolname>`, hier `starhead_sc_mining`.
Beim Aufruf wird daraus wieder `sc_mining` für den Server. Im MiningManager
ist kein eigener MCP-Aufruf und keine nachgebaute MCP-Tooldefinition notwendig.

Die YAML-Zuordnung ist eine Freigabeliste: Nicht aufgeführte Tools werden nicht
angeboten. Wildcards sind nicht unterstützt. Ein Tool kann mehreren Managern
zugeordnet werden und erscheint trotzdem nur einmal pro Kontext. Es ist verfügbar,
wenn mindestens einer der zugeordneten Manager aktiv ist und zum Kontext passt.
Ungültige, mehrdeutige oder mit lokalen Funktionen kollidierende Namen bleiben gesperrt.

Die Prüfung erfolgt sowohl beim Zusammenstellen der Toolliste als auch vor dem
Remote-Aufruf. Eine alte Gesprächshistorie oder ein Instant-Command-Cache-Eintrag
kann die Prüfung nicht umgehen. MCP-Tools werden nicht in der Registry lokaler
Python-Funktionen registriert und sind damit für den Instant-Command-Cache ungültig.
Ergebnisse tragen zusätzlich `do_not_cache: true`.

Zusätzliche Tools lassen sich später durch weitere Einträge in der Freigabeliste
zuordnen. Änderungen an der YAML-Konfiguration erfordern Neuladen/Neustart.
Ein deaktivierter Server (`enabled: false`) führt keine Discovery oder Aufrufe aus.

## Toollisten und YAML-Referenz

Alle explizit konfigurierten HTTP-MCP-Server in der globalen Konfiguration und
unter allen Wingmen abfragen:

```powershell
.\.venv\Scripts\python.exe scripts/list_mcp_tools.py
```

Auch deaktivierte Server werden fuer diese reine Discovery abgefragt; sie werden
nicht aktiviert und ihre Tools nicht ausgefuehrt. `--enabled-only` ueberspringt sie.
Einzelne Serverfehler werden gemeldet, die anderen Server trotzdem abgefragt.
Bei Fehlern ist der Exit-Code 1, sonst 0.

Optionen:

```powershell
# Vollstaendige Beschreibungen und Parameterschemas
.\.venv\Scripts\python.exe scripts/list_mcp_tools.py --details

# Andere Konfiguration oder nur ein bestimmter Wingman
.\.venv\Scripts\python.exe scripts/list_mcp_tools.py --config configs/configs/config.yaml --wingman star-citizen-ai
```

Die Ausgabe enthaelt je Server ein YAML-Dokument mit der Liste seiner Originalnamen.
Diese Liste kann unter `mcp.manager_tools.<Managername>` eingefuegt werden.
Die Abfrage aendert keine Freigaben. Fuer eine Freigabe nur die gewuenschten Namen
uebernehmen.

StarHead-Referenz (abgefragt am 26.09.2026, nicht automatisch freigegeben):

```yaml
starhead:
  - sc_search            # Namen suchen
  - sc_ship_info         # Schiffsdaten
  - sc_ship_loadout      # Standardausruestung
  - sc_compare_ships     # Schiffe vergleichen
  - sc_find_ships        # Schiffe filtern und finden
  - sc_component_info    # Komponentendaten
  - sc_find_components   # Passende Komponenten finden
  - sc_loadout_calc      # Loadout berechnen
  - sc_trade_route       # Handelsrouten
  - sc_commodity_prices  # Rohstoffpreise und Verkaufsstellen
  - sc_where_to_buy      # Bezugsquellen fuer Schiffe/Ausruestung
  - sc_shop_inventory    # Shop-Sortimente
  - sc_find_commodities  # Handelswaren vergleichen
  - sc_mining            # Mining-Fundorte und Vorkommen
  - sc_crafting          # Bauplaene und Materialien
  - sc_fps_item_info     # FPS-Ausrüstung
  - sc_location_info     # Ortsinformationen
```

## Betrieb und Fehler

- Discovery erfolgt beim Aktivieren des Managers. Bei Nichterreichbarkeit bleiben
  vorhandene lokale Funktionen anderer Manager verfügbar. Der ComponentManager hat
  keinen lokalen Fallback; Manager aus- und einschalten wiederholt Discovery.
- Jede Operation öffnet und schließt ihren SDK-Client im selben Event-Loop.
  Das passt zu den separaten Event-Loops der Audioverarbeitung in `main.py`.
- Das Timeout umfasst Verbindungsaufbau und Abfrage. Fehler werden als Tool-Ergebnis
  zurückgegeben, sodass CORA sie erklären kann. Remote-Ausführungen werden nicht
  automatisch wiederholt.
- Übertragen werden die Tool-Argumente, keine automatisch angehängten Screenshots,
  lokalen Dateien oder vollständigen Gespräche. Serverantworten bleiben als `data`
  unter einer lokalen Ergebnisstruktur; sie ersetzen keine lokalen Freigaben.
- Metadaten-Logs unter `services.manager_mcp` enthalten Quelle, Tool, Kontext,
  Laufzeit und Erfolg. Die vorhandenen Wingman-Debuglogs können weiterhin die
  Funktionsargumente und Ergebnisse protokollieren.

Zum Abschalten genügt `mcp.servers.starhead.enabled: false` und ein Neustart.
Ein Branch-Wechsel setzt die ignorierte persönliche `config.yaml` und installierte
Python-Pakete nicht zurück.

## Tests

Die Tests verwenden das offizielle SDK gegen einen MCP-Testserver im selben
Prozess, ohne StarHead-Netzwerkzugriff:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_component_manager.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_manager_mcp.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_instant_command_cache.py
```

Sie prüfen Freigaben, Kontextwechsel, gemeinsame Tool-Zuordnungen, den tatsächlichen
Wingman-Dispatcher, Cache-Ausschluss, Discovery, Schemaübernahme und Fehlerbehandlung.
Der HTTP-Transport selbst wird vom offiziellen SDK bereitgestellt.
