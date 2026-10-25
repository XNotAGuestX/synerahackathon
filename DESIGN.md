# DESIGN — Track 01 HTTP-Vertrag

> Autoritative Gestaltung. Die Wire-Form steht in [openapi.yaml](openapi.yaml). Widerspricht ein Beispiel hier der OpenAPI-Datei, gilt OpenAPI.
>
> Implementierung und Start: [docs/api/README.md](docs/api/README.md). Die ursprünglich referenzierte ADR wurde nicht mitgeliefert.

## 1. Zweck

Die Innenraum-Oberfläche muss entwickelt und vorgeführt werden können, bevor der Agent fertig ist. Das Backend implementiert später denselben HTTP-Vertrag. Der Sonntags-Benchmark bleibt eine Kommandozeile und geht nicht durch diese API.

Leser: Frontend, Backend, und wer in der Demo ein Gerät sucht, eine stufenfreie Route läuft oder eine Änderung bestätigt.

## 2. Übernommene Prinzipien

- [x] Deklarativ: `effects[].type` sagt der Oberfläche, was sie zeichnet. Eine neue Zeichenart ist ein neuer effect.
- [x] Trennung: Die Oberfläche rechnet keine Route. Das Modell liefert keine unbelegte Polylinie. Die HTTP-Schicht rechnet nicht an Polygonen.
- [x] Abhängigkeiten nur nach innen: Das Frontend hängt nur an OpenAPI. Die Backend-Anwendung ruft `final_agent`. Das Domänenmodul hängt nicht an HTTP oder der UI.
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
| Vertrag | OpenAPI 3.1, `openapi.yaml` |
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
- FR-3: Zeichenbare Geometrie pro Etage lesen, inklusive bestätigter neuer Türen. `closed_ids` entspricht der Sitzung derselben `revision`.
- FR-4: Räume und Geräte nach Wörtern suchen.
- FR-5: Route berechnen und die Polylinie pro Etage liefern. Unerreichbar bleibt eine Route mit `reachable: false`.
- FR-6: Einen Satz senden und Antworttext, `understood`, `effects` und die zitierten Routen erhalten.
- FR-7: Schließen, Wiederöffnen oder eine Tür vorschlagen. Erst die Bestätigung ändert die Sitzung.
- FR-8: Den Dialog seitenweise lesen. Nach einem Reload stellen `last_route_id` und `pending_action_id` die Karte wieder her.
- FR-9: Fehler haben stabile Codes. Kein Stacktrace in der Antwort.
- FR-10: Beispielantworten lassen sich aus dem dev-Datensatz erzeugen.

FR-1 → `list_buildings`, `get_building`. FR-2 → sessions. FR-3 → `get_floor_plan`. FR-4 → `search_places`. FR-5 → routes. FR-6 → `create_message`. FR-7 → actions. FR-8 → `list_messages` und Session. FR-9 → `Error`. FR-10 → `scripts/generate_api_fixtures.py`.

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
- SSE.
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

Verboten: Frontend importiert `final_agent`. Domäne importiert einen HTTP-Client. Der Message-Handler ändert `closed_ids` ohne Aktionsbestätigung.

Ablauf:

1. Der Client legt eine Sitzung an und erhält `revision: 1`.
2. Er lädt den Plan pro Etage und zeichnet Polygone, Türen und Geräteflächen.
3. Suche oder ein Klick erzeugt eine Id, keine Route.
4. Route oder Nachricht liefert `route_id` und `points` pro Etage.
5. Eine Gebäudeänderung erscheint zuerst als `pending`. Nach der Bestätigung steigt `revision`.

