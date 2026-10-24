# TODOLIST – hackathon-synera / Wayfinder

**Stand:** 2026-10-24, offene Frontend-Lücken nach Codeprüfung ergänzt  
**Arbeitszweig:** `feature/wayfinder-frontend`  
**Autoritative Frontend-Planung:** `docs/FRONTEND_IMPLEMENTATION_PLAN.md`  
**Autoritativer API-Vertrag:** `docs/api/openapi.yaml`  

Dieses Dokument bündelt die verstreuten Frontend-, API- und Produktaufgaben. Statuswerte:

- `[x]` erledigt und im aktuellen Entwicklungsstand vorhanden
- `[~]` begonnen, aber noch nicht vollständig verifiziert
- `[ ]` offen

Prioritäten: **P0** blockiert die MVP-Abnahme, **P1** erforderlich für die vollständige Navigation, **P2** verbessert Robustheit und Demoqualität, **P3** optionaler Ausbau.

## P0 – MVP-Abnahme und reale Navigationskette

- [x] **NAV-01 Route here:** Suchergebnis in ein `RouteRequest` umwandeln und `gateway.createRoute()` aufrufen. Ergebnis in Route Tape und Guide übernehmen.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/api/gateway.ts`, `frontend/src/domain/presentation.ts`
- [x] **NAV-02 Step-free preference:** sichtbaren, persistenten Toggle hinzufügen und an `PUT /api/v1/sessions/{session_id}/preferences` anbinden.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/api/gateway.ts`, `frontend/src/features/guide/GuidePanel.tsx`
- [x] **API-01 HTTP Contract Smoke:** echte Antworten für buildings, sessions, floors, plan, places, routes, messages und actions gegen `/api/v1` prüfen.
  - Dateien: `frontend/src/api/gateway.ts`, `docs/api/examples/`, `docs/api/openapi.yaml`
- [x] **API-02 Error Envelope:** `error_code`, `message`, `trace_id` und `X-Request-Id` in UI-Zustände abbilden.
  - Dateien: `frontend/src/api/gateway.ts`, `frontend/src/app/App.tsx`
- [x] **QA-01 Build and smoke:** Build, Start, Route, Clarify, Unreachable und Pending Action automatisiert prüfen.
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
- [x] **SESSION-01 Reload recovery:** Session wird erstellt; Wiederherstellung von `last_route_id`, `pending_action_id`, `revision` und `step_free` fehlt noch.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/api/gateway.ts`
- [x] **ACTION-01 Confirm/Cancel:** Gateway-Aufrufe existieren; `building_patched`, revision refresh und Plan-Neuladen fehlen noch.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/domain/presentation.ts`, `frontend/src/api/gateway.ts`
- [x] **EFFECT-01 Declarative effects:** zentrale Effects werden verarbeitet; vollständige Regression für alle bekannten Effect-Typen fehlt.
  - Dateien: `frontend/src/domain/presentation.ts`, `frontend/src/rendering/PlanCanvas.tsx`

## P1 – Wichtig: Discovery und Karteninteraktion

