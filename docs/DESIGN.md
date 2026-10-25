# DESIGN — Track 01 HTTP-Vertrag

> Autoritative Gestaltung. Die Wire-Form steht in `docs/api/openapi.yaml`. Widerspricht ein Beispiel hier der OpenAPI-Datei, gilt OpenAPI.
>
> Entscheidungen: `docs/adr/ADR-0001-http-session-contract.md`, `docs/adr/ADR-0003-voice-live-position.md`.

## 1. Zweck

Die Innenraum-Oberfläche muss entwickelt und vorgeführt werden können, bevor der Agent fertig ist. Das Backend implementiert später denselben HTTP-Vertrag. Der Sonntags-Benchmark bleibt eine Kommandozeile und geht nicht durch diese API.

Leser: Frontend, Backend, und wer in der Demo ein Gerät sucht, eine stufenfreie Route läuft oder eine Änderung bestätigt.

## 2. Übernommene Prinzipien

- [x] Deklarativ: `effects[].type` sagt der Oberfläche, was sie zeichnet. Eine neue Zeichenart ist ein neuer effect.
- [x] Trennung: Die Oberfläche rechnet keine Route. Das Modell liefert keine unbelegte Polylinie. Die HTTP-Schicht rechnet nicht an Polygonen.
- [x] Abhängigkeiten nur nach innen: Das Frontend hängt nur an OpenAPI. Die Backend-Anwendung darf `starter_agent` rufen. Das Domänenmodul hängt nicht an HTTP oder der UI.
- [x] Steckbar: Fällt das Modell aus, bleiben Grundriss, Suche und Route benutzbar.
- [x] Idempotent: Schreibende POSTs tragen `Idempotency-Key`. Eine Bestätigung macht erst detect, dann apply.
- [x] Reproduzierbar: Mocks erzeugt `scripts/generate_api_fixtures.py`. Beispiel-UUIDs und Zeitstempel sind fest.
- [x] Beobachtbar: Jede Antwort trägt `X-Request-Id`. Das Fehlerpaket trägt dieselbe `trace_id`.
- [x] Sicher: Keine Geheimnisse im Repository. Ein optionales Bearer-Token kommt nur aus der Umgebung.
- [x] Geringste Rechte: v1 hat keine Benutzerkonten. Ist `API_TOKEN` gesetzt, gilt ein Token für den Prozess. Ist es leer, läuft die lokale Demo offen.
- [x] Eine Quelle: Wire-Form = OpenAPI. Schließmenge und neue Türen gelten bei der Sitzungs-`revision`.
- [x] Fehlerisolation: Ein Modellfehler schreibt keine Schließmenge und legt keine ausstehende Aktion an.
- Zero-dependency rollout gilt für den Vertrag. Die Laufzeit des API-Prozesses wählt das Backend. Diese Ausnahme ist erklärt.

## 3. Plattform

| Punkt | Wahl |
|---|---|
| Vertrag | OpenAPI 3.1, `docs/api/openapi.yaml` |
| Transport | HTTP/1.1, `Content-Type: application/json`, UTF-8 |
| Pfad | `/api/v1` |
| Felder | `snake_case`; Abwesenheit ist `null` |
| Zeit | RFC 3339 UTC |
| Koordinaten | Lokale Meter, x nach rechts, y nach oben. Kein WGS84. |
| Größenklasse | B, Ausnahmen in `CLAUDE.md` |
| Kodierung | UTF-8 ohne BOM, LF |
| Dokumentensprache | Deutsch |

`schema_version` bleibt in jedem kompatiblen v1-Body `1`. Ein optionales Feld hebt weder diese Zahl noch die URL-Version. Clients ignorieren unbekannte Antwortfelder und unbekannte `effects[].type`. Unbekannte Request-Felder ergeben `20001_validation_failed`.

Eine brechende Änderung braucht eine neue ADR und `/api/v2`. Der Server sendet in v1 keine Felder, die OpenAPI nicht nennt.

## 4. Anforderungen

### FR

