# Frontend-Implementierungsplan

**Projekt:** `hackathon-synera`  
**Produkt:** `Wayfinder`  
**Status:** Freigegeben für MVP-Implementierung  
**Datum:** 2026-10-24  
**Sprache:** Deutsch für dieses Planungsdokument; die MVP-Oberfläche ist Englisch.

## 1. Ziel

Das MVP liefert eine benutzbare React-Weboberfläche für die Navigation in Innenräumen. Ein Nutzer wählt ein Gebäude, öffnet eine Sitzung, formuliert ein Ziel in natürlicher Sprache und erhält eine verständliche, visuell nachvollziehbare Route.

Die Oberfläche ist eine dünne Darstellungsschicht über dem bestehenden Vertrag `/api/v1`. Sie berechnet keine Routen, verändert keine Gebäudedaten ohne Bestätigung und führt keine zweite Datenquelle neben OpenAPI ein.

## 2. Lieferumfang

### Muss im MVP enthalten sein

- Gebäudewahl mit dem Demo-Gebäude `proc-factory-dev-003`.
- Sitzungsansicht mit Grundriss und Etagenwechsel.
- Suchfeld für Räume und Assets.
- Route-Anzeige mit Start, Ziel, Distanz, Barrierefreiheit und Schrittfolge.
- Route-Tape-Animation mit Reduced-Motion-Fallback.
- Gesprächsbereich für natürliche Sprache.
- Zustände für akzeptierte Route, Rückfrage, unerreichbare Route und ausstehende Änderung.
- Englisch als vollständige UI-Locale.
- Internationalisierungsstruktur mit reservierter `de`-Locale und englischem Fallback.
- Fixture-Modus für lokale Entwicklung ohne Backend.

### Nachrangig

- Three.js-Ansicht als austauschbare, sekundäre Etagen-Explosionsansicht.
- Spracheingabe.
- Authentifizierung und persistente Nutzerkonten.

## 3. Architektur

```text
src/
  app/              App-Shell, Provider, globale Fehlergrenze
  api/              OpenAPI-Client, Fixture-Adapter, Fehlergrenze
  domain/           Typen und reine UI-nahe Modelle
  features/
    building-picker/ Gebäudeauswahl
    navigation/      Karte, Etagen, Route
    guide/           Dialog, Eingabe, Rückfragen
    changes/         Vorschau und Bestätigung
  rendering/         2D-Plan und spätere 3D-Erweiterung
  i18n/              Locale-Verträge und englische Texte
  styles/            Design Tokens und globale Layoutregeln
```

Abhängigkeiten zeigen nach innen: Komponenten greifen auf API-Adapter und Domänentypen zu; Domäne und Datenadapter importieren keine UI-Komponenten. Der Planrenderer verarbeitet deklarative Planobjekte und ignoriert unbekannte `effects[].type` sicher.

## 4. Technische Entscheidungen

- React 18+ mit TypeScript und Vite.
- TanStack Query für Serverzustand und Lade-/Fehlerzustände.
- Kleiner React-Reducer für lokalen Ansichtsstatus; keine Kopie des Serverzustands.
- SVG als erster 2D-Renderer, weil Polygone, Route-Linien, Marker und fokussierbare Beschriftungen direkt kontrollierbar sind.
- Three.js/React Three Fiber nur als progressive Erweiterung.
- Lucide-Icons für Bedienaktionen.
- CSS-Tokens für Farben, Abstände, Typografie, Radius und Bewegung.
- Keine geheimen Werte im Frontend; optionale API-Konfiguration ausschließlich über Vite-Umgebungsvariablen.

## 5. API-Abbildung

| `/api/v1`-Ressource | Frontend-Verwendung |
|---|---|
| `buildings` | Gebäudeauswahl |
| `sessions` | Sitzungsstart, Reload-Zustand, Präferenz `step_free` |
| `floors` | Etagenleiste und Fokuswechsel |
| `plan` | Räume, Öffnungen, Assets, Connectoren |
| `places` | Suche und Zielauswahl |
| `routes` | Route-Tape, Distanz, Directions, `reachable` |
| `messages` | Guide-Antwort, `understood`, `effects`, Rückfragen |
| `actions` | Vorschau, Bestätigung, Abbruch und Revision |