- [x] **DISCOVERY-01 Kategorie-basierte Ortssuche:** Im Standardzustand keine zufälligen Gebäude/Orte anzeigen. Aus dem aktiven Datensatz alle vorhandenen Asset-/Raumkategorien als große Kategorien anzeigen; ein Klick auf eine Kategorie öffnet die nächste Filterstufe, z. B. `Getränke/Lebensmittel` → `Wasserspender`, `Kaffeemaschine`, `Automat`. **Done:** Kategorien und Unterkategorien werden ausschließlich aus den geladenen Gebäudedaten abgeleitet, leere Kategorien werden nicht angezeigt und die Auswahl führt zu einer begrenzten Ergebnisliste.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/api/gateway.ts`, `frontend/src/api/fixtures.ts`, `frontend/src/domain/types.ts`, `frontend/src/styles.css`
- [x] **MAP-01 Interne Kartenzoom-Steuerung:** Minus-/Plus-Steuerung und sichtbarer Zoomstatus direkt in der Karte ergänzen. Zoom darf die Interaktion kleiner Räume und Komponenten nicht verschieben oder unbrauchbar machen; Tastaturbedienung und `prefers-reduced-motion` berücksichtigen. **Done:** Zoom funktioniert auf Desktop und Mobile, bleibt innerhalb sinnvoller Grenzen und unterstützt Zurücksetzen auf 100 %.
  - Dateien: `frontend/src/rendering/PlanCanvas.tsx`, `frontend/src/app/App.tsx`, `frontend/src/styles.css`
- [x] **MAP-02 Karten-Pan:** Die Karte frei per Drag/Pan verschiebbar machen, ohne Auswahl- und Focus-Events zu verschlucken. **Done:** Drag funktioniert mit Maus und Touch/Pointer, Klick auf Raum/Gerät bleibt möglich und die Ansicht kann auf den Ausgangszustand zurückgesetzt werden.
  - Dateien: `frontend/src/rendering/PlanCanvas.tsx`, `frontend/src/app/App.tsx`, `frontend/src/styles.css`
- [x] **DEBUG-01 Nicht-verdeckendes Debug-Panel:** Debug-Ausgabe darf keine Kartenposition dauerhaft verdecken. Panel als verschiebbares, einklappbares oder außerhalb der Karte liegendes Werkzeug organisieren und bei kleinen Viewports in eine nicht-blockierende Ansicht wechseln. **Done:** Alle Kartenbereiche bleiben erreichbar; Debug-Funktionen und Auswahlinformationen bleiben erhalten.
  - Dateien: `frontend/src/features/debug/DebugPanel.tsx`, `frontend/src/app/App.tsx`, `frontend/src/styles.css`
- [x] **THEME-01 Vollständige Theme-Abdeckung:** Alle UI-Komponenten müssen die semantischen Light/Dark/System-Token verwenden; insbesondere `ask-block`, Debug-Panel, Notices, Suchergebnisse, Auswahlzustände und Kartensteuerung dürfen keine festen Light-Only-Farben enthalten. **Done:** Light, Dark und System werden bei 320/768/1440 px ohne unlesbare Kontraste oder harte helle Flächen geprüft.
  - Dateien: `frontend/src/styles.css`, `frontend/src/features/guide/GuidePanel.tsx`, `frontend/src/features/debug/DebugPanel.tsx`, `frontend/src/app/App.tsx`
## P2 – UX-, Accessibility- und Demoqualität

- [x] **UX-01 Responsive shell:** Desktop, Tablet, Mobile, `viewport-fit` und 320px-Schutz.
  - Dateien: `frontend/index.html`, `frontend/src/styles.css`
- [x] **UX-02 Reduced motion:** Route Animation wird bei `prefers-reduced-motion` deaktiviert.
  - Dateien: `frontend/src/styles.css`
- [x] **UX-03 English i18n base:** englische UI-Schlüssel und spätere Locale-Erweiterung vorbereitet.
  - Dateien: `frontend/src/i18n/en.ts`, `docs/FRONTEND_IMPLEMENTATION_PLAN.md`
- [x] **A11Y-01 Keyboard/WCAG:** sichtbare Focus-Zustände und Status-Rollen vorhanden; Axe-Prüfung und vollständiger Keyboard-Flow fehlen.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/features/guide/GuidePanel.tsx`, `frontend/src/styles.css`
- [x] **QA-02 Playwright:** Screenshots und Verhalten bei 320, 390, 768, 1024 und 1440px prüfen.
  - Dateien: `frontend/e2e/`, `frontend/package.json`
