# StarStrings beim Cora-Start

`StarStringsManager` ist standardmäßig aktiv. Beim Start der Star-Citizen-Wingman-
Instanz prüft er im Hintergrund das jüngste veröffentlichte Release von
[MrKraken/StarStrings](https://github.com/MrKraken/StarStrings). Die Prüfung verwendet
die öffentliche GitHub-API; ein GitHub-Token oder KI-Aufruf ist nicht erforderlich.
Ein fehlendes Paket wird installiert, eine neue Release-Datei ersetzt das vorhandene.
Bei unverändertem Release wird nur die Metadatenprüfung ausgeführt; das ZIP wird
nicht erneut heruntergeladen. Eine fehlende `global.ini` wird erneut installiert.
Während Cora läuft, erfolgt keine periodische Release-Abfrage. Erneute Aktivierung
des Managers startet ebenfalls eine Prüfung.

Das Projekt bietet ein englisches LIVE-Paket. Die Installation folgt seiner
[Anleitung](https://github.com/MrKraken/StarStrings#installation):

```text
<sc_installation_dir>/LIVE/
├── user.cfg                         # g_language = english
└── data/Localization/english/global.ini
```

Das Ziel folgt `sc-keybind-mappings.sc_installation_dir` und `sc_active_channel`.
Für einen anderen aktiven Kanal als LIVE oder ein fehlendes Installationsverzeichnis
wird die Installation übersprungen. Vorhandene Groß-/Kleinschreibung von `Data`,
`USER.cfg` usw. wird beibehalten. Die Sprache im Spiel wird Englisch; Coras
Gesprächssprache wird nicht geändert. Das Spiel muss nach einer Installation oder
Aktualisierung neu gestartet werden, damit es die Sprachdatei neu lädt.

## Einstellungen

```yaml
features:
  StarStringsManager:
    enabled: true
    timeout_seconds: 15
```

Diese Einstellungen gehören zur Star-Citizen-Wingman-Konfiguration. Ohne Eintrag
gilt `enabled: true`. `timeout_seconds` begrenzt den Socket-Timeout je HTTP-Anfrage
und liegt zwischen 1 und 30 Sekunden. Die Prüfung läuft in einem Hintergrundthread;
ein Offline-Start verhindert Coras Start nicht. Im bestehenden Feature-Manager
kann StarStringsManager aktiviert oder deaktiviert werden.

## Release-Erkennung und Erhalt vorhandener Dateien

StarStrings verwendet einen dauerhaften Tag `latest`. Deshalb vergleicht Cora
Release-ID, Name und Veröffentlichungszeit sowie Asset-ID, Änderungszeit, Größe
und SHA-256-Digest. Auch ein erneut hochgeladenes Paket unter demselben Tag wird
dadurch als Update erkannt.

Aus dem ZIP wird ausschließlich `Data/Localization/english/global.ini` gelesen.
Die mitgelieferte `USER.cfg` ersetzt keine bestehende Konfiguration. Cora ergänzt
oder aktualisiert ausschließlich deren aktive `g_language`-Einträge; andere
Einstellungen, Kommentare, Zeilenenden und die unterstützte Dateikodierung bleiben
erhalten. Auch ein unveränderter Release prüft diesen benötigten Spracheintrag.

Vor dem Ersetzen werden bestehende Dateien gesichert:

```text
<data-root-directory>/starstrings/
├── installed_LIVE.json
└── backups/LIVE/
    ├── user.cfg.<sha256>.bak
    └── global.ini.<sha256>.bak
```

Die Sicherungen werden anhand ihres Inhalts benannt und nicht überschrieben.
Ein vorhandenes eigenes Sprachpaket wird vor der ersten StarStrings-Installation
ebenfalls gesichert. Für eine manuelle Wiederherstellung zuerst den Manager
deaktivieren und die gewünschte Sicherung auf den ursprünglichen Dateipfad kopieren.

Das ZIP wird vor Änderungen auf vollständigen Download, veröffentlichten SHA-256-
Digest (falls vorhanden), Archivstruktur und gültige Sprachdaten geprüft. Die Dateien
werden atomar ersetzt; bei einem Fehler beim Schreiben weiterer Installationsdateien
werden bereits ersetzte Dateien zurückgesetzt. Der Release-Marker wird zuletzt
geschrieben. Netzwerk- und Validierungsfehler erhalten das bisherige Paket und
werden in der Konsole angezeigt.

## Prüfung

`tests/test_star_citizen_starstrings.py` prüft unter anderem die erste Installation,
Neustarts, Änderungen unter dem Tag `latest`, Offline-Starts, bestehende Konfigurationen,
Backups, Schreibfehler mit Rollback, Abbruch und den Manager-Lebenszyklus.

Das echte Release-ZIP vom 09.10.2026 wurde zusätzlich in einem temporären LIVE-
Verzeichnis installiert. Die bestehende `user.cfg` wurde dafür als Eingabe kopiert;
alle ursprünglichen Einstellungen blieben erhalten. Die Sprachdatei hatte
10.715.737 Bytes. Eine zweite Startup-Prüfung erkannte das Paket als aktuell und
lud das ZIP nicht erneut. Das tatsächliche Spieleverzeichnis wurde bei diesem Test
nicht geändert. Die Ergebnisse liegen in
`debug_data/decisions/starstrings-install-smoke-2026-10-12.json`.