- FR-1: Gebäude seitenweise listen und den Etagenindex lesen.
- FR-2: Sitzung anlegen, Stufenfrei-Präferenz ersetzen, Sitzung löschen.
- FR-3: Zeichenbare Geometrie pro Etage lesen, inklusive bestätigter neuer Türen und Editor-Änderungen. `closed_ids` und `stacking` entsprechen der Sitzung derselben `revision`.
- FR-4: Räume und Geräte nach Wörtern suchen.
- FR-5: Route berechnen und die Polylinie pro Etage liefern. Unerreichbar bleibt eine Route mit `reachable: false`.
- FR-6: Einen Satz senden und Antworttext, `understood`, `effects` und die zitierten Routen erhalten.
- FR-7: Schließen, Wiederöffnen, eine Tür oder eine Editor-Änderung (FR-11) vorschlagen. Erst die Bestätigung ändert die Sitzung. Chat und Editor-Buttons nutzen denselben Ablauf `propose → confirm`.
- FR-8: Den Dialog seitenweise lesen. Nach einem Reload stellen `last_route_id` und `pending_action_id` die Karte wieder her.
- FR-9: Fehler haben stabile Codes. Kein Stacktrace in der Antwort.
- FR-10: Beispielantworten lassen sich aus dem dev-Datensatz erzeugen.
- FR-11: Objekt-Editor. Objekte anlegen, ändern, verschieben, auf andere Objekte stellen, entfernen. Türen, Durchgänge, Treppen, Rolltreppen und Aufzüge hinzufügen. Die letzte Änderung rückgängig machen. Wände und Raumumrisse bleiben unveränderlich.
- FR-12 Sprachschleife: Bei aktivem Voice-Modus bleibt das Mikrofon offen. Jede Äußerung wird transkribiert, als Nutzernachricht gezeigt, vom Agenten beantwortet und gesprochen. Voice-Antworten sind ein bis zwei kurze Sätze. Ein Provider-Fehler zeigt einen Fehler, Texteingabe bleibt nutzbar.
- FR-13 Live-Position: Der Client sendet Positionsfixes in Plan-Metern. Der Server löst sie zu einem Raum auf. Der Agent nutzt eine frische Live-Position als Routenstart. Ein Fix ändert `revision` nicht und löst kein `30012_revision_conflict` aus.
- FR-14 Geführter Weg: Der Server nennt den nächsten Wegpunkt und die nächste Anweisung, sobald die Position höchstens 3 m vom aktuellen Ziel entfernt ist. Die Ankunft wird gemeldet.
- FR-15 Falsche Richtung: Pro Wegpunkt höchstens eine Warnung. Danach Stille und keine automatische Neuroute. Die Warnung wird erst nach dem nächsten erreichten Wegpunkt wieder scharf.
- FR-16 Erzähler: Ein KI-Aufruf pro Route wählt Sätze aus einem festen Phrasenkatalog und füllt Landmarken. Distanzen, Seiten und Namen kommen aus Code. Fällt das Modell aus, gelten die Standardphrasen.

FR-1 → `list_buildings`, `get_building`. FR-2 → sessions. FR-3 → `get_floor_plan`. FR-4 → `search_places`. FR-5 → routes. FR-6 → `create_message`. FR-7 → actions. FR-8 → `list_messages` und Session. FR-9 → `Error`. FR-10 → `scripts/generate_api_fixtures.py`. FR-11 → `list_object_types`, actions mit den Editor-Kinds, `FloorPlan.stacking`; Regeln in `docs/superpowers/specs/2026-10-25-object-editor-design.md`. FR-12 → `create_transcription`, `create_transcription_token`, `get_speech_clip`, `create_message` mit `input_mode: voice`. FR-13 → `put_position`. FR-14, FR-15 → `get_guidance`, `put_guidance`, `delete_guidance`. FR-16 → Phrasenkatalog in `final_agent/narration.py`.

### NFR

- NFR-1 Kompatibilität: v1 nur additiv. Clients ignorieren unbekannte Felder.
- NFR-2 Zuverlässigkeit: Schreibaufrufe sind wiederholbar. Ein Modell-Timeout hinterlässt keine halbe Änderung. Wiederholtes `DELETE` einer Sitzung ist 204.
- NFR-3 Sicherheit: Keine Schlüssel im Repo. Body-Grenzen stehen in OpenAPI. Logs enthalten kein `Authorization`.
- NFR-4 Wartbarkeit: Domänencode importiert kein Web-Framework.
- NFR-5 Effizienz: Ein Plan-Aufruf liefert eine Etage. Listen haben ein `limit`-Maximum.
- NFR-6 Beobachtbarkeit: Antworten tragen `X-Request-Id`. Diese Iteration verspricht keine Metriken und keinen verteilten Trace.
- Latenzzahlen werden gemessen, wenn das Backend steht. Der Vertrag nennt kein ungeprüftes p95.