Bestätigte Möbel-/Geräteänderungen gelten gemeinsam pro Datensatz/Gebäude und bleiben
nach Neustarts erhalten. `Session.object_revision` versioniert diesen Bestand;
Höhen und Stapelbeziehungen werden mit den Objekten atomar gespeichert. Andere
Sitzungen übernehmen Änderungen vor Zugriffen und im sichtbaren Browser alle zwei
Sekunden. Alte Vorschauen werden verworfen (409 bei Bestätigungsversuch), unsichere
Undo-Snapshots gelöscht und Routen/Sprachausgabe gestoppt. Türen, Verbindungen,
Sperrungen und Gespräch bleiben sitzungsbezogen. Details: [Speichervertrag](docs/api/README.md#shared-room-objects).

`revision` folgt nur dem Kartenzustand: Präferenz, Schließmenge, bestätigte Edits, `last_route_id`, `pending_action_id`. Reiner Text erhöht `revision` nicht.

Stufenfrei: fehlt `preferences` beim Anlegen, ist `step_free` false. `PUT .../preferences` wird der spätere Default. Ein Satz darf das über `client_context.preferences.step_free` nur für diesen Turn übersteuern. Die Oberfläche zeigt `understood.constraints.step_free`.

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

Pro Sitzung ist höchstens eine Aktion offen. Eine zweite REST-Proposal-Anfrage
ergibt `409` mit `30010_action_conflict`; im Chat wird zuerst um Bestätigung oder
Abbruch der bestehenden Aktion gebeten. Es wird kein Vorschlag stillschweigend ersetzt.

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
- Der Schlüssel gilt pro Prozess; der Fingerprint umfasst Methode, Pfad und kanonisches JSON. Ein Replay behält das erste fachliche Ergebnis, erhält aber die aktuelle Request-/Trace-Id. Ein konkurrierend während eines Modellaufrufs geänderter Sitzungszustand ergibt ebenfalls `30012_revision_conflict`.
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
| 403 | `10002_forbidden` | Authentifiziert, aber ohne Recht. v1 kann das ungenutzt lassen. |
| 400 | `20001_validation_failed` | Feldweise `details` |
| 400 | `20010_idempotency_key_required` | POST ohne Schlüssel |
| 409 | `20011_idempotency_key_mismatch` | Gleicher Schlüssel, anderer Body |
| 413 | `20012_payload_too_large` | Über der in OpenAPI genannten Größe |
| 404 | `30001_building_not_found` | Gebäude fehlt |
| 404 | `30002_session_not_found` | Sitzung fehlt |
| 404 | `30003_floor_not_found` | Etage fehlt |
| 404 | `30004_place_not_found` | Start oder Ziel nicht auflösbar |
| 409 | `30005_place_ambiguous` | `details` nennt Kandidaten-Ids |
| 409 | `30007_not_adjacent` | Die zwei Räume teilen keine Wand oder keine Etage |
| 404 | `30008_action_not_found` | Aktion fehlt |
| 409 | `30009_action_expired` | Aktion abgelaufen |
| 409 | `30010_action_conflict` | Bestätigen oder Abbrechen widerspricht dem Zustand |
| 409 | `30012_revision_conflict` | `If-Match` passt nicht zur `revision` |
| 404 | `30013_element_not_found` | Aufzug, Tür oder Raum zum Schließen fehlt |
| 503 | `40001_model_unavailable` | Nur messages |
| 429 | `40002_model_rate_limited` | Nur messages. Mit `Retry-After`. |
| 504 | `40003_model_timeout` | Nur messages |

Reserviert und nicht umzuwidmen: `30006` und `30011`. Eine Suche ohne Treffer ist 200 und eine leere Liste. Eine Nachricht mit unklarem Ort ist 201, `intent` ist `clarify` oder `unknown`.

### Header

- `X-Request-Id`: optional vom Client. Fehlt er, erzeugt ihn der Server.
- `Idempotency-Key`: bei den genannten POSTs Pflicht.
- `If-Match`: optional, quoted revision, zum Beispiel `"1"`. Bei Abweichung 409.
- `Authorization: Bearer <token>`: Pflicht nur, wenn `API_TOKEN` nicht leer ist.

Antwortheader: `X-Request-Id`, `X-API-Version: 1`, `X-Schema-Version: 1`. Erfolgreiche Antworten mit Sitzungszustand tragen `ETag`. Anlegen antwortet 201 und setzt `Location`.

### Koordinaten und Polylinie

Jeder Punkt in `points` ist `[x, y]` in Metern, y nach oben. Polygone sind nicht geschlossen.

`legs[]` enthält nur die Polylinie dieser Etage. Knicke folgen den ausgewählten Türen und dem wandabständigen Laufweg in Gehreihenfolge. Treppe und Aufzug zeichnen keine Linie zwischen Etagen. Der Satz steht in `directions`. Längenmodell des Kits 1.1.0: Treppe 2 m pro Meter Höhendifferenz, Aufzug 15 m Warten plus 1 m pro Meter Höhendifferenz. Der Client rechnet `length_m` nicht nach. Der geerbte Geometrie-Fallback kann eine heuristische Distanz liefern, ohne einen vollständigen validierten Laufweg zu besitzen; fehlende geometrische Teilstücke werden nicht durch erfundene Linien ersetzt.

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

### Auth, Limit, CSRF

v1 nutzt keine Cookies und damit kein CSRF-Token. Cross-Origin steuert das Backend über `CORS_ORIGINS`. Über dem Limit: 429 und `Retry-After`. JSON-Bodies höchstens 64 KiB; rohe Audio-Uploads an `transcriptions` höchstens 2 MiB.

Logs auf Info: `trace_id`, Methode, Pfad, Status, Dauer, `session_id`. Der originale Nutzersatz nur auf Debug. Kein Authorization-Header im Log.

## 8. Fahrplan

- M1: v1-Vertrag und dev-Mock. Das Frontend entwickelt dagegen.
- M2: Backend implementiert buildings, sessions, plan, places, routes, actions.
- M3: Backend hängt messages an den Agenten. Fällt das Modell aus, bleiben die M2-Endpunkte nutzbar.
- Sprachmodus: WAV an `POST transcriptions`, den erkannten Text mit `input_mode: voice` an messages. `guide_message.text` bleibt ausführlich; `speech_text` enthält die kurze gesprochene Antwort und `speech_clip_id` ihren Clip. `input_mode: transcript` bleibt reine Texteingabe; ohne input_mode gilt `text`. Führung nutzt den bestehenden Long-Poll-Feed (ADR-0003). Der Browser nutzt keine direkten Provider-WebSockets mehr; der Token-Endpunkt bleibt kompatibel verfügbar.

## 9. Offene Punkte

- Ob ein Gebäude aus einem Plan eine Sitzung ohne Datensatz-Id bekommen darf. v1 unterstützt das nicht.
- Physisches Mikrofon, Echo und iPhone Safari sind noch nicht gerätegeprüft. Implementierung und fokussierte Browserprüfungen: [VOICE_AUDIO_HANDOFF.md](VOICE_AUDIO_HANDOFF.md).

## 10. Änderungsmatrix

| Änderung | Mitprüfen |
|---|---|
| OpenAPI-Feld oder Fehlercode | Diese Tabelle, examples, beide Seiten |
| Geometriefelder in `building.json` | Floor-plan-Schema, Fixture-Skript |
| Routenkostenmodell | Backend-Route und Kit-Bewertung. HTTP-Feldnamen bleiben. |
| Neuer effect-Typ | OpenAPI oneOf, Frontend-Zweig für unbekannte Typen |
| Brechende Änderung | Neue ADR, `/api/v2`, CHANGELOG |

## 11. Mock

```bash
uv run python scripts/generate_api_fixtures.py
```

Das Skript liest `data/manifest.csv` und `data/dev/proc-factory-dev-003` und schreibt `docs/api/examples/`. Der nächste Lauf überschreibt Handänderungen. Die Zuordnung steht in `docs/api/README.md`. `scripts/validate_api_fixtures.py` prüft die Beispiele gegen die OpenAPI-Schemas.
