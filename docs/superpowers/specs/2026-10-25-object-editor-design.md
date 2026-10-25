# Objekt-Editor — Design und Umsetzungsplan

Stand: 25. Oktober 2026. Branch `worktree-object-editor`. Vertrag für alle Implementierungs-Agents: Was hier steht, gilt; Abweichungen nur nach Rückfrage.

## 1. Ziel

Nutzer legen Objekte an, ändern ihre Details, verschieben sie, stellen sie auf andere Objekte, entfernen sie und machen die letzte Änderung rückgängig. Zusätzlich fügen sie Türen, Durchgänge, Treppen, Rolltreppen und Aufzüge hinzu. Beides geht über **Freitext** (Guide-Chat bzw. CLI-Agent) und über **Buttons im Frontend**. Wände und Raumumrisse bleiben unveränderlich.

Begriffe: *Objekt* = `asset` in `building.json`. *Verbindung* = `opening` (`door`, `opening` = Durchgang) oder `vertical_connector` (`stairs`, `escalator`, `lift`).

## 2. Entscheidungen

| Frage | Entscheidung |
|---|---|
| Persistenz | Pro Sitzung, wie Türen heute. Jede bestätigte Änderung schreibt zusätzlich `agent_output/api/<session_id>/building_edited.json` und `stacking_adapter.json`. Die CLI schreibt beide in ihr Ausgabeverzeichnis. |
| Entfernen / Rückgängig | Ja. Entfernen von Objekten (samt allem, was darauf steht) und von in der Sitzung hinzugefügten Verbindungen. Undo als Stapel (max. 20) pro Karte. |
| Stapel bewegen | Bewegt man ein tragendes Objekt, wandert alles darauf starr mit, auch in einen anderen Raum. Drehen oder Größe ändern wird abgelehnt, wenn danach etwas schwebt. |
| Rolltreppe | Keine Doku erwähnt Rolltreppen (Kit-Schema: `stairs | lift`). Annahme: Rolltreppe = beidseitig begehbar, Kosten wie Treppe, nie stufenfrei. Router bleibt unverändert. |
| Höhe | Objekthöhen stehen in `stacking_adapter.json`, nicht in `building.json`. Default-Höhe je Typ aus dem Katalog; eine geänderte Höhe ist ein Override und wird **nur** über diese Datei gespeichert und geladen. |
| Ein Pfad | Freitext und Buttons nutzen denselben Aktionsablauf `propose → confirm`. Der Agent schlägt nur vor. Im Editor gilt **Speichern** als Bestätigung. |
| Vertrag | Additiv in v1. Kein `/api/v2`. |

## 3. Datenmodell

### 3.1 Ids und Felder

- Neues Objekt: `{floor_id}-A-new{n}`; neue Verbindung zwischen Etagen: `{building_id}-V-new{n}`; neue Öffnung unverändert `{floor_id}-O-new{n}`. `n` = kleinste freie Zahl ab Anzahl+1 (Schema wie `add_door`). Ids ändern sich bei Verschiebung nicht.
- Neues Objekt: alle Pflichtfelder des Assets (`id name category type space_id floor_id position footprint{width_m depth_m rotation_deg} source`), `source: "user_edit"`. Neue Öffnungen/Verbinder: `synthetic: true`.
- Unbekannte Zusatzfelder bleiben erhalten.

### 3.2 `stacking_adapter.json`

```json
{
  "schema_version": 1,
  "building_id": "proc-campus-dev-000",
  "layers": [
    {"layer": 0, "objects": [
      {"object_id": "proc-campus-dev-000-A00002", "on_top_of": [], "height_m": 0.9, "height_source": "override", "elevation_m": 0.0},
      {"object_id": "proc-campus-dev-000-A00077", "on_top_of": [], "height_m": 2.1, "height_source": "override", "elevation_m": 0.0}
    ]},
    {"layer": 1, "objects": [
      {"object_id": "proc-campus-dev-000-F0-A-new1", "on_top_of": ["proc-campus-dev-000-A00002"], "height_m": 0.3, "height_source": "catalog", "elevation_m": 0.9}
    ]}
  ]
}
```