- [x] **QA-03 Empty/loading/error states:** gezielte UI-Zustände für leere Suche, Session-Fehler, Plan-Laden und API-Ausfall.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/styles.css`
- [x] **DEMO-01 Demo script:** fünfminütiger Ablauf für locate, route, clarify, closure und unreachable.
  - Dateien: `docs/DEMO_SCRIPT.md`

## P3 – Optionaler Ausbau

- [x] **3D-01 Three.js floor stack:** optionale Etagenexplosion auf Basis echter elevations und route legs.
  - Dateien: `frontend/src/rendering/floor-stack-3d/`
- [x] **VOICE-01 Voice boundary:** `input_mode: transcript` vorbereiten, ohne Speech API als MVP-Abhängigkeit.
  - Dateien: `frontend/src/api/gateway.ts`, `frontend/src/features/guide/GuidePanel.tsx`
- [x] **BUILD-02 Plan ingestion UI:** neue Grundrisse aufnehmen, validieren und Korrekturen anzeigen.
  - Dateien: `frontend/src/features/building-ingestion/`, `docs/`

## P1 – Interaktion nach BACKLOG L1–L4

Diese Punkte entsprechen den Frontend-Anteilen von L1-01, L1-03, L1-04, L2-02, L2-03, L3-01, L3-02 und L4-01. Geometrie und der Live-Agent bleiben außerhalb dieser Liste.

- [x] **CTX-01 Aktueller Ort:** „I am at …“ setzt nur den Standort, zeichnet keine Route und bleibt für **Route here** erhalten.
  - Dateien: `frontend/src/api/interpret.ts`, `frontend/src/app/App.tsx`, `frontend/src/features/guide/GuidePanel.tsx`
- [x] **CTX-02 Keine erfundene Route:** unbekannte Sätze und „9.99“ bleiben ohne Route Tape. Mehrdeutige Namen fragen nach.
  - Dateien: `frontend/src/api/interpret.ts`, `frontend/src/api/gateway.ts`
- [x] **CTX-03 Schließen und wieder öffnen:** bestätigtes Schließen kann über **Reopen** zurückgenommen werden. Die Karte nutzt die bestätigten `closed_ids`.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/api/gateway.ts`, `frontend/src/features/guide/GuidePanel.tsx`
- [x] **CTX-04 Tour und Etagenwechsel:** `via` und mehrteilige `legs` zeigen Stopps und einen Etagenwechsel, der die passende Etage öffnet.
  - Dateien: `frontend/src/features/guide/GuidePanel.tsx`
- [x] **CTX-05 Gebäudewechsel:** ein anderes Gebäude löscht Plan, Auswahl und Route. Gleiche Raumnummern werden nicht aus dem vorigen Gebäude gezeigt.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/api/gateway.ts`
- [x] **CTX-06 Kalibrierung:** Bild und PDF zeichnen keine Räume. Die Oberfläche verlangt Breite und Höhenlage, bevor Geometrie entstehen kann.
  - Dateien: `frontend/src/features/building-ingestion/PlanImport.tsx`

## P1 – BACKLOG-Folge für die Oberfläche

- [x] **L1-04 Folge:** Standort, Zielwechsel und Step-free bleiben über die nächste Frage erhalten. Spätere Routen nutzen diese Präferenz.
- [x] **L2-02 Folge:** ein benanntes Element kann geschlossen und wieder geöffnet werden. Eine gekreuzte Route wird nicht durch eine erfundene Ersatzroute ersetzt.
- [x] **L2-03 Folge:** eine Tour behält die genannte Reihenfolge. Ohne gespeicherte Mehrpunktroute wird keine Distanz angezeigt.
- [x] **L3-02 Folge:** die gewählte Gebäude-ID bleibt lokal erhalten. Ortsoptionen nennen das Gebäude.
- [x] **L4-01 Folge:** ein Bild zeigt die Prüfrechnung „1 m = N px“. Es entstehen daraus keine Räume.
  - Dateien: `frontend/src/api/interpret.ts`, `frontend/src/app/App.tsx`, `frontend/src/features/building-ingestion/PlanImport.tsx`, `docs/INTERACTION_SCRIPT.md`

## P1 – Route as a story

Entspricht dem genehmigten Erlebnis in `docs/WEB_PRODUCT_PLAN.md`: die Route wird schrittweise erzählt, nicht nur als fertige Linie gezeichnet.

- [x] **STORY-01 Schrittweise Route:** die Tape zeigt nur den Abschnitt bis zur aktuellen Anweisung. Play/Pause läuft die Schritte ab; reduzierte Bewegung startet kein automatisches Weiterschalten.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/rendering/PlanCanvas.tsx`
- [x] **STORY-02 Etagenübergang:** endet der sichtbare Abschnitt vor einem Wechsel, liegt ein Verbindungs-Marker auf dem Plan. Die nächste Etage öffnet sich mit dem Schritt.
  - Dateien: `frontend/src/rendering/PlanCanvas.tsx`, `frontend/src/features/guide/GuidePanel.tsx`

