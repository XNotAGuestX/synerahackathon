# ADR-0001 — HTTP-Sitzungsvertrag

- Status: Accepted
- Datum: 2026-10-24
- Entscheider: Frontend schlägt diese Basis für das Backend vor. Eine brechende Änderung braucht eine neue ADR.

## Kontext

Die Oberfläche muss fertig werden, bevor der Agent steht. Die Daten liegen in `data/<split>/<building_id>/building.json`. Die Domänenreferenz ist `starter_agent`. Der Sonntags-Benchmark ist eine Kommandozeile und geht nicht durch diese HTTP-API.

Das Frontend braucht einen mockbaren Vertrag: Grundriss, Suche, Routenpolylinie, verstandenes Anliegen, bestätigtes Schließen oder eine neue Tür. Das Backend implementiert denselben Vertrag.

## Entscheidung

v1 ist HTTP JSON unter `/api/v1`. Die normative Form steht nur in `docs/api/openapi.yaml`.

- Eine Sitzung bindet ein Gebäude. Geometrie wird aus der Sitzung gelesen.
- Grundriss, Ortssuche und Route sind deterministisch und gehen nicht über das Modell.
- Natürliche Sprache geht nur an `POST /sessions/{session_id}/messages`. `understood` und `effects` sagen der Oberfläche, was sie zeichnet.
- Gebäudeänderungen laufen nur über eine ausstehende Aktion: `actions`, dann `confirmations` oder `cancellations`. Vor der Bestätigung ändern sich `closed_ids` und die Öffnungen nicht.
- Eine unmögliche Route ist eine erfolgreiche Berechnung: `reachable: false`, HTTP 201.
- Die Polylinie kommt vom Server, pro Etage, in Metern, y nach oben.
- Schreibende `POST`s brauchen `Idempotency-Key`. Erfolgreiche 2xx werden 24 Stunden dedupliziert.
- Das Fehlerpaket ist flach: `code`, `message`, `trace_id`, `details`.

## Folgen

- Das Frontend zeichnet aus `docs/api/examples/`. Das Backend kann deterministische Endpunkte mit `starter_agent` bauen und das Modell nur an messages hängen.
- Die Sitzung hat Zustand: revision, Schließmenge, ausstehende Aktionen, Idempotenz.
- v1 deckt kein Gebäude aus einem Plan, keinen Campus und kein Streaming ab. Das sind neue Endpunkte oder optionale Felder.
- Uneinigkeit ändert den Vertrag, nicht still ein Pflichtfeld in einer Implementierung.

## Verworfene Alternativen

- Verschachteltes `{ "error": { "code" } }`: widerspricht dem flachen Fehlerpaket.
- Frontend liest `building.json` direkt: neue Türen und Schließungen haben dann keine gemeinsame Quelle.
- Polylinie nur in der Nachricht: ein Refresh müsste den Dialog wiederholen.
- Unerreichbar als 409: die Oberfläche würde „kein Weg“ als fehlgeschlagenen Request zeichnen.