- Aufgeführt sind alle Objekte, die gestapelt sind, etwas tragen **oder** einen Höhen-Override haben. Alle anderen haben die Katalog-Höhe und fehlen.
- Ebene 0: steht am Boden. Ebene k ≥ 1: höchster Träger liegt auf Ebene k−1.
- `height_m`: wirksame Höhe. `height_source`: `override` (vom Nutzer gesetzt) oder `catalog` (Default des Typs). Nur `override`-Höhen sind Eingabe; `catalog`-Höhen werden beim Schreiben eingetragen und beim Laden aus dem Katalog neu bestimmt.
- `elevation_m`: Unterkante über dem Etagenboden = größte Oberkante (`elevation_m + height_m`) der Träger; Ebene 0 → 0. Abgeleitet.
- `layer` und `elevation_m` sind abgeleitet: Beim Laden neu berechnet, geschriebene Werte zählen nicht. Maßgeblich beim Laden sind `object_id`, `on_top_of` und `height_m` mit `height_source: "override"`. Höhe überschreiben = Override setzen, im Editor wie per Hand in der Datei.
- Sortierung: Ebenen aufsteigend, Objekte nach `object_id`, `on_top_of` sortiert. Nichts aufzuführen → `"layers": []`. Zahlen auf 0,001 m gerundet.
- UTF-8, LF, Einrückung 2, Zeilenende am Schluss, atomar ersetzt (wie `JsonBuildingStore.save`).
- Laden: Fehlt die Datei neben `building.json`, gibt es weder Stapel noch Overrides. Falsche `building_id`, unbekannte Ids, Zyklen oder `height_m` ≤ 0 → `MapError` mit klarer Meldung.

### 3.3 Objektkatalog

`final_agent/object_catalog.json`, erzeugt von `uv run python scripts/generate_object_catalog.py` aus allen `data/train/*/building.json` und `data/dev/*/building.json`. Deterministisch (sortiert, Mediane auf 0,05 m gerundet, mindestens 0,05 m).

```json
{
  "schema_version": 1,
  "groups": [
    {"id": "items", "label": "Items", "categories": [
      {"id": "furniture", "label": "Furniture", "types": [
        {"id": "desk", "label": "Desk", "action": "add_object", "width_m": 1.4, "depth_m": 0.7, "height_m": 0.75, "count": 1234}
      ]}
    ]},
    {"id": "connections", "label": "Connections", "categories": [
      {"id": "same_floor", "label": "Same floor", "types": [
        {"id": "door", "label": "Door", "action": "add_opening", "width_m": 0.9, "depth_m": null, "count": 0},
        {"id": "opening", "label": "Passage", "action": "add_opening", "width_m": 1.2, "depth_m": null, "count": 0}
      ]},
      {"id": "between_floors", "label": "Between floors", "types": [
        {"id": "stairs", "label": "Stairs", "action": "add_connector", "width_m": null, "depth_m": null, "count": 0},
        {"id": "escalator", "label": "Escalator", "action": "add_connector", "width_m": null, "depth_m": null, "count": 0},
        {"id": "lift", "label": "Lift", "action": "add_connector", "width_m": null, "depth_m": null, "count": 0}
      ]}
    ]}
  ]
}
```

- Kategorien-Reihenfolge: furniture, equipment, fixture, machine. Typen nach `label`. `label` = Typ-Id, `_` → Leerzeichen, erster Buchstabe groß.
- `door.width_m` = 0,9 (`NEW_DOOR_WIDTH_M`). `opening.width_m` = Median der Datensatz-Öffnungen mit `kind: opening`. Zahlen der Beispiele oben sind Platzhalter.
- `height_m` je Objekttyp: Der Datensatz hat keine Höhen. Das Skript enthält eine kleine, kommentierte Tabelle typischer Höhen (z. B. desk 0.75, chair 0.9, shelf 2.0, server_rack 2.0, forklift 2.2) und je Kategorie einen Fallback (furniture 0.8, equipment 1.0, fixture 0.9, machine 1.8). Verbindungen: `height_m: null`.
- Ein Typ kann in zwei Kategorien stehen (`washing_machine`). Ohne Kategorie gewinnt die mit größerem `count`.

## 4. Deterministischer Kern (Python)

### 4.1 Module

`final_agent/stacking.py` — nur Stapel-Datenlogik, keine Geometrie:

```python
STACKING_FILE = "stacking_adapter.json"
def layers(supports: dict[str, list[str]]) -> dict[str, int]          # alle Beteiligten inkl. Ebene-0-Träger
def elevations(supports: dict[str, list[str]], heights: dict[str, float]) -> dict[str, float]  # Unterkanten
def descendants(supports: dict[str, list[str]], object_id: str) -> list[str]  # transitiv, sortiert
def to_document(building_id: str, supports: dict[str, list[str]], overrides: dict[str, float],
                heights: dict[str, float]) -> dict                     # heights = wirksame Höhen der Aufgeführten
def from_document(document: dict, building_id: str, asset_ids: set[str]) -> tuple[dict[str, list[str]], dict[str, float]]
def load(path: Path, building_id: str, asset_ids: set[str]) -> tuple[dict, dict]  # fehlende Datei → ({}, {})
def save(path: Path, document: dict) -> None                                       # atomar
```

`final_agent/object_edits.py` — Validierung und Anwendung aller Editor-Änderungen:

```python
EDIT_KINDS = ("add_object", "update_object", "remove_object", "add_opening", "add_connector", "undo_edit")
def load_catalog() -> dict                                   # gecacht
def find_object_types(query: str | None = None) -> list[dict]  # flach: group, category, type, label, action, width_m, depth_m
def footprint_polygon(asset: dict) -> Polygon
def default_height(asset: dict) -> float                     # Katalog: Typ+Kategorie, sonst Kategorie-Fallback
def effective_height(building_map: BuildingMap, asset_id: str) -> float  # Override sonst Default
def check_edit(building_map: BuildingMap, proposal: dict) -> dict  # ändert building_map nie
def apply_edit(building_map: BuildingMap, proposal: dict) -> dict  # atomar, schreibt Undo
```

`apply_edit` akzeptiert zusätzlich den Altfall `{"kind": "add_door", "first_space", "second_space", "step_free"}` und behandelt ihn wie `add_opening` mit `opening_kind: "door"`. So landen auch bestätigte Chat-Türen im Undo-Stapel.

`BuildingMap` (`final_agent/building_map.py`):

- `self.stacking: dict[str, list[str]]` (Objekt → Träger), `self.height_overrides: dict[str, float]`, `self.undo_stack: list[dict]` (max. `UNDO_LIMIT = 20`).
- `stacking_document() -> dict`: das Dokument aus 3.2 für den aktuellen Stand.
- `snapshot() -> dict` / `restore(snapshot, keep_closures: bool = False)`: Daten (Assets, Öffnungen, Verbinder), Indexe, `stacking`, `height_overrides`, `closed`, `walks` (flach), `last_route`, Länge von `undo_stack`; Spatial-Index wird verworfen.
- `transaction()` nutzt `snapshot/restore` und stellt bei Fehler **alles** wieder her, auch Assets, Verbinder, Stapel und einen schon geschriebenen Undo-Eintrag.
- `clone() -> BuildingMap`: unabhängige Kopie (Daten, `closed`, `stacking`, `height_overrides`, `undo_stack`, `walks`, `last_route`, `active_request`, `selection`). `SessionService.working_copy` nutzt künftig `clone()`.
- `resolve_object(reference) -> str`: Asset-Id oder eindeutiger Asset-Name (ohne Groß/Klein), Öffnungs-Id, Verbinder-Id oder -Name. Mehrdeutig → `MapError(reason="ambiguous", candidates=[{"id": …}])`; fehlt → `reason="not_found"`.
- `add_door(..., kind: str = "door")`: `kind` ∈ {`door`, `opening`}.
- `wall_at(floor_id, position) -> tuple[str, str]`: die zwei verschiedenen Räume der Etage, deren Umriss am nächsten am Punkt liegt, beide ≤ `SHARED_WALL_TOLERANCE_M`. Sonst `MapError(reason="not_adjacent")`.
- `load(path)` liest eine `stacking_adapter.json` daneben; `save(path)` schreibt `building_edited.json` **und** `path.parent / STACKING_FILE`.
- `MapError` bekommt optional `field: str | None` (abwärtskompatibel).

### 4.2 Proposal-Form (gleich in API, CLI-Tools und Chat)

Fehlende Felder oder `null` = Default (anlegen) bzw. unverändert (ändern).

