# CLAUDE.md — Track 01

> Nur projektspezifische Abweichungen. Allgemeine Regeln: software-engineering Playbook. Gestaltung: `docs/DESIGN.md`. Wire-Form: `docs/api/openapi.yaml`.

## Sprache

- Teamdokumente sind Deutsch.
- JSON-Felder, `operationId`, Fehler-`message` und stabile Bezeichner bleiben Englisch. Das ist die Diagnosesprache.
- Das Organizer-Kit (`README.md` Aufgabentext, `ATTRIBUTION.md`, `starter_agent/README.md`) bleibt der englische Originaltext.

## Größenklasse

Stufe B: Hackathon-Team, Demo, Backend-Anbindung.

Ausnahmen, begründet in `docs/DESIGN.md`:

- Metriken und verteilte Traces sind ein Request-Log plus `X-Request-Id`.
- Keine Locale-Dateien in der API. Diagnose-`message` ist Englisch.
- E2E-CI kommt mit dem Frontend. Heute gilt: OpenAPI lässt sich parsen, und `scripts/generate_api_fixtures.py` erzeugt die Beispiele neu.

## Namen

- HTTP + JSON, OpenAPI 3.1, Präfix `/api/v1`.
- JSON-Felder sind `snake_case`. `schemaVersion` aus dem Playbook heißt hier `schema_version`.
- Pfade: Nomen im Plural, `kebab-case`. Keine Verben im Pfad. Bestätigen und Abbrechen sind `confirmations` und `cancellations`.
- Booleans sind JSON-Booleans. Enums sind Strings. Fehlende Werte sind `null`.
- Zeit: RFC 3339 UTC, zum Beispiel `2026-10-24T12:00:00Z`.
- UTF-8 ohne BOM, Zeilenenden LF.
- `operationId` ist `snake_case`.

## Verzeichnisse

- `docs/DESIGN.md` — Semantik und Anforderungsnummern.
- `docs/adr/` — tragende Entscheidungen.
- `docs/api/openapi.yaml` — normative Request- und Response-Form.
- `docs/api/examples/` — erzeugte Mocks. Nicht von Hand ändern.
- `scripts/generate_api_fixtures.py` — erzeugt die Mocks neu.
- `starter_agent/` — Domänenbeispiel des Kits. Die HTTP-Schicht leakt keine Framework-Typen hierhin.
- `ATTRIBUTION.md` bleibt im Wurzelverzeichnis, weil das Kit-README dorthin verlinkt.

## Änderungsmatrix

| Änderung | Mitprüfen |
|---|---|
| Felder, Enums, Statuscodes in `docs/api/openapi.yaml` | `docs/DESIGN.md`, `docs/api/examples/`, Frontend, Backend |
| Fehlercodes | OpenAPI `ErrorCode`, DESIGN-Tabelle, Frontend-Zweige |
| Felder in `building.json` | Floor-plan-Schema, Fixture-Skript |
| Brechende Änderung | Neue ADR und `/api/v2`. v1 nicht still ändern. |
