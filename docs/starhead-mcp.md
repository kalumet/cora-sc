# StarHead-MCP ausprobieren

Die Anbindung verwendet das offizielle Python-SDK `mcp` (Version 2.2.0).
Der erste freigegebene Aufruf ist `sc_mining`, ausschließlich über den
aktivierten MiningManager im CORA-Kontext. Lokale Signaturerkennung und
Raffinerieaufträge bleiben erhalten.

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

## Betrieb und Fehler

- Discovery erfolgt beim Aktivieren des Managers. Bei Nichterreichbarkeit bleiben
  die lokalen Funktionen verfügbar; Manager aus- und einschalten wiederholt Discovery.
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

Die neuen Tests verwenden das offizielle SDK gegen einen MCP-Testserver im selben
Prozess, ohne StarHead-Netzwerkzugriff und ohne Desktop-/Audio-Abhängigkeiten:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_manager_mcp.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_instant_command_cache.py
```

Sie prüfen Freigaben, Kontextwechsel, gemeinsame Tool-Zuordnungen, den tatsächlichen
Wingman-Dispatcher, Cache-Ausschluss, Discovery, Schemaübernahme und Fehlerbehandlung.
Der HTTP-Transport selbst wird vom offiziellen SDK bereitgestellt.