## P0 – Fehlende BACKLOG-Anbindung L1–L4

Die bisherigen CTX-Punkte sind die Fixture-Oberfläche. Diese Liste schließt die Lücken, indem dieselbe Oberfläche berechnete Session-Antworten zeichnet. Das Frontend rechnet keine Route.

- [x] **GAP-01 L1-01 Gespräch:** jede Eingabe geht an die Session-API. Die Antwort kommt aus den Gebäudedaten. Der Guide zeigt Text, `effects` und die passende Etage.
- [x] **GAP-02 L1-02 Treffer:** ein Treffer wird auf der richtigen Etage markiert. Mehr als 15 Treffer können weitergeblättert werden.
- [x] **GAP-03 L1-03 Mehrdeutig:** ein Name mit mehreren Treffern stellt eine Frage. „9.99“ erzeugt keinen Ort und keine Route.
- [x] **GAP-04 L1-04 Kontext:** Standort, Ziel, Gebäude und Step-free bleiben in der Session. „instead“ ändert nur das Ziel.
- [x] **GAP-05 L2-01 Route:** Route here und Sätze liefern Länge, Richtungen und `legs`. Die Karte zeichnet genau diese `legs`.
- [x] **GAP-06 L2-02 Schließen:** Tür, Raum, Aufzug und Treppe können bestätigt geschlossen und wieder geöffnet werden. Die aktive Route wird neu berechnet oder als unerreichbar erklärt.
- [x] **GAP-07 L2-03 Tour:** die genannte Reihenfolge bleibt. Die Antwort enthält Abschnitte und die summierte Länge, wenn eine Route existiert.
- [x] **GAP-08 L3-01 Etagen:** eine berechnete Route über mehrere Etagen zeigt je Etage ihr Segment und den Verbinder.
- [x] **GAP-09 L3-02 Gebäude:** der Picker lädt ein zweites Gebäude. Raumnummern bleiben an die Gebäude-ID gebunden.
- [x] **GAP-10 L3-03 Übergang:** ein Schritt, der das Gebäude verlässt, wird als eigener Abschnitt gezeigt. Eine fehlende Verbindungsbrücke wird erklärt, nicht erfunden.
- [x] **GAP-11 L4 Prüfung:** ein hochgeladenes JSON wird auf IDs, Koordinaten und Polygone geprüft. Korrekturen sind sichtbar. Bilder bleiben bei der Maßstabsprüfung und erzeugen keine Räume.
  - Dateien: `final_agent/guide_session.py`, `scripts/serve_api.py`, `frontend/src/api/gateway.ts`, `frontend/src/app/App.tsx`, `frontend/src/features/discovery/PlaceDiscovery.tsx`, `frontend/src/features/building-ingestion/PlanImport.tsx`

## P0 – Offene Frontend-Lücken: Fixture hängt an der Live-Sitzung

Codeprüfung von `frontend/src` am 2026-10-24. Die angehakten GAP-, SESSION- und ACTION-Punkte beschreiben die vorhandene Oberfläche. Sie schließen die folgenden Live-Daten-Lücken nicht. Das Frontend rechnet weiterhin keine Route.

- [ ] **LIVE-01 Namen aus der geladenen Session:** `labelFor` und `connectorNote` lesen nur den Fixture-Katalog in `frontend/src/api/fixtures.ts`. In einer anderen Gebäude-Sitzung zeigen „you are at“, Zwischenstopps und Assumption-Details rohe Ids. **Done:** Namen und Verbinder kommen aus dem geladenen Plan oder der Session-Antwort; unbekannte Ids bleiben als Id sichtbar und werden nicht mit Fixture-Namen einer anderen Gebäude-ID beschriftet.
  - Dateien: `frontend/src/api/fixtures.ts`, `frontend/src/app/App.tsx`, `frontend/src/features/guide/GuidePanel.tsx`, `frontend/src/rendering/PlanCanvas.tsx`