| kind | Felder |
|---|---|
| `add_object` | `type` (Pflicht), `category`, `name`, `space`, `floor_id`, `position` `[x, y]`, `rotation_deg` (Default 0), `width_m`, `depth_m` (Default aus Katalog; unbekannter Typ 0,5), `height_m` (gesetzt = Override, sonst Katalog), `on_top_of` (Liste, Default `[]`) |
| `update_object` | `object_ref` (Pflicht) und optional `name`, `type`, `category`, `space`, `floor_id`, `position`, `rotation_deg`, `width_m`, `depth_m`, `height_m` (setzt Override), `on_top_of` (`[]` = auf den Boden), `step_free`, `opening_kind` |
| `remove_object` | `object_ref` |
| `add_opening` | `opening_kind` (`door`\|`opening`, Default `door`), `first_space` + `second_space` (beide oder keiner), `floor_id` + `position` (wenn keine Räume), `width_m` (Default Katalog), `step_free` (Default `true`) |
| `add_connector` | `connector_kind` (`stairs`\|`escalator`\|`lift`), `spaces` (≥ 2 Raum-Referenzen), `name`, `step_free` |
| `undo_edit` | — |

`update_object` je Ziel: Asset → `name type category space floor_id position rotation_deg width_m depth_m height_m on_top_of`; Öffnung → `opening_kind width_m step_free`; Verbinder → `name step_free`. Anderes Feld → `MapError(reason="invalid_field", field=…)`.

`check_edit` gibt die **normalisierte** Proposal zurück: Referenzen durch Ids ersetzt, Position berechnet, Defaults gefüllt. Eine normalisierte Proposal erneut anzuwenden ist deterministisch.

### 4.3 Regeln

Platzierung (jedes neue, verschobene oder geänderte Asset, inkl. mitbewegter Stapel):

1. Der Mittelpunkt (`position`) liegt in einem Raum dieser Etage. Liegt er in mehreren, gilt der flächenkleinste. Dieser Raum wird `space_id`. Ist `space` angegeben, muss die Position darin liegen (`outside_space`).
2. Der gedrehte Footprint liegt im Raumpolygon, gepuffert um `PLACEMENT_TOLERANCE_M = 0.15` (`crosses_wall`). Messung: alle 11 811 Assets aus 12 dev-Gebäuden erfüllen das.
3. Nur `space` ohne `position` → Position = `anchor(space)`. Nur `on_top_of` ohne `position` → Mittelpunkt der Vereinigung der Träger-Footprints; Etage und Raum von den Trägern. Weder `space` noch `position` noch `on_top_of` beim Anlegen → `invalid_field` (`field="space"`).

Stapeln („nicht schweben“):

4. Träger sind Assets, nicht das Objekt selbst, nicht etwas, das auf dem Objekt steht (`support_cycle`), existieren (`not_found`, `field="on_top_of"`).
5. Alle Träger auf derselben Etage und im selben Raum wie das Objekt (`support_other_space`).
6. Der Footprint überlappt jeden Träger mit mindestens `SUPPORT_MIN_OVERLAP_M2 = 0.01`, und der Mittelpunkt liegt in der Vereinigung der Träger-Footprints (`floating`).
7. Ein gestapeltes Objekt im selben Raum verschieben: Regeln 5–6 gelten weiter, sonst `floating`. Verschiebung in einen anderen Raum oder auf eine andere Etage **ohne** `on_top_of` → Objekt kommt auf den Boden (`on_top_of = []`); die Zusammenfassung sagt „on the floor“.
8. Träger verschieben: alle Nachfahren werden um denselben Vektor verschoben und übernehmen Etage und Raum; alle werden nach 1–2 geprüft.
9. Drehen oder Größe eines Trägers ändern: gelten 6 für die Objekte darauf nicht mehr → `would_strand`.

Höhe:

9a. `height_m` muss endlich und > 0 sein (`invalid_field`). Gesetzt beim Anlegen oder Ändern → Override in `height_overrides`; ohne Angabe gilt `default_height`. Ein Typwechsel ändert eine Override-Höhe nicht.
9b. Oberkante jedes betroffenen Objekts und aller Nachfahren (`elevation_m + height_m`) ≤ `height_m` der Etage (`exceeds_ceiling`). Gilt auch, wenn die Höhe eines Trägers wächst oder ein Stapel auf eine niedrigere Etage wandert.
9c. Entfernen eines Objekts entfernt auch seine Overrides; Undo stellt sie wieder her.

Verbindungen:

10. `add_opening` mit Räumen → `add_door(first, second, step_free, width_m, position, kind)`. Ohne Räume → `wall_at(floor_id, position)`, dann Position auf die gemeinsame Wand projizieren (wie Mittelpunkt in `shared_wall`: nächster Punkt auf Raum 1, halbwegs zu Raum 2). Nicht benachbart / Wand zu kurz / Duplikat → `not_adjacent`.
11. `add_connector`: Räume auflösen, Etagen paarweise verschieden (`same_floor`), nach Ebene sortieren, aufeinanderfolgende Stopps überlappen im Grundriss mit mindestens `CONNECTOR_MIN_OVERLAP_M2 = 0.25` (`not_stacked`). `stairs`/`escalator`: `step_free` immer `false`; `lift`: Default `true`. Name-Default `Stairs N` / `Escalator N` / `Lift N`, eindeutig.

Entfernen und Undo:

12. `remove_object` auf ein Asset entfernt es und alle Nachfahren und bereinigt `stacking`. Öffnungen und Verbinder nur, wenn `synthetic` und Id enthält `-new` (`not_removable`). Entfernte Ids verschwinden aus `closed`, `located_asset_ids` und `selection`.
13. Jede erfolgreiche Änderung außer `undo_edit` legt `{snapshot, summary, floor_ids}` auf `undo_stack`. `undo_edit` stellt den letzten Stand wieder her, **behält aktuelle Schließungen** (minus Ids, die es nicht mehr gibt), Ergebnis-Zusammenfassung `Undo: <summary>`. Leer → `nothing_to_undo`.
14. Nach jeder Änderung: Spatial-Index verwerfen, `last_route = None`, `walks` der betroffenen Räume bei Öffnungen verwerfen. Assets beeinflussen den Router nicht.

Zusammenfassungen (Englisch, ein Satz, für die Bestätigungskarte), z. B. `Add Desk 0.02 in Office 0.02.`, `Move Printer 2.01 to Kitchen 2.03 (on the floor).`, `Put Laptop 0.02 on Desk 0.02-A.`, `Remove Desk 0.02-A and 1 object on top.`, `Add a passage between Corridor 0.01 and Office 0.02.`, `Add Escalator 1 between Ground floor and First floor.`, `Undo: Add Desk 0.02 in Office 0.02.`

### 4.4 Rückgabeformen

`apply_edit` → EditResult:

```json
{"kind": "add_object", "summary": "...", "changed_ids": ["..."], "removed_ids": [], "floor_ids": ["..."],
 "assets": [/* Asset nach der Änderung */], "openings": [], "connectors": []}
```

`check_edit` →

```json
{"proposal": {/* normalisiert */}, "summary": "...",
 "preview": {"floor_ids": [], "assets": [], "openings": [], "connectors": [], "removed_ids": [], "space_ids": []}}
```

`preview` zeigt den Zustand **nach** der Änderung für alle neuen oder geänderten Elemente (inkl. mitbewegter Stapel); `space_ids` = betroffene Räume zum Hervorheben.

### 4.5 `MapError.reason` → API

| reason | HTTP | code | `details` |
|---|---|---|---|
| `not_found` (Objekt, Träger) | 404 | `30013_element_not_found` | `field` |
| `not_found` (Raum) | 404 | `30004_place_not_found` | `field` |
| `ambiguous` | 409 | `30005_place_ambiguous` | Kandidaten-Ids |
| `outside_space`, `crosses_wall`, `floating`, `support_cycle`, `support_other_space`, `would_strand`, `exceeds_ceiling`, `not_stacked`, `same_floor` | 409 | `30014_invalid_placement` | `code` = reason |
| `not_adjacent` | 409 | `30007_not_adjacent` | |
| `nothing_to_undo` | 409 | `30015_nothing_to_undo` | |
| `not_removable` | 409 | `30016_not_removable` | |
| `invalid_field`, `unknown_type`, ungültige Zahl | 400 | `20001_validation_failed` | `field` |

## 5. HTTP-Vertrag (additiv v1)

Beide OpenAPI-Dateien (`openapi.yaml`, `docs/api/openapi.yaml`) gleich halten; einziger Unterschied bleibt der Pfad in Zeile 7.

- `ActionCreate` oneOf + Mapping: `AddObjectProposal`, `UpdateObjectProposal`, `RemoveObjectProposal`, `AddOpeningProposal`, `AddConnectorProposal`, `UndoEditProposal` (Felder wie 4.2, `additionalProperties: false`, Referenzen 1–200 Zeichen, Zahlen endlich, Breite/Tiefe > 0).
- `EditResult`: `{kind (enum der 6), summary, changed_ids, removed_ids, floor_ids}`. `ActionResult`-Mapping: die 6 Kinds → `EditResult`.
- `preview_effects` einer Editor-Aktion: `[{"type": "preview_objects", "floor_ids", "assets", "openings", "connectors", "removed_ids"}, {"type": "highlight_spaces", "space_ids", "reason": "preview"}]`. Neues Schema `PreviewObjectsEffect` in `ViewEffect`.
- `GET /api/v1/object-types` → `ObjectCatalog` (Katalog 3.3), `operationId: list_object_types`, ohne Sitzung.
- `FloorPlan.stacking`: immer vorhanden, Liste `{object_id, layer, on_top_of, height_m, height_source, elevation_m}` für die in `stacking_adapter.json` aufgeführten Objekte dieser Etage (3.2). Für alle anderen gilt die Katalog-Höhe.
- `ObjectCatalog`-Typen tragen `height_m` (`number | null`). `AddObjectProposal`/`UpdateObjectProposal` haben `height_m` (`number > 0 | null`).
- `ClientContext.selected_object_id`: `string | null` (Asset, Öffnung, Verbinder). Unbekannt → `30013_element_not_found`, `field: selected_object_id`.
- `Intent` + `edit`. `ErrorCode` + `30014_invalid_placement`, `30015_nothing_to_undo`, `30016_not_removable`. `Connector.kind`-Beschreibung nennt `escalator`.
- Bestätigung jeder Gebäudeänderung (6 neue Kinds und `add_door`): innerhalb der Transaktion `session.map.save(output_directory / session.id / "building_edited.json")`. Speicherfehler → Rollback, 500 `00001_internal`, Aktion bleibt `pending`.
- `docs/DESIGN.md`: FR-7 erweitern, FR-11 Objekt-Editor, Fehlertabelle, effects-Tabelle (`preview_objects`), Sitzungsdateien, Undo-Semantik.
- Fixtures: `scripts/generate_api_fixtures.py` erzeugt zusätzlich Beispiele für `object-types`, eine `add_object`-Aktion (pending und confirmed) und einen `30014`-Fehler. `scripts/validate_api_fixtures.py` grün.

## 6. Freitext-Kanal

`final_agent/tools.py` (CLI wendet sofort an und speichert über den vorhandenen `apply_edit`-Helfer; Ergebnis = EditResult + `saved_to` + `active_route_update()`):

```text
list_object_types(query=None)
add_object(type, space=None, name=None, category=None, position=None, floor_level=None, rotation_deg=0, width_m=None, depth_m=None, height_m=None, on_top_of=None)
update_object(object, name=None, type=None, category=None, space=None, position=None, floor_level=None, rotation_deg=None, width_m=None, depth_m=None, height_m=None, on_top_of=None, step_free=None, opening_kind=None)
remove_object(object)
add_opening(opening_kind="door", first_space=None, second_space=None, position=None, floor_level=None, width_m=None, step_free=True)
add_connector(connector_kind, spaces, name=None, step_free=None)
undo_last_edit()
```

Tools rechnen `floor_level` → `floor_id` um und bauen die Proposal aus 4.2. `final_agent/agent.py` System-Prompt bekommt einen kurzen Abschnitt: Namen zuerst über `search_building`/`inspect_space` auflösen, nie Koordinaten erfinden, Räume oder das ausgewählte Objekt nutzen, „put X on Y“ → `update_object(X, on_top_of=[Y])`, „take X off“ → `on_top_of=[]`, bei Mehrdeutigkeit nachfragen.

`final_agent/api_session.py` `TurnTools`: Overrides mit **denselben Namen** für die 6 schreibenden Tools bauen dieselbe Proposal und rufen `self.proposal(...)`. `API_PROMPT`: diese Tools schlagen nur vor. `ApiReply.intent` + `edit`. `client_context.selected_object_id` erreicht den Turn-Kontext.

## 7. Frontend

Neu: `src/features/object-editor/EditorPanel.tsx`, `TypePicker.tsx`, `ObjectForm.tsx`, `SupportPicker.tsx`; `src/domain/editor.ts` (reine Funktionen: Katalog flach/Suche, Draft → Proposal, Nudge/Drehen, Klemmen auf Trägerfläche, Gültigkeitshinweis); `src/domain/editor.check.ts`; `package.json` Script `test:editor`.
Geändert: `api/gateway.ts` (`listObjectTypes`, `createAction`, Confirm liefert ganze Aktion inkl. `result`, `sendMessage` mit `client_context`), `api/fixtures.ts` (Offline-Katalog), `domain/types.ts`, `domain/presentation.ts` (`preview_objects` → Geister), `rendering/PlanCanvas.tsx`, `app/App.tsx`, `features/guide/GuidePanel.tsx` (falls nötig), `i18n/en.ts`, `styles.css`.