### Nicht in v1

- Sonntags-Benchmark, Fragenkatalog, Bewertung.
- SSE. Der Guidance-Feed ist ein Long-Poll (ADR-0003).
- Ein Gebäude aus einem Grundriss erzeugen.
- Eine Sitzung für mehrere Gebäude.
- Etagen-PNG. Der Client zeichnet Polygone.
- Batch-Endpunkte. Ein späteres Batch liefert pro Element `ok`.

## 5. Architektur

Beteiligte: Frontend, Backend, Demo-Bedienung. Die Oberfläche wartet nicht auf das Modell. Änderungen sind bestätigbar. Nach dem Reload stimmen Karte und Sitzung überein.

```
Frontend  →  HTTP /api/v1  →  Application (Sitzung, Idempotenz, Aktionen)
                                    ↓
                              Domain (Gebäudegraph, Route, Suche)
                                    ↓
                              data/<split>/<building_id>/building.json
```

Verboten: Frontend importiert `starter_agent`. Domäne importiert einen HTTP-Client. Der Message-Handler ändert `closed_ids` ohne Aktionsbestätigung.

Ablauf:

1. Der Client legt eine Sitzung an und erhält `revision: 1`.
2. Er lädt den Plan pro Etage und zeichnet Polygone, Türen und Geräteflächen.
3. Suche oder ein Klick erzeugt eine Id, keine Route.
4. Route oder Nachricht liefert `route_id` und `points` pro Etage.
5. Eine Gebäudeänderung erscheint zuerst als `pending`. Nach der Bestätigung steigt `revision`.

`revision` folgt nur dem Kartenzustand: Präferenz, Schließmenge, bestätigte Edits, `last_route_id`, `pending_action_id`. Reiner Text erhöht `revision` nicht.

Stufenfrei: fehlt `preferences` beim Anlegen, ist `step_free` false. `PUT .../preferences` wird der spätere Default. Ein Satz darf das über `client_context.preferences.step_free` nur für diesen Turn übersteuern. Die Oberfläche zeigt `understood.constraints.step_free`.

Begehbare Figur: Die Karte kann eine Figur auf der aktuellen Etage bewegen. Wände und Türen werden aus den Polygonkanten und Öffnungen des gelesenen Plans abgeleitet. Die Figur berechnet keine Route, schreibt keine Sitzung und wechselt die Etage nicht. Siehe `docs/specs/map-walker.md` und `docs/adr/ADR-0002-map-walker.md`. Die Position bleibt nicht mehr nur in der Seite: Die Figur sendet sie als Live-Position an die Sitzung (`PUT .../position`, ADR-0003). Sie ist trotzdem kein Sitzungszustand mit `revision`.

Live-Position und Führung: `LiveState` pro Sitzung besitzt Position, Fortschritt und Ereignisse. Der Navigator vergleicht jeden Fix mit dem aktuellen Ziel. Die nächste Anweisung folgt erst bei höchstens 3 m. Der Feed `GET .../guidance` ist ein Long-Poll mit Cursor `after`. Sprachtexte haben eine `speech_clip_id`. Das Audio holt der Client mit `GET .../speech-clips/{clip_id}`. Der Server synthetisiert beim ersten Abruf und cached.

## 6. Datenmodell

Erfolgsbodies tragen `schema_version: 1`. Das Fehlerpaket trägt das Feld nicht. Die Fehlerform ändert sich innerhalb von v1 nicht.

| Entität | Identität | Bedeutung |
|---|---|---|
| Session | UUID | `building_id`, `revision`, `preferences`, `closed_ids`, `last_route_id`, `pending_action_id` |
| Route | UUID | Polylinie und `reachable`. Wird nicht automatisch neu gerechnet, wenn sich Schließungen ändern. |
| Message | UUID | Nutzer- und Guidesatz. Der Guidesatz speichert `understood` und `effects`, nicht die ganze Polylinie. |
| Action | UUID | `pending → confirmed \| cancelled \| expired` |
| IdempotencyRecord | `Idempotency-Key` | siehe unten |

Wenn v1-Zustand persistiert wird, trägt das Dokument `schema_version`. Ein Upgrade schreibt neu und lässt das alte Dokument lesbar. Während des Hackathons darf die Sitzung nur im Speicher leben. Die Feldnamen bleiben dieselben.

