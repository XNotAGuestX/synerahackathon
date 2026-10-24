# HTTP API v1

Die normative Wire-Form ist [openapi.yaml](openapi.yaml). Semantik, Fehlercodes und Idempotenz stehen in [../DESIGN.md](../DESIGN.md). Die Entscheidung steht in [../adr/ADR-0001-http-session-contract.md](../adr/ADR-0001-http-session-contract.md).

```bash
npx @redocly/cli preview-docs docs/api/openapi.yaml
```

## Mock

Die Beispiele kommen aus dem Datensatz. Nicht von Hand ändern.

```bash
uv run python scripts/generate_api_fixtures.py
uv run --with pyyaml --with jsonschema --with referencing python scripts/validate_api_fixtures.py
```

Standardgebäude: `data/dev/proc-factory-dev-003` (Fertigung Ost 27).

| Aufruf | Datei |
|---|---|
| `GET /api/v1/buildings?split=dev&limit=20` | `examples/buildings-page.json` |
| `next_cursor` der vorigen Datei | `examples/buildings-page-2.json`, nur wenn `has_more` |
| `GET /api/v1/buildings/proc-factory-dev-003` | `examples/building-detail.json` |
| `POST /api/v1/sessions` und `GET /api/v1/sessions/{id}` | `examples/session.json` |
| `GET /api/v1/sessions/{id}/floors` | `examples/floor-index.json` |
| `GET .../floors/proc-factory-dev-003-F0/plan` | `examples/floor-plan.json` |
| Dieselbe Etage nach bestätigtem Schließen | `examples/floor-plan-closed.json` |
| `GET /api/v1/health` | `examples/health.json` |
| `GET .../places?q=cnc` | `examples/places-page.json` |
| `POST .../routes`, erreichbar | `examples/route.json` |
| `POST .../routes`, Aufzug zu, ohne Stufen | `examples/route-unreachable.json` |
| `POST .../messages`, Eingang zum CNC, ohne Stufen | `examples/message-accepted.json` |
| `POST .../messages`, mehrdeutige Suche | `examples/message-clarify.json` |
| `POST .../messages`, Aufzug schließen, noch nicht bestätigt | `examples/message-pending-action.json` |
| `GET .../messages` | `examples/message-page.json` |
| `POST .../actions`, Büroaufzug schließen | `examples/action-pending.json` |
| `POST .../actions/{id}/confirmations` | `examples/action-confirmed.json` |
| Validierung fehlgeschlagen | `examples/error-validation.json` |
| Ort mehrdeutig | `examples/error-ambiguous.json` |

Sitzungs-, Nachrichten-, Routen- und Aktions-IDs sind feste UUIDs. Beispiel-`Idempotency-Key` für die Route-Nachricht: `fixture-message-route`. Bestätigen nutzt `fixture-confirm-lift`.

Ein UI-Test kann diese JSON-Dateien zurückgeben. Weicht ein Feldname von OpenAPI ab, gilt OpenAPI. Danach das Skript neu laufen lassen.
