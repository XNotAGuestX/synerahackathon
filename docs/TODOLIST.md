# TODOLIST – hackathon-synera / Wayfinder

**Stand:** 2026-10-24  
**Arbeitszweig:** `feature/wayfinder-frontend`  
**Autoritative Frontend-Planung:** `docs/FRONTEND_IMPLEMENTATION_PLAN.md`  
**Autoritativer API-Vertrag:** `docs/api/openapi.yaml`  

Dieses Dokument bündelt die verstreuten Frontend-, API- und Produktaufgaben. Statuswerte:

- `[x]` erledigt und im aktuellen Entwicklungsstand vorhanden
- `[~]` begonnen, aber noch nicht vollständig verifiziert
- `[ ]` offen

Prioritäten: **P0** blockiert die MVP-Abnahme, **P1** erforderlich für die vollständige Navigation, **P2** verbessert Robustheit und Demoqualität, **P3** optionaler Ausbau.

## P0 – MVP-Abnahme und reale Navigationskette

- [ ] **NAV-01 Route here:** Suchergebnis in ein `RouteRequest` umwandeln und `gateway.createRoute()` aufrufen. Ergebnis in Route Tape und Guide übernehmen.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/api/gateway.ts`, `frontend/src/domain/presentation.ts`
- [ ] **NAV-02 Step-free preference:** sichtbaren, persistenten Toggle hinzufügen und an `PUT /api/v1/sessions/{session_id}/preferences` anbinden.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/api/gateway.ts`, `frontend/src/features/guide/GuidePanel.tsx`
- [ ] **API-01 HTTP Contract Smoke:** echte Antworten für buildings, sessions, floors, plan, places, routes, messages und actions gegen `/api/v1` prüfen.
  - Dateien: `frontend/src/api/gateway.ts`, `docs/api/examples/`, `docs/api/openapi.yaml`
- [ ] **API-02 Error Envelope:** `error_code`, `message`, `trace_id` und `X-Request-Id` in UI-Zustände abbilden.
  - Dateien: `frontend/src/api/gateway.ts`, `frontend/src/app/App.tsx`
- [ ] **QA-01 Build and smoke:** Build, Start, Route, Clarify, Unreachable und Pending Action automatisiert prüfen.
  - Dateien: `frontend/package.json`, `frontend/tests/` oder `frontend/e2e/`

## P1 – Erforderliche Produktfunktionen

- [x] **DATA-01 Fixture gateway:** gemeinsame `BuildingGateway`-Schnittstelle und Fixture-Implementierung.
  - Dateien: `frontend/src/api/gateway.ts`, `frontend/src/api/fixtures.ts`
- [x] **DATA-02 HTTP gateway:** HTTP-Implementierung mit `VITE_DATA_MODE` und `VITE_API_BASE_URL`.
  - Dateien: `frontend/src/api/gateway.ts`, `frontend/.env.example`
- [x] **DATA-03 Session/Floors/Plans:** Session öffnen und floors/plans asynchron laden.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/api/gateway.ts`
- [x] **BUILD-01 Building Picker:** Gebäude über `gateway.listBuildings()` laden und auswählen.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/styles.css`
- [x] **PLACE-01 Places Search:** Räume und Geräte suchen, Etage fokussieren und Ziel markieren.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/api/gateway.ts`, `frontend/src/styles.css`
- [~] **SESSION-01 Reload recovery:** Session wird erstellt; Wiederherstellung von `last_route_id`, `pending_action_id`, `revision` und `step_free` fehlt noch.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/api/gateway.ts`
- [~] **ACTION-01 Confirm/Cancel:** Gateway-Aufrufe existieren; `building_patched`, revision refresh und Plan-Neuladen fehlen noch.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/domain/presentation.ts`, `frontend/src/api/gateway.ts`
- [~] **EFFECT-01 Declarative effects:** zentrale Effects werden verarbeitet; vollständige Regression für alle bekannten Effect-Typen fehlt.
  - Dateien: `frontend/src/domain/presentation.ts`, `frontend/src/rendering/PlanCanvas.tsx`

## P2 – UX-, Accessibility- und Demoqualität

- [x] **UX-01 Responsive shell:** Desktop, Tablet, Mobile, `viewport-fit` und 320px-Schutz.
  - Dateien: `frontend/index.html`, `frontend/src/styles.css`
- [x] **UX-02 Reduced motion:** Route Animation wird bei `prefers-reduced-motion` deaktiviert.
  - Dateien: `frontend/src/styles.css`
- [x] **UX-03 English i18n base:** englische UI-Schlüssel und spätere Locale-Erweiterung vorbereitet.
  - Dateien: `frontend/src/i18n/en.ts`, `docs/FRONTEND_IMPLEMENTATION_PLAN.md`
- [~] **A11Y-01 Keyboard/WCAG:** sichtbare Focus-Zustände und Status-Rollen vorhanden; Axe-Prüfung und vollständiger Keyboard-Flow fehlen.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/features/guide/GuidePanel.tsx`, `frontend/src/styles.css`
- [ ] **QA-02 Playwright:** Screenshots und Verhalten bei 320, 390, 768, 1024 und 1440px prüfen.
  - Dateien: `frontend/e2e/`, `frontend/package.json`