Verhalten:

- **Ein Einstieg:** Button „Edit map“ (Stift-Icon + Text) in `.map-toolbar`, Taste `E` außerhalb von Eingabefeldern. Ist ein Objekt ausgewählt → Editor öffnet dessen Details; sonst → Hinzufügen mit fokussierter Typauswahl. Offen: Text „Done“, `aria-pressed="true"`. Schließen mit ungespeichertem Entwurf → Inline-Rückfrage „Discard changes?“ (kein `window.confirm`).
- Das Editor-Panel ersetzt während der Bearbeitung `.guide-region`. Fokus wandert ins Panel und beim Schließen zurück zum Button. `Esc` bricht den aktuellen Modus ab.
- **Typauswahl hierarchisch:** Breadcrumb (`Items › Furniture › Desk`), Kinder als Buttons (≥ 40 px), Suchfeld über alle Ebenen, zuletzt genutzte Typen (localStorage, max. 5).
- **Hinzufügen Objekt:** Geist folgt dem Zeiger, Klick setzt ihn, danach Formular. **Tür/Durchgang:** Wandmodus, Klick sendet `floor_id` + `position`. **Treppe/Rolltreppe/Aufzug:** Raum auf dieser Etage anklicken, Etage wechseln, zweiten Raum anklicken (weitere optional), Chips zeigen die Auswahl.
- **Formular Objekt:** Name, Typ (öffnet Typauswahl), Raum (abgeleitet), X/Y (Schritt 0,1), Drehung (Zahl + ±15°), Breite/Tiefe, Höhe (wirksame Höhe aus `FloorPlan.stacking` oder Katalog; Hinweis „default“/„custom“; Ändern sendet `height_m`), „Stands on“ (zeigt Unterkante „sits at 0.75 m“). **Öffnung:** Tür/Durchgang, Breite, stufenfrei. **Verbinder:** Name, stufenfrei (nur Aufzug).
- **„Stands on“:** Combobox (ARIA-1.2-Muster) über Objekte derselben Etage nach Name/Typ, sortiert nach Abstand; Mehrfachauswahl als Chips; Auswahl setzt den Entwurf auf den Mittelpunkt der Träger; leer = „On the floor“; zeigt „Layer n“.
- **Auf der Karte:** ausgewähltes Objekt ziehen (Pointer-Events; Pan pausiert), Pfeiltasten 0,1 m (Shift 1 m), `R`/`Shift+R` ±15°. Ein Träger zieht seinen Stapel sichtbar mit. Ein gestapeltes Objekt wird beim Ziehen auf die Trägerfläche geklemmt. Ungültig: rot gestrichelt **plus** Text. Server entscheidet.
- **Speichern** = `createAction` + `confirmAction`. Während des Speicherns gesperrt. Erfolg: Etagen aus `result.floor_ids` neu laden, Objekt bleibt ausgewählt, Live-Region meldet die Zusammenfassung. Fehler: Code → verständlicher Text am Formular, Entwurf bleibt. Scheitert nur die Bestätigung → Aktion abbrechen (best effort). `30010_action_conflict` → „Confirm or cancel the guide's pending change first.“
- **Entfernen:** Gefahr-Button mit Inline-Rückfrage „Remove X (and n on top)?“. **Undo:** Button „Undo last edit“; `30015` → „Nothing to undo“.
- Gestapelte Objekte zeichnen nach ihren Trägern mit Badge `L1`, `L2`…
- Chat-Vorschläge mit `preview_objects` zeigen Geister; Bestätigen in der Guide-Karte lädt bei Editor-Kinds die Etagen aus `result.floor_ids` neu (bestehendes `confirm()` verallgemeinern).
- `sendMessage` sendet `client_context` mit `floor_level` und, falls ausgewählt, `selected_space_id` bzw. `selected_object_id`.

## 8. Prüfung (kurz)