### Aktionszustände

- `pending`: das Gebäude ist unverändert. `expires_at` liegt 15 Minuten nach der Erstellung.
- `confirmed`: detect sieht eine schon bestätigte `action_id` und liefert das erste Ergebnis. Keine zweite Tür.
- `cancelled`: keine Gebäudeänderung. Erneutes Abbrechen liefert das erste Abbruchergebnis.
- `expired`: Bestätigen nach Ablauf ergibt `30009_action_expired`.
- Bestätigen einer abgebrochenen Aktion, oder Abbrechen einer bestätigten Aktion: `30010_action_conflict`.

Detect beim Türhinzufügen: Gibt es für dasselbe `space_ids`-Paar schon eine Tür, liefert die Bestätigung diese Öffnung.

### Idempotenz

- Gilt für `POST` zum Anlegen von Sitzung, Route, Nachricht, Aktion, Bestätigung und Abbruch.
- Schlüssel: Header `Idempotency-Key`, 1–128 sichtbare ASCII-Zeichen. TTL 24 Stunden.
- Gleicher Schlüssel, gleicher Body, erstes Ergebnis 2xx: erste Antwort, keine zweite Nebenwirkung.
- Gleicher Schlüssel, anderer Body: `409` + `20011_idempotency_key_mismatch`. Dieses 4xx wird gemerkt.
- Andere 4xx außer `30012_revision_conflict` werden gemerkt.
- 5xx, 429 und `30012_revision_conflict` werden nicht gemerkt. Der Client darf denselben Schlüssel wiederholen.
- `GET`, `PUT` und `DELETE` brauchen den Header nicht. `PUT` der Präferenz ersetzt das ganze Objekt. `DELETE` einer fehlenden Sitzung ist 204.

### Seiten

Standard ist Cursor-Paging. Bei `has_more: false` ist `next_cursor` `null`. Der Cursor ist opak.

| Liste | Default limit | Maximum |
|---|---|---|
| buildings, messages | 20 | 100 |
| places | 15 | 50 |

Filter sind nur die in OpenAPI genannten. `include` akzeptiert nur `spaces`, `openings`, `assets`, `connectors`.

Externe Ids: Gebäude und Geometrie nutzen Datensatz-Ids. Sitzung, Nachricht, Route und Aktion nutzen UUIDs. `revision` ist eine Nebenläufigkeitsversion, keine Identität.

## 7. Schnittstelle

Normative Details stehen in OpenAPI. Hier steht die Semantik.

### Fehlerpaket

```json
{
  "code": "20001_validation_failed",
  "message": "Human readable summary",
  "trace_id": "11111111-1111-4111-8111-111111111111",
  "details": [{ "field": "text", "code": "too_long" }]
}
```

`code` ist stabil. `message` ist Englisch und nur für Logs. Die Oberfläche verzweigt auf `code`. Stacktraces gehen nur ins Log.