- [ ] **QA-03 Empty/loading/error states:** gezielte UI-Zustände für leere Suche, Session-Fehler, Plan-Laden und API-Ausfall.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/styles.css`
- [ ] **DEMO-01 Demo script:** fünfminütiger Ablauf für locate, route, clarify, closure und unreachable.
  - Dateien: `docs/DEMO_SCRIPT.md`

## P3 – Optionaler Ausbau

- [ ] **3D-01 Three.js floor stack:** optionale Etagenexplosion auf Basis echter elevations und route legs.
  - Dateien: `frontend/src/rendering/floor-stack-3d/`
- [ ] **VOICE-01 Voice boundary:** `input_mode: transcript` vorbereiten, ohne Speech API als MVP-Abhängigkeit.
  - Dateien: `frontend/src/api/gateway.ts`, `frontend/src/features/guide/GuidePanel.tsx`
- [ ] **BUILD-02 Plan ingestion UI:** neue Grundrisse aufnehmen, validieren und Korrekturen anzeigen.
  - Dateien: `frontend/src/features/building-ingestion/`, `docs/`

## Backend- und Benchmark-Spur

Diese Aufgaben sind nicht durch die React-Oberfläche erledigt und müssen parallel verfolgt werden.

- [ ] **BENCH-01** Neun scored question kinds in `final_agent` mit deterministischen Tools abdecken.
- [ ] **BENCH-02** Area, door width, reachability, adjacency, what-if door, stacked rooms und 3D distance verifizieren.
- [ ] **BENCH-03** Dev benchmark mit `benchmark.evaluate` und per-kind Auswertung ausführen.
- [ ] **BENCH-04** Sunday benchmark command und `BENCHMARK.md` vorbereiten.
- [ ] **CORE-01** Sicherstellen, dass der produktive Agent keine `starter_agent`-Imports verwendet.
- [ ] **CORE-02** API-Backend für `/api/v1` implementieren und mit OpenAPI/Fixtures validieren.
- [ ] **CORE-03** Fehler-, Revision- und Idempotency-Verhalten des Backends testen.

## Dateien nach Verantwortungsbereich

| Bereich | Dateien |
|---|---|
| Produkt- und Frontend-Planung | `docs/WEB_PRODUCT_PLAN.md`, `docs/FRONTEND_IMPLEMENTATION_PLAN.md`, `docs/TODOLIST.md` |
| API-Vertrag und Beispiele | `docs/api/openapi.yaml`, `docs/api/README.md`, `docs/api/examples/` |
| React-Einstieg | `frontend/src/main.tsx`, `frontend/src/app/App.tsx` |
| Datenzugriff | `frontend/src/api/gateway.ts`, `frontend/src/api/fixtures.ts` |
| Fachliche Präsentation | `frontend/src/domain/types.ts`, `frontend/src/domain/presentation.ts` |
| Guide und Status | `frontend/src/features/guide/GuidePanel.tsx`, `frontend/src/features/debug/DebugPanel.tsx` |
| Rendering | `frontend/src/rendering/PlanCanvas.tsx`, `frontend/src/styles.css` |
| Lokale Konfiguration | `frontend/.env.example`, `frontend/package.json`, `frontend/vite.config.ts` |
| Agent/Benchmark | `final_agent/`, `benchmark/`, `tests/`, `BACKLOG.md` |

## Empfohlene Reihenfolge

1. `NAV-01 Route here`
2. `NAV-02 Step-free preference`
3. `API-01` und `API-02` gegen echte `/api/v1`-Antworten
4. `ACTION-01` Revision refresh und `SESSION-01` Reload recovery
5. `QA-01`, `QA-02`, `QA-03` automatisierte und responsive Prüfung
6. `DEMO-01` Demo-Skript
7. P3 Three.js/Voice erst nach stabiler 2D-Navigation
8. Parallel: `BENCH-*` und `CORE-*` für die eigentliche Hackathon-Bewertung

## Definition of Done für den Frontend-MVP

- Ein Nutzer kann ein Gebäude wählen, eine Session öffnen, einen Ort suchen und über **Route here** eine echte Route erhalten.
- Natürliche Sprache, Suchergebnis und Clarify-Flow verwenden denselben Presentation-State.
- Step-free kann aktiviert werden und beeinflusst die API-Anfrage.
- API-Fehler, leere Suche, loading und unreachable sind verständlich dargestellt.
- Fixtures und echtes `/api/v1` verwenden denselben Gateway-Vertrag.
- Die UI funktioniert bei 320px, 390px, 768px, 1024px und 1440px ohne horizontale Überbreite.
- Playwright-Smoke und Accessibility-Prüfung laufen erfolgreich.