- [ ] **LIVE-02 Route here ohne gesetzten Standort:** `routeToPlace` fällt auf `catalog.replies.accepted.routes[0].start_space_id` zurück. Ohne aktuellen Ort startet die Route am Fixture-Lobby, auch in einem anderen Gebäude. **Done:** ohne Standort bleibt die Karte ohne Tape; der Guide fragt nach dem Start. Es wird kein Fixture-Start in eine andere Gebäude-ID eingesetzt.
  - Dateien: `frontend/src/app/App.tsx`
- [ ] **LIVE-03 Bestätigung zeichnet die bestätigte Änderung:** nach Confirm kommen die Karten-Highlights weiter aus `catalog.confirmedEffects`. `closed_ids` kommen aus der Aktion, die Highlight-Flächen nicht. **Done:** Confirm übernimmt Flächen, geschlossene Ids und Revision aus der Aktionsantwort und lädt die betroffenen Pläne neu. Abbrechen lässt den Plan unverändert.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/domain/presentation.ts`
- [ ] **LIVE-04 Debug-Proben überschreiben die Live-Antwort:** die vier Sample-Buttons rufen `loadReply` auf, leeren `liveReply` und zeigen Fixture-Dialoge, auch wenn die API verbunden ist. **Done:** Sample-Buttons sind als Fixture-Vorschau gekennzeichnet und ersetzen eine berechnete Session-Antwort nicht. Eine geladene Probe kann verlassen werden, ohne die Session-Route zu verlieren.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/features/debug/DebugPanel.tsx`
- [ ] **LIVE-05 Rückfrage setzt die Anfrage fort:** `onChoose` schreibt die Option nur in das Eingabefeld. Der Nutzer muss ein zweites Mal senden. **Done:** eine Option wird als nächste Nutzernachricht an `gateway.sendMessage` geschickt. Die Karte übernimmt die daraus entstandene Antwort, ohne eine zweite manuelle Sendung.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/features/guide/GuidePanel.tsx`
- [ ] **LIVE-06 Ausstehende Bestätigung übersteht Reload:** `pendingActionId` wird in `sessionStorage` geschrieben. Beim Öffnen wird nur `last_route_id` wiederhergestellt. Confirm und Cancel fehlen nach dem Neuladen. **Done:** eine gespeicherte pending Action lädt Status, Vorschau und beide Entscheidungen. Eine abgelaufene Action zeigt den Fehlerzustand und keine falsche Bestätigung.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/api/recovery.ts`, `frontend/src/api/gateway.ts`
- [ ] **LIVE-07 Reopen nennt das geschlossene Element:** der Button sendet den festen Satz `Reopen the closed connector` und keine Id. **Done:** Reopen bezieht sich auf die bestätigten `closed_ids` der Session. Die Anfrage nennt das Element. Die Karte zeigt den Zustand nach der neuen Antwort.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/features/guide/GuidePanel.tsx`

## P1 – Angefragte Frontend-Funktionen, im Code noch offen

Diese Punkte stehen in den Teamnotizen. Die aktuelle Oberfläche erfüllt sie nicht.

- [ ] **REQ-01 Fragen ohne Optionen:** `GuidePanel` zeichnet nur Auswahlbuttons. Eine Frage ohne `options` hat darunter kein Eingabefeld. **Done:** bis zu vier Optionen bleiben Buttons und senden direkt. Ohne Optionen erscheint ein Eingabefeld in dem Fragenblock. Die Antwort geht an dieselbe Session-Nachricht.
  - Dateien: `frontend/src/features/guide/GuidePanel.tsx`, `frontend/src/domain/presentation.ts`
- [ ] **REQ-02 Text- und Transcript-Modus unterscheiden die Antwort:** der Schalter sendet nur `input_mode`. Guide-Aufbau und Satzlänge bleiben gleich. **Done:** Transcript zeigt zuerst eine kurze Bestätigung und die nächste Anweisung. Längere Annahmen, Richtungen und Ids bleiben im eingeklappten Details-Block. Textmodus behält die lesbare Annahmenzeile.
  - Dateien: `frontend/src/features/guide/GuidePanel.tsx`, `frontend/src/app/App.tsx`, `frontend/src/i18n/en.ts`
- [ ] **REQ-03 Standort simulieren und Checkpoint auslösen:** es gibt keinen verschiebbaren Standortmarker und keinen Hinweis, wenn der nächste Schritt erreicht ist. **Done:** ein Debug- oder Guide-Steuerelement setzt einen simulierten Standort auf dem Plan. Die Oberfläche sendet diese Position und zeigt die nächste Anweisung, wenn der Marker den aktuellen Schritt erreicht. Ohne Position bleibt die bestehende schrittweise Route bedienbar.
  - Dateien: `frontend/src/app/App.tsx`, `frontend/src/rendering/PlanCanvas.tsx`, `frontend/src/features/debug/DebugPanel.tsx`
- [ ] **REQ-04 Landmarken an der Route und Debug-Maße:** der aktuelle Schritt ist ein Punkt. Nahe Geräte werden nicht größer hervorgehoben. Das Debug-Panel zeigt Name, Id und Etage, aber keine Koordinate und keine Türbreite. **Done:** die aktuelle Anweisung kann nahe, unterscheidbare Geräte größer markieren, wenn die Antwort sie liefert. Die Debug-Auswahl zeigt Koordinate und, bei einer Öffnung, Türbreite und Step-free. Die Hauptansicht bleibt die 2D-Karte.
  - Dateien: `frontend/src/rendering/PlanCanvas.tsx`, `frontend/src/features/debug/DebugPanel.tsx`, `frontend/src/domain/types.ts`
- [ ] **REQ-05 Kategorien über 15 Einträge blättern:** die Textsuche hat More. Ein Typ in der Kategorieansicht nutzt `limitPlaces` und zeigt nur die ersten 15, ohne nächste Seite. **Done:** Kategorie- und Typansicht blättern über 15 Einträge. Die Zählung nennt den sichtbaren Bereich und die Gesamtzahl. Leere Kategorien bleiben ausgeblendet.
  - Dateien: `frontend/src/features/discovery/PlaceDiscovery.tsx`, `frontend/src/domain/discovery.ts`
- [ ] **REQ-06 Import wird eine Gebäude-Sitzung:** ein Bild erzeugt keine Räume und bleibt bei der Maßstabsprüfung. Ein gültiges JSON ersetzt nur den lokalen Plan der aktuellen Etage und öffnet keine neue Session. **Done:** ein gültiges Plan-JSON besteht die sichtbare Prüfung und kann als eigene Gebäude-Sitzung geladen werden. Ein Bild oder PDF erzeugt weiterhin keine erfundenen Räume, solange nur Maßstab und Höhenlage vorliegen.
  - Dateien: `frontend/src/features/building-ingestion/PlanImport.tsx`, `frontend/src/app/App.tsx`, `frontend/src/api/gateway.ts`

## P2 – Frontend-Prüfung deckt die Live-Lücken nicht

- [ ] **QA-04 Smoke über die Fixture-Proben hinaus:** `frontend/e2e/smoke.py` klickt die Debug-Proben für Clarify, Unreachable und Pending. Gebäudewechsel, Route here ohne Standort, Bestätigung in einer berechneten Session und der HTTP-Gateway sind nicht abgedeckt. **Done:** ein Smoke-Lauf prüft diese vier Fälle und bleibt bei 320, 390, 768, 1024 und 1440 px ohne horizontale Überbreite. Ein grüner Lauf der alten Proben gilt nicht als Abschluss von LIVE-01 bis LIVE-07.
  - Dateien: `frontend/e2e/smoke.py`, `frontend/package.json`

## Backend- und Benchmark-Spur

Diese Aufgaben sind nicht durch die React-Oberfläche erledigt und müssen parallel verfolgt werden.

- [x] **BENCH-01** Neun scored question kinds in `final_agent` mit deterministischen Tools abdecken.
- [x] **BENCH-02** Area, door width, reachability, adjacency, what-if door, stacked rooms und 3D distance verifizieren.
- [x] **BENCH-03** Dev benchmark mit `benchmark.evaluate` und per-kind Auswertung ausführen. Live `--per-kind 1` war 0/9, weil das Modell nur grüßte. Der Tool-Adapter beantwortet dieselben neun Arten ohne Modell; lokal 138/138 auf gelabeltem dev.
- [x] **BENCH-04** Sunday benchmark command und `BENCHMARK.md` vorbereiten.
- [x] **CORE-01** Sicherstellen, dass der produktive Agent keine `starter_agent`-Imports verwendet.
- [x] **CORE-02** API-Backend für `/api/v1` implementieren und mit OpenAPI/Fixtures validieren. `scripts/serve_api.py` spielt die Fixtures und die Fehlerhülle.
- [x] **CORE-03** Fehler-, Revision- und Idempotency-Verhalten des Backends testen.

## Dateien nach Verantwortungsbereich

| Bereich | Dateien |
|---|---|
| Produkt- und Frontend-Planung | `docs/WEB_PRODUCT_PLAN.md`, `docs/FRONTEND_IMPLEMENTATION_PLAN.md`, `docs/TODOLIST.md` |
| API-Vertrag und Beispiele | `docs/api/openapi.yaml`, `docs/api/README.md`, `docs/api/examples/` |
| React-Einstieg | `frontend/src/main.tsx`, `frontend/src/app/App.tsx` |
| Datenzugriff | `frontend/src/api/gateway.ts`, `frontend/src/api/fixtures.ts` |
| Fachliche Präsentation | `frontend/src/domain/types.ts`, `frontend/src/domain/presentation.ts` |
| Guide und Status | `frontend/src/features/guide/GuidePanel.tsx`, `frontend/src/features/debug/DebugPanel.tsx` |
| Ortssuche und Import | `frontend/src/features/discovery/PlaceDiscovery.tsx`, `frontend/src/domain/discovery.ts`, `frontend/src/features/building-ingestion/PlanImport.tsx` |
| Sitzungswiederherstellung | `frontend/src/api/recovery.ts` |
| Rendering | `frontend/src/rendering/PlanCanvas.tsx`, `frontend/src/styles.css` |
| Lokale Konfiguration | `frontend/.env.example`, `frontend/package.json`, `frontend/vite.config.ts` |
| Agent/Benchmark | `final_agent/`, `benchmark/`, `tests/`, `BACKLOG.md` |

## Empfohlene Reihenfolge

1. `LIVE-01` bis `LIVE-07`: Fixture-Daten aus der Live-Sitzung lösen
2. `REQ-05` Blättern in Kategorien und `REQ-01` Fragen ohne Optionen
3. `QA-04` Smoke für Gebäudewechsel, Route here und berechnete Bestätigung
4. `REQ-02` bis `REQ-04` und `REQ-06` nach der stabilen Live-Sitzung
5. Bereits angehakte MVP-Punkte nicht erneut öffnen, solange ein LIVE- oder REQ-Punkt sie nicht ausdrücklich wieder aufmacht

## Definition of Done für den Frontend-MVP

- `LIVE-01` bis `LIVE-07` sind offen, bis eine zweite Gebäude-Sitzung ohne Fixture-Namen, Fixture-Start und Fixture-Highlights funktioniert.
- Ein Nutzer kann ein Gebäude wählen, eine Session öffnen, einen Ort suchen und über **Route here** eine echte Route erhalten.
- Natürliche Sprache, Suchergebnis und Clarify-Flow verwenden denselben Presentation-State.
- Step-free kann aktiviert werden und beeinflusst die API-Anfrage.
- API-Fehler, leere Suche, loading und unreachable sind verständlich dargestellt.
- Fixtures und echtes `/api/v1` verwenden denselben Gateway-Vertrag.
- Die UI funktioniert bei 320px, 390px, 768px, 1024px und 1440px ohne horizontale Überbreite.
- Playwright-Smoke und Accessibility-Prüfung laufen erfolgreich.