| HTTP | code | Wann |
|---|---|---|
| 500 | `00001_internal` | Unerwarteter Fehler |
| 429 | `00002_rate_limited` | Gateway- oder App-Limit. Mit `Retry-After`. |
| 401 | `10001_unauthenticated` | `API_TOKEN` ist gesetzt, Token fehlt oder stimmt nicht. |
| 403 | `10002_forbidden` | Authentifiziert, aber ohne Recht. Auch bei eingefrorenem Objekteditor: `POST .../actions` und Bestätigungen für `add_object`, `update_object`, `remove_object`, `add_opening`, `add_connector`, `undo_edit` ohne `MAP_EDITING=1` bzw. `--map-editing`; Detail `{"field": "kind", "code": "map_editing_disabled"}`. |
| 400 | `20001_validation_failed` | Feldweise `details`. Editor: `code` `invalid` oder `unknown_type` (Typ fehlt im Katalog und keine Kategorie) |
| 400 | `20010_idempotency_key_required` | POST ohne Schlüssel |
| 409 | `20011_idempotency_key_mismatch` | Gleicher Schlüssel, anderer Body |
| 413 | `20012_payload_too_large` | Über der in OpenAPI genannten Größe |
| 404 | `30001_building_not_found` | Gebäude fehlt |
| 404 | `30002_session_not_found` | Sitzung fehlt |
| 404 | `30003_floor_not_found` | Etage fehlt |
| 404 | `30004_place_not_found` | Start, Ziel oder Raum einer Editor-Proposal (`space`, `first_space`, `second_space`, `spaces`) nicht auflösbar. `details[].field` nennt das Feld. |
| 409 | `30005_place_ambiguous` | `details` nennt Kandidaten-Ids |
| 409 | `30007_not_adjacent` | Die zwei Räume teilen keine Wand oder keine Etage, die Wand ist zu kurz, an der Position liegt keine Wand oder dort ist schon eine Öffnung |
| 404 | `30008_action_not_found` | Aktion fehlt |
| 409 | `30009_action_expired` | Aktion abgelaufen |
| 409 | `30010_action_conflict` | Bestätigen oder Abbrechen widerspricht dem Zustand |
| 409 | `30012_revision_conflict` | `If-Match` passt nicht zur `revision` |
| 404 | `30013_element_not_found` | Aufzug, Tür oder Raum zum Schließen fehlt. Editor: Objekt oder Träger fehlt (`details[].field` `object_ref` oder `on_top_of`). Unbekannte `client_context.selected_object_id` (`field: selected_object_id`). |
| 409 | `30014_invalid_placement` | Editor-Regel verletzt. `details[].code` ist die Regel: `outside_space`, `crosses_wall`, `floating`, `support_cycle`, `support_other_space`, `would_strand`, `exceeds_ceiling`, `not_stacked`, `same_floor`. `details[].message` erklärt sie auf Englisch. |
| 409 | `30015_nothing_to_undo` | Undo ohne bestätigte Gebäudeänderung in dieser Sitzung |
| 409 | `30016_not_removable` | Tür, Treppe oder Aufzug aus dem Datensatz. Nur Schließen ist möglich. |
| 503 | `40001_model_unavailable` | Nur messages |
| 429 | `40002_model_rate_limited` | Nur messages. Mit `Retry-After`. |
| 504 | `40003_model_timeout` | Nur messages |
| 503 | `40004_speech_unavailable` | Sprachanbieter nicht nutzbar. `details.reason` ist `not_configured`, `auth`, `rate_limited`, `timeout` oder `provider_error`. |
| 404 | `30017_speech_clip_not_found` | Unbekannte `clip_id` |

Reserviert und nicht umzuwidmen: `30006` und `30011`. Eine Transkription mit falschem Audiotyp ist `20001_validation_failed` mit Feld `Content-Type`. Eine Suche ohne Treffer ist 200 und eine leere Liste. Eine Nachricht mit unklarem Ort ist 201, `intent` ist `clarify` oder `unknown`.

### Sprache und Position

| Operation | Semantik |
|---|---|
| `put_position` | `PUT /sessions/{id}/position`. Ersetzt die Live-Position. Kein `Idempotency-Key`, keine `revision`. Veraltete Fixes kommen mit `applied: false` zurück. Ein Fix älter als 15 s gilt als `stale`. |
| `create_transcription` | `POST /sessions/{id}/transcriptions`. Roher Audio-Body, `Idempotency-Key` pro Äußerung. Antwort `{text, language}`. Rauschen ergibt `text: ""`. |
| `create_transcription_token` | `POST /sessions/{id}/transcription-tokens`. 201 mit Einmal-Token und WebSocket-URL. Der Browser streamt PCM (16 kHz) schon während der Äußerung direkt zum Sprachdienst und committet am Ende. Fallback ist `create_transcription`. |
| `get_guidance` | `GET /sessions/{id}/guidance?after=n&wait_s=0..25`. Zustand plus Ereignisse nach `after`. Long-Poll. |
| `put_guidance` | `PUT /sessions/{id}/guidance`, `{route_id}`. Startet die Führung ohne Agenten. |
| `delete_guidance` | `DELETE /sessions/{id}/guidance`. 204, Status `idle`. |
| `get_speech_clip` | `GET /sessions/{id}/speech-clips/{clip_id}`. `audio/mpeg`. |

`position` und `guidance` sind Singletons nach dem Muster von `preferences` (Ausnahme von „Nomen im Plural“, ADR-0003). `GuidanceEvent.kind` ist `instruction`, `wrong_way`, `arrived` oder `stopped`. `MessageCreate.input_mode` kennt `voice`. `MessageAccepted.speech_clip_id` ist nur bei Voice-Turns nicht `null`. Eine bestätigte Schließung auf der geführten Route beendet die Führung mit `stopped`.

### Header

- `X-Request-Id`: optional vom Client. Fehlt er, erzeugt ihn der Server.
- `Idempotency-Key`: bei den genannten POSTs Pflicht.
- `If-Match`: optional, quoted revision, zum Beispiel `"1"`. Bei Abweichung 409.
- `Authorization: Bearer <token>`: Pflicht nur, wenn `API_TOKEN` nicht leer ist.

Antwortheader: `X-Request-Id`, `X-API-Version: 1`, `X-Schema-Version: 1`. Erfolgreiche Antworten mit Sitzungszustand tragen `ETag`. Anlegen antwortet 201 und setzt `Location`.

### Koordinaten und Polylinie

Jeder Punkt in `points` ist `[x, y]` in Metern, y nach oben. Polygone sind nicht geschlossen.

`legs[]` enthält nur die Polylinie dieser Etage. Knicke sind Raumanker und Türpositionen, in Gehreihenfolge. Treppe und Aufzug zeichnen keine Linie zwischen Etagen. Der Satz steht in `directions`. Längenmodell des Kits: Treppe 12 m pro Etage, Aufzug 15 m Warten plus 6 m pro Etage. Der Client rechnet `length_m` nicht nach.

`directions[].at` darf `null` sein. Der Server soll den Startpunkt des Satzes setzen. Ist `at` null, zeigt der Client trotzdem `text`.

### effects

In Array-Reihenfolge anwenden. Unbekannter `type`: dieses Element überspringen.

| type | Oberfläche |
|---|---|
| `highlight_spaces` | Räume nach `reason` hervorheben: `match`, `selected`, `closed`, `preview`. |
| `highlight_assets` | Geräte hervorheben. |
| `focus` | Auf diese Etage wechseln, optional zur `point`. |
| `draw_route` | Linie über `route_id`. Dieselbe Antwort liefert das Objekt in `routes`. |
| `clear_route` | Linie löschen. `last_route_id` ist `null`. |
| `set_closures` | Lokale Schließmenge durch die volle `closed_ids`-Liste ersetzen. |
| `ask` | Klärungsoptionen zeigen, kein Formular. |
| `building_patched` | Diese `floor_ids` neu per GET plan laden. |
| `preview_objects` | Vorschau einer Editor-Aktion als Geister zeichnen: `assets`, `openings`, `connectors` im Zustand danach, `removed_ids` ausgeblendet. Ändert den Plan nicht. |

### Objekt-Editor

Regeln und Datenmodell stehen in `docs/superpowers/specs/2026-10-25-object-editor-design.md`. Hier steht der HTTP-Teil.

- Katalog: `GET /api/v1/object-types` liefert `final_agent/object_types.json`, ohne Sitzung. Objekttypen tragen Default-Breite, -Tiefe und -Höhe.
- Kinds: `add_object`, `update_object`, `remove_object`, `add_opening`, `add_connector`, `undo_edit`. Fehlende Felder oder `null` bedeuten Default beim Anlegen und „unverändert“ beim Ändern.
- Vorschlagen prüft die Änderung auf einer Kopie der Sitzungskarte. Die Aktion speichert die normalisierte Proposal: Ids statt Namen, berechnete Position, gefüllte Defaults. Ohne Angabe bleibt `height_m` `null`, dann gilt die Katalog-Höhe. `preview_effects` = `preview_objects` plus `highlight_spaces` mit `reason: preview`.
- Bestätigen wendet die gespeicherte Proposal an. `result` ist `EditResult`: `kind`, `summary`, `changed_ids`, `removed_ids`, `floor_ids`. Der Client lädt die Pläne aus `floor_ids` neu.
- Sitzungsdateien: Jede bestätigte Gebäudeänderung (Editor-Kinds und `add_door`) schreibt in derselben Transaktion `agent_output/api/<session_id>/building_edited.json` und daneben `stacking_adapter.json`. Scheitert das Speichern, wird alles zurückgerollt: 500 `00001_internal`, die Aktion bleibt `pending` und kann erneut bestätigt werden. Andere Sitzungen und der Datensatz bleiben unverändert.
- Undo: Ein Stapel von höchstens 20 Einträgen pro Sitzung. Jede bestätigte Gebäudeänderung außer `undo_edit` legt einen Eintrag an, auch eine bestätigte `add_door`-Tür. `undo_edit` stellt den Stand davor wieder her und behält die aktuellen Schließungen, minus Ids, die es dann nicht mehr gibt. Zusammenfassung `Undo: <summary>`. Ein leerer Stapel ergibt `30015_nothing_to_undo`.
- Entfernen: Ein Objekt geht samt allem, was darauf steht. Öffnungen und Verbinder nur, wenn sie in der Sitzung hinzugefügt wurden.
- Stapel und Höhen: `FloorPlan.stacking` listet die Objekte der Etage, die gestapelt sind, etwas tragen oder einen Höhen-Override haben, mit `layer`, `on_top_of`, `height_m`, `height_source` und `elevation_m`. Alle anderen stehen am Boden und haben die Katalog-Höhe.
- Rolltreppe: Keine Kit-Doku nennt Rolltreppen. Annahme: beidseitig begehbar, Kosten wie eine Treppe, nie stufenfrei. Der Router bleibt unverändert.
- Chat: Die Guide-Tools mit denselben Namen wie in der CLI schlagen nur vor. `ApiReply.intent` ist dann `edit`. `client_context.selected_object_id` (Objekt, Tür oder Verbinder) erreicht den Turn-Kontext.

