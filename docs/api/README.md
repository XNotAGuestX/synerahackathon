# Frontend-Vertrag und Beispiele

Die autoritativen Dateien liegen im Repository-Root:
[openapi.yaml](../../openapi.yaml) definiert die Wire-Form,
[DESIGN.md](../../DESIGN.md) die Semantik. Die laufende API liefert denselben
Vertrag unter `/openapi.json`; `/docs` zeigt die interaktive Dokumentation.

```bash
uv sync
uv run python -m final_agent.api
```

Web-UI dazu (zweites Terminal): `cd frontend && npm ci && npm run dev`, dann
`http://localhost:5173` öffnen. Vite leitet `/api` an Port 8000 weiter. Bei einem
Verbindungsfehler zeigt die UI „Reconnect“; Beispieldaten sind ausdrücklich über
„More → Open example demo“ (`?demo=1`) wählbar. `VITE_DATA_MODE=fixture` aktiviert
denselben eingeschränkten Demomodus. Nach diesem Update beide Server neu starten.

Die Standardadresse ist `http://127.0.0.1:8000/api/v1`. Sitzungen leben im Speicher;
deshalb läuft der Server mit einem Worker. Ein Browser-Reload kann eine Sitzung
über ihre gespeicherte UUID wieder laden. Ein Server-Neustart beendet sie.

Gebäudeliste, Suche, Pläne, direkte Routen und Aktionen benötigen keine
Anthropic-Zugangsdaten. Nur `POST .../messages` nutzt den konfigurierten Agenten.
Für `.env`-Dateien explizit `uv run --env-file .env python -m final_agent.api`
verwenden; `.env.example` enthält die unterstützten Umgebungsvariablen.

Der Objekteditor ist standardmäßig eingefroren: Vorschläge und Bestätigungen für
`add_object`, `update_object`, `remove_object`, `add_opening`, `add_connector` und
`undo_edit` enden mit `403 10002_forbidden`, und der Agent bekommt diese Werkzeuge
nicht angeboten. Sperrungen (`set_closed`) und Türen (`add_door`) bleiben erlaubt.
Für die Entwicklung `uv run python -m final_agent.api --map-editing` oder
`MAP_EDITING=1` setzen. Der Produktions-Build des Frontends (`npm run build`) enthält
weder den Karteneditor noch die Debug-Ansicht; beide gibt es nur unter `npm run dev`.

Die Oberfläche führt einen Chatverlauf mit sofort geleertem Eingabefeld, Sendestatus
und Retry. Ein Retry wiederholt dieselbe Anfrage mit demselben Idempotency-Key.
`GET .../messages` lädt den Verlauf nach einem Reload; Session und `last_route_id`
stellen den aktuellen Kartenzustand wieder her. Suche, Import, 3D, Simulation und
Diagnose liegen in sekundären Ansichten; die Simulation startet ausgeschaltet.

`Session.current_space_id` ist die bestätigte Position. `client_context.current_space_id`
setzt sie ausdrücklich; `selected_space_id` bleibt eine reine Kartenauswahl.
`client_context.destination_place_id` übergibt eine konkrete Rückfrage-Auswahl.
Direkte Routen können ebenfalls `current_space_id` übergeben. Alle IDs werden gegen
das Sitzungsgebäude geprüft. Sprachliche Standortmeldungen werden im Backend aufgelöst.
Unvollständige Navigationsanfragen bleiben bis zur Klärung erhalten. „Nearest/closest“
vergleicht sämtliche passenden Geräte anhand eingeschränkter Gehwege; Vergleiche
verändern die aktive Route nicht. Anschließend wird der gewählte Weg aktiviert und
als `draw_route` zurückgegeben. Eine Etage allein legt keinen Startpunkt fest.

`API_TOKEN` aktiviert optional Bearer-Auth. `CORS_ORIGINS` enthält erlaubte
Origins als kommagetrennte Liste; standardmäßig sind localhost und 127.0.0.1
auf Port 3000 und 5173 erlaubt. Keine Cookies. Die Header `ETag`, `Location`,
`X-Request-Id`, `X-API-Version`, `X-Schema-Version` und `Retry-After` sind im
Browser lesbar. `--rate-limit N` begrenzt Anfragen je IP und Minute; 0 deaktiviert
das zusätzliche App-Limit. Das Modell-Limit wird unabhängig davon als 429 gemeldet.

Jeder POST braucht einen neuen `Idempotency-Key`. Zum Wiederholen **derselben**
Anfrage denselben Schlüssel verwenden. Ein Schlüssel gilt pro Serverprozess für
Methode, Pfad und JSON-Body; cachebare Ergebnisse bleiben 24 Stunden erhalten.
Ein optionaler `If-Match` enthält die letzte ETag-Revision, einschließlich der
Anführungszeichen. Bei 409 `30012_revision_conflict` Sitzung neu laden und den
gleichen Request mit aktualisiertem `If-Match` wiederholen. Auch ein während
des Modellaufrufs konkurrierend geänderter Zustand kann diesen Konflikt auslösen.

Änderungen an Türen, Sperrungen und Objekten (Editor-Kinds, `GET /api/v1/object-types`
liefert den Typkatalog) zunächst als Aktion anzeigen. Erst
`POST .../confirmations` wendet sie an. Danach Session und betroffene Pläne neu
laden. Vorhandene Routen bleiben historische Snapshots; `last_route_id` wird
bei bestätigten Änderungen geleert. Eine neue Route ausdrücklich berechnen.
Es gibt höchstens eine offene Aktion pro Sitzung. Eine weitere Änderung erst
nach Bestätigung/Abbruch vorschlagen; sonst folgt `30010_action_conflict`.

Raummeldungen funktionieren über den Chat. Sie verwenden standardmäßig
`agent_output/room_notes.sqlite3` und die bestehende Facility-Ableitung aus
Gebäudemetadaten bzw. `building.id`; `--notes-db` ändert den Speicherpfad.
Sitzungsneustarts löschen diese Meldungen nicht. Jede Meldung wird sofort pro
Tool-Aufruf gespeichert und bleibt auch bei einem späteren HTTP-Modellfehler
erhalten; ein Retry zählt nicht doppelt, weil jeder Chat nur einmal zählt. `input_mode: transcript` nimmt Text des
Voice-Clients entgegen; Audio-Upload und SSE sind nicht Teil von v1.

## Beispiele erzeugen und prüfen

```bash
uv run python scripts/generate_api_fixtures.py
uv run python scripts/validate_api_fixtures.py
```

Der Generator liest das Manifest und `proc-factory-dev-003`, verwendet feste UUIDs
und UTC-Zeitpunkte und ruft kein Modell auf. Er überschreibt `examples/*.json`;
`index.json` ordnet jede Datei einem OpenAPI-Schema zu. Die Beispiele zeigen
deterministische echte Gebäudedaten, aber keine gemessene Modellantwort.

| Dateien | Verwendung |
|---|---|
| `health`, `buildings`, `building` | Verfügbarkeit und Gebäudeauswahl |
| `session`, `floors`, `plan`, `places`, `route` | Zustand, Geometrie, Suche und Route |
| `message`, `messages` | Beispielhafte Guide-Antwort mit `understood` und Route-Effekt; Dialogseite |
| `action_pending`, `session_pending` | Offene Bestätigungskarte |
| `action_confirmed`, `session_confirmed`, `plan_confirmed` | Zustand nach bestätigter Sperrung |
| `error_validation`, `error_not_found`, `error_model` | Stabile Fehlerpakete |
| `object_types` | Objektkatalog des Editors |
| `action_add_object_pending`, `action_add_object_confirmed` | Editor-Aktion mit `preview_objects` und `EditResult` |
| `error_invalid_placement` | `30014_invalid_placement` mit Regel in `details[].code` |

Die geometrischen Routen verwenden Kit 1.1.0: Tür-zu-Tür, Wandabstand und
Höhenkosten. Falls das geerbte Kit-Modell nur eine heuristische Distanz hat,
werden keine erfundenen Linien durch getrennte Geometrie ergänzt. Sichtbare
Teilstücke bleiben getrennte Legs; ein solcher Fall ist keine geometrisch
validierte vollständige Wegführung.

## Wayfinder-Integration

`frontend/` verwendet ausschließlich die Haupt-API ohne das ältere `engine`-Feld,
folgt Cursor-Pagination und liest bestätigte Sperrungen aus `Action.result`.
Alle Chat-Nachrichten gehen an den Agenten von main. `scripts/serve_api.py`
startet dieselbe API als Kompatibilitätsaufruf. Statische Debug-Vorschauen bleiben
sichtbar; API-Fehler lösen keine lokalen Ersatzantworten aus.

Der gemeinsame Generator erhält beide Beispielsätze. Die Frontend-Dateien
(`floor-plan*.json`, `message-accepted.json`, `message-clarify.json`,
`message-pending-action.json`, `action-pending.json`, `action-confirmed.json`)
behalten ihre festen Demo-UUIDs. `session.json` und `route.json` gehören zu diesem
Satz; `backend-session.json` und `backend-route.json` ergänzen die Backend-Beispiele.
`index.json` erfasst sämtliche 41 erzeugten Beispiele für die gemeinsame Prüfung.

`ANTHROPIC_API_KEY` bzw. eine SDK-Anmeldung authentifiziert Claude-Anfragen.
Claude-Aufrufe verwenden den Standard-SDK-Client von main.
`API_TOKEN` schützt unabhängig davon die lokale HTTP-API.
