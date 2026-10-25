# Changelog

Versionen des Andockvertrags.

## Unreleased

- Notfallmodus (FR-17, ADR-0004): acht additive Operationen unter `Emergency`, Header `X-Admin-Token`, Codes `10003_admin_disabled`, `30019`, `30020`, `30022`. Beispiele `admin-token`, `emergency-status`, `emergency-roster`.
- Vor der Veröffentlichung geändert: `create_emergency_challenge` und `30021_challenge_invalid` aus Commit `d960441` entfallen, `30021` bleibt reserviert. `PUT .../emergency` nimmt nur noch ein optionales `reason`. `list_emergency_people` ist während des Alarms öffentlich.
- Beispielgrundriss für Etage 1: `docs/api/examples/floor-plan-f1.json`. Der v1-Vertrag bleibt unverändert.

## 1.0.0 — 2026-10-24

- `/api/v1` eingefroren (`docs/api/openapi.yaml`). Teamdokumente sind Deutsch.
- Beispielantworten aus dem dev-Datensatz, inklusive unerreichbarer Route, unbestätigter Schließung und Grundriss nach der Bestätigung.
- Fehlt `preferences` beim Anlegen einer Sitzung, ist `step_free` false.