Lokale Fixtures stammen aus `docs/api/examples/` und werden nicht manuell verändert. Der Adapter muss später ohne Änderungen an Features gegen HTTP austauschbar sein.

## 6. Design-System

- Hintergrund: `#F6F7F3`.
- Planfläche: `#E8ECE5`.
- Text: `#17211F`.
- Route/Primäraktion: `#E4572E`.
- Aktiv/barrierefrei: `#0E8F80`.
- Rückfrage/Vorschau: `#D19A24`.
- Fehler/unreachable: `#B84747`.
- Display-Schrift: Space Grotesk.
- Lesetext: Inter.
- IDs und Maße: IBM Plex Mono.

Der visuelle Fokus ist das Route Tape. Schatten, Blur und dekorative Flächen bleiben sparsam. Alle interaktiven Elemente besitzen einen sichtbaren Fokuszustand und mindestens 44px Zielgröße auf Touch-Geräten.

## 7. Umsetzungsreihenfolge

1. Vite-/React-Grundgerüst, Tokens und englische i18n-Schlüssel.
2. Fixture-Adapter und typisierte Beispieldaten.
3. App-Shell mit Building Header, Guide Panel und Map Surface.
4. SVG-Grundriss mit Räumen, Assets, Highlighting und Etagenleiste.
5. Route-Tape, Start-/Zielmarker und Schrittfolge.
6. Rückfrage-, unreachable- und pending-action-Zustände.
7. Responsive Reflow für 320, 390, 768, 1024 und 1440px.
8. Erster Three.js-Prototyp als optionale Ansicht.
9. Build, Lint, Playwright-Smoke und Accessibility-Prüfung.

## 8. Akzeptanzkriterien

- Die Anwendung startet lokal über einen dokumentierten npm-Befehl.
- Der Demo-Grundriss wird ohne Backend aus `floor-plan.json` gerendert.
- Die Beispielroute zeigt 46,1 m, Start, Ziel und Directions.
- Eine Rückfrage zeigt Kandidaten und rät nicht stillschweigend.
- Eine unerreichbare Route wird als Zustand mit Erklärung gezeigt, nicht als leerer Bildschirm.
- Eine ausstehende Änderung zeigt Vorschau und getrennte Bestätigen-/Abbrechen-Aktion.
- Reduced Motion deaktiviert die Tape-Animation ohne Informationsverlust.
- Keine horizontale Überbreite und sichtbarer Keyboard-Fokus.
- Frontend-Tests können Fixtures verwenden, ohne das Backend zu starten.

## 9. Nicht-Ziele

- Keine neue Backend-Route außerhalb `/api/v1`.
- Keine clientseitige Routenberechnung.
- Keine automatische Gebäudedatenänderung ohne Bestätigung.
- Keine vollständige 3D-Navigation im MVP.
- Keine hardcodierte Antwortlogik für Testfragen.


## 10. Implementierungsstand

- [x] Fixture- und HTTP-Gateway mit gemeinsamer `BuildingGateway`-Schnittstelle.
- [x] Session-Eröffnung über Gateway.
- [x] Etagenindex und Grundriss werden beim Start asynchron über Gateway geladen.
- [x] Nachrichten werden über `sendMessage` geleitet; Fixture- und HTTP-Envelope werden normalisiert.
- [x] Confirm/Cancel für ausstehende Aktionen verwenden Gateway-Endpunkte.
- [x] `VITE_DATA_MODE` und `VITE_API_BASE_URL` dokumentiert.
- [ ] Building Picker als sichtbare UI-Auswahl.
- [ ] Places-Suche als sichtbare Vorschlagsliste.
- [ ] Vollständige HTTP-Integration für Session-Preferences und Revision-Refresh.
- [ ] Playwright-/Axe-Smoke-Checks.

## 11. Nächster Lieferstand

- [x] Sichtbarer Building Picker über `gateway.listBuildings()`.
- [x] Gebäudewahl startet eine neue Session und lädt Etagen sowie Grundrisse neu.
- [x] Places Search über `gateway.searchPlaces()`.
- [x] Suchergebnisse zeigen Raum/Gerät und Etage.
- [x] Auswahl eines Suchergebnisses fokussiert die Etage und markiert das Ziel.