```bash
uv run python -m unittest discover -s tests -p 'test_object_edits.py'
uv run python -m unittest discover -s tests -p 'test_api.py'
uv run python scripts/generate_api_fixtures.py && uv run python scripts/validate_api_fixtures.py
uv run python -m unittest discover -s tests          # einmal am Ende
(cd frontend && npm run build && npm run test:effects && npm run test:editor)
```

Tests nur für Kernregeln: Platzierung, Stapel (schwebend, Zyklus, Mitbewegen, `would_strand`), Höhe (Override, Unterkante, Decke), Entfernen, Undo, Adapter-Rundreise, Rolltreppe im Router, eine API-Runde pro Kind, Sitzungsisolation, geschriebene Dateien, Chat-Override schlägt nur vor.

## 9. Aufteilung

| Agent | Phase | Dateien |
|---|---|---|
| A backend-core | 1 | `final_agent/building_map.py`, `stacking.py`, `object_edits.py`, `object_catalog.json`, `tools.py`, `agent.py`, `scripts/generate_object_catalog.py`, `tests/test_object_edits.py` |
| B frontend-editor | 1 (parallel zu A) | nur `frontend/` |
| C api-contract | 2 (nach A) | `openapi.yaml`, `docs/api/openapi.yaml`, `docs/DESIGN.md`, `final_agent/api.py`, `final_agent/api_session.py`, `scripts/generate_api_fixtures.py`, `docs/api/examples/`, `tests/test_api.py` |
| D integration | 3 | beliebig, nur Abgleichsfehler |

Agents committen nicht; der Koordinator committet je Phase.

## 10. Menschliche Verifikation

API und Frontend starten:

```bash
uv run python -m final_agent.api            # Port 8000
(cd frontend && npm run dev)                # Vite-Proxy auf /api/v1
```

1. „Edit map“ ohne Auswahl → Typauswahl offen, Fokus im Suchfeld. Suche „desk“ zeigt `Furniture › Desk`.
2. Desk wählen, in einen Raum klicken, speichern → Objekt erscheint, Revision steigt, `agent_output/api/<session>/building_edited.json` enthält es.
3. Desk über eine Wand ziehen → rot + Text; speichern lehnt mit „crosses a wall“ ab.
4. Neues Objekt (z. B. Laptop/Monitor) anlegen, „Stands on“ → Desk wählen → sitzt auf dem Desk, Badge `L1`, `stacking_adapter.json` hat Ebene 0 und 1.
5. Laptop vom Desk herunterziehen → bleibt auf der Desk-Fläche geklemmt.
5a. Höhe des Desks auf 0,9 m setzen → `stacking_adapter.json`: Desk `height_source: "override"`, Laptop `elevation_m: 0.9`. Höhe 5 m → abgelehnt (Decke). Override per Hand in der Datei ändern und laden → neue Höhe gilt: `uv run python -c "from pathlib import Path; from final_agent.building_map import BuildingMap; print(BuildingMap.load(Path('agent_output/api/<session>/building_edited.json')).height_overrides)"`.
6. Desk in einen anderen Raum verschieben → Laptop wandert mit.
7. Desk um 90° drehen, sodass der Laptop schweben würde → abgelehnt mit verständlichem Text.
8. „Undo last edit“ zweimal → vorherige Zustände kommen zurück.
9. Desk entfernen → Rückfrage nennt „1 on top“; beide weg.
10. Tür: „Door“ wählen, auf Wand zwischen zwei Räumen klicken, speichern → Tür sichtbar; Route durch die neue Tür möglich.
11. Rolltreppe: zwei übereinanderliegende Räume auf zwei Etagen wählen → Route zwischen den Etagen nennt die Rolltreppe; mit „step-free“ wird sie gemieden.
12. Chat: „put a coffee machine in the kitchen on floor 1“ → Bestätigungskarte mit Geist; bestätigen → Objekt da. „move it to room X“ mit ausgewähltem Objekt → Vorschlag. „undo that“ → Vorschlag, bestätigen.
13. Tastatur: nur mit Tab/Pfeilen/`R`/`Esc` ein Objekt anlegen, verschieben, drehen, speichern.

## 11. Nicht im Umfang

Wände und Raumumrisse; Eingänge nach draußen; Verschieben oder Entfernen von Datensatz-Türen/-Treppen (nur Schließen); Objekthöhen und 3D-Ansicht; Neuerzeugen von `equipment.csv`; gemeinsame Bearbeitung über Sitzungen hinweg; Einweg-Rolltreppen.
