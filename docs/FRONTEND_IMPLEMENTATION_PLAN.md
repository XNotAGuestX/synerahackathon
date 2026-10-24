# Frontend-Implementierungsplan

**Projekt:** `hackathon-synera`  
**Produkt:** `Wayfinder`  
**Status:** Freigegeben für die MVP-Implementierung  
**Datum:** 2026-10-24  
**Oberflächensprache:** Englisch; Internationalisierung ist vorbereitet.

## 1. Ziel

Das MVP liefert eine benutzbare React-Oberfläche für die Navigation in Innenräumen. Ein Nutzer wählt ein Gebäude, öffnet eine Sitzung, sucht einen Ort oder formuliert ein Ziel in natürlicher Sprache und erhält eine verständliche, visuell nachvollziehbare Route.

Die Oberfläche ist eine Darstellungsschicht über dem bestehenden Vertrag `/api/v1`. Sie berechnet keine Routen, verändert keine Gebäudedaten ohne Bestätigung und führt keine zweite Datenquelle neben OpenAPI ein.

## 2. Bereits umgesetzt

- [x] React-, TypeScript- und Vite-Grundgerüst.
- [x] Englische UI-Texte mit vorbereiteter Internationalisierung.
- [x] Fixture-Gateway und HTTP-Gateway mit gemeinsamer `BuildingGateway`-Schnittstelle.
- [x] Session-Eröffnung über Gateway.
- [x] Etagenindex und Grundrisse werden asynchron über Gateway geladen.
- [x] 2D-SVG-Grundriss mit Räumen, Assets, Markierungen und Route Tape.
- [x] Route-Darstellung mit Distanz, Directions, Start und Ziel.
- [x] Guide-Panel mit natürlicher Sprache und Rückfragen.
- [x] Zustände für akzeptierte Route, Clarify, Unreachable und Pending Action.
- [x] Confirm/Cancel-Aufrufe für ausstehende Aktionen.
- [x] Building Picker über `gateway.listBuildings()`.
- [x] Places Search über `gateway.searchPlaces()`.
- [x] Suchergebnis fokussiert die passende Etage und markiert das Ziel.
- [x] Responsive Layout für Desktop, Tablet und mobile Geräte.
- [x] `viewport-fit`, Reduced Motion, sichtbare Focus-Zustände und Touch-Zielgrößen.
- [x] `VITE_DATA_MODE` und `VITE_API_BASE_URL`.
- [x] Produktions-Build mit `npm run build`.

## 3. Architektur

```text
src/
  app/              App-Shell und globale Fehlergrenze
  api/              OpenAPI-Client und Fixture-Gateway
  domain/           Typen und Presentation-Modelle
  features/         Guide, Debug und spätere Änderungen
  rendering/        2D-Grundriss und spätere 3D-Erweiterung
  i18n/             UI-Locale-Schlüssel
```

Die Abhängigkeiten zeigen nach innen: UI-Features verwenden Gateway und Domänentypen; Domäne und Datenadapter importieren keine UI-Komponenten. Der Renderer verarbeitet deklarative Planobjekte und ignoriert unbekannte Effect-Typen sicher.

## 4. API-Abbildung

| `/api/v1`-Ressource | Frontend-Verwendung |
|---|---|
| `buildings` | Building Picker |
| `sessions` | Session-Start und Sitzungskontext |
| `floors` | Etagenleiste und Etagenwechsel |
| `plan` | Räume, Öffnungen, Assets und Connectoren |
| `places` | Suche und Zielauswahl |
| `routes` | Route Tape, Distanz und Directions |
| `messages` | Guide-Antwort, Verständnis und Rückfragen |
| `actions` | Vorschau, Bestätigung und Abbruch |

Fixtures stammen aus `docs/api/examples/` und werden nicht manuell verändert. Der Adapter muss später ohne Änderungen an den UI-Features gegen HTTP austauschbar sein.

## 5. Offene Implementierung

### P0 – Navigationskette

- [ ] Suchergebnis mit **Route here** verbinden und `gateway.createRoute()` aufrufen.
- [ ] Step-free-Präferenz als persistenten Toggle anzeigen und über die API speichern.
- [ ] HTTP-Contract-Smoke gegen alle relevanten `/api/v1`-Ressourcen ausführen.
- [ ] Fehlerhülle mit `error_code`, `message`, `trace_id` und `X-Request-Id` anzeigen.

### P1 – Sitzungs- und Änderungszustände

- [ ] Reload-Recovery für `last_route_id`, `pending_action_id`, `revision` und `step_free`.
- [ ] `building_patched` verarbeiten und betroffene Grundrisse neu laden.
- [ ] Revision-Konflikte und abgelaufene Aktionen behandeln.
- [ ] Nach bestätigter Änderung Route und geschlossene Connectoren neu darstellen.

### P2 – Qualität und Abnahme

- [ ] Playwright-Smoke-Tests für Start, Route, Clarify, Unreachable und Pending Action.
- [ ] Axe-WCAG-Prüfung.
- [ ] Prüfung bei 320, 390, 768, 1024 und 1440 Pixeln.
- [ ] Explizite Loading-, Empty-, Error- und API-unavailable-Zustände.
- [ ] Demo-Skript für Locate, Route, Clarify, Closure und Unreachable.

### P3 – Optionale Erweiterungen

- [ ] Three.js-Etagenstapel mit echten Höhen und Route-Legs.
- [ ] Voice-ready `input_mode: transcript`.
- [ ] UI für Planimport, Validierung und Korrektur.

## 6. Technische Regeln

- Keine clientseitige Routenberechnung.
- Keine Gebäudedatenänderung ohne explizite Bestätigung.
- `length_m` wird nicht im Frontend neu berechnet.
- Fixtures und HTTP verwenden denselben Gateway-Vertrag.
- UI-Texte werden über Locale-Schlüssel geführt.
- Unbekannte `effects[].type` dürfen die restliche Antwort nicht beschädigen.
- Der 2D-Grundriss bleibt die zuverlässige Hauptansicht; Three.js ist progressive enhancement.

## 7. Definition of Done

- Ein Nutzer kann ein Gebäude wählen, eine Session öffnen, einen Ort suchen und über **Route here** eine echte Route erhalten.
- Natürliche Sprache und Suchergebnisse verwenden denselben Presentation-State.
- Step-free kann aktiviert werden und beeinflusst die API-Anfrage.
- Loading, leere Suche, API-Fehler und unreachable sind verständlich dargestellt.
- Fixture- und HTTP-Modus verwenden denselben Gateway-Vertrag.
- Die UI funktioniert bei 320, 390, 768, 1024 und 1440 Pixeln ohne horizontale Überbreite.
- Build, Playwright-Smoke und Accessibility-Prüfung laufen erfolgreich.