### Auth, Limit, CSRF

v1 nutzt keine Cookies und damit kein CSRF-Token. Cross-Origin steuert das Backend über `CORS_ORIGINS`. Über dem Limit: 429 und `Retry-After`. JSON-Bodies höchstens 64 KiB. Einzige Ausnahme ist Audio bis 2 MiB auf `POST .../transcriptions`. Darüber gilt `20012_payload_too_large`.

Limit: Der Client sendet etwa eine Position pro Sekunde (`PUT .../position`) und hält einen Long-Poll offen. Das App-Limit muss beides tragen, sonst kommt `00002_rate_limited` und die Führung hakt. Jeder offene Long-Poll belegt einen Threadpool-Thread, bis er endet oder abläuft.

Logs auf Info: `trace_id`, Methode, Pfad, Status, Dauer, `session_id`. Der originale Nutzersatz nur auf Debug. Kein Authorization-Header im Log.

## 8. Fahrplan

- M1: v1-Vertrag und dev-Mock. Das Frontend entwickelt dagegen.
- M2: Backend implementiert buildings, sessions, plan, places, routes, actions.
- M3: Backend hängt messages an den Agenten. Fällt das Modell aus, bleiben die M2-Endpunkte nutzbar.
- M4: Sprache und Live-Position (EXT-02): Position, Führung, Transkription, Sprachclips. Der Browser-Mikrofontest und die Live-Prüfung mit ElevenLabs und Anthropic stehen noch aus.
- Später: Streaming, Entwurfsgebäude, mehrere Häuser, Wi-Fi-Ortung statt Figur. Fehlt `input_mode`, gilt `text`.

## 9. Offene Punkte

- Ob ein Gebäude aus einem Plan eine Sitzung ohne Datensatz-Id bekommen darf. v1 unterstützt das nicht.
- Entschieden: Der Server wandelt Sprache mit ElevenLabs (STT und TTS), siehe ADR-0003. `input_mode: voice` markiert den Turn. Der Schlüssel liegt nur in der Umgebung.
- Offen: Echo-Unterdrückung bei Lautsprechern (Barge-in). Für die Demo gelten Kopfhörer. Die Latenz bis zum ersten Ton ist ungemessen.

## 10. Änderungsmatrix

| Änderung | Mitprüfen |
|---|---|
| OpenAPI-Feld oder Fehlercode | Diese Tabelle, examples, beide Seiten |
| Geometriefelder in `building.json` | Floor-plan-Schema, Fixture-Skript |
| Routenkostenmodell | Backend-Route und Kit-Bewertung. HTTP-Feldnamen bleiben. |
| Position, Führung, Sprache | Diese Tabelle, ADR-0003, Fixtures, `final_agent/narration.py`, Frontend `features/voice` |
| Neuer effect-Typ | OpenAPI oneOf, Frontend-Zweig für unbekannte Typen |
| Brechende Änderung | Neue ADR, `/api/v2`, CHANGELOG |

## 11. Mock

```bash
uv run python scripts/generate_api_fixtures.py
```

Das Skript liest `data/manifest.csv` und `data/dev/proc-factory-dev-003` und schreibt `docs/api/examples/`. Der nächste Lauf überschreibt Handänderungen. Die Zuordnung steht in `docs/api/README.md`. `scripts/validate_api_fixtures.py` prüft die Beispiele gegen die OpenAPI-Schemas.
