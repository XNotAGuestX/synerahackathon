# ADR-0002 — Begehbare Figur auf dem Grundriss

- Status: Accepted
- Datum: 2026-10-25
- Entscheider: Umsetzung der Karteninteraktion. Eine neue API-Version braucht diese Entscheidung nicht.

## Kontext

Die Karte zeichnet Räume, Öffnungen und Geräte aus dem Etagenplan. Eine Figur soll mit Richtungstasten von A nach B laufen, ohne durch Wände, geschlossene Türen oder gezeichnete Geräte zu gehen. Der Plan hat keine Wandpolygone. Öffnungen sind Punkte mit Breite. Gemessene Abstände zur nächsten Raumkante reichen von 0 m bis 0.91 m.

## Entscheidung

Die Figur ist Darstellung auf der schon geladenen Etage.

- Wände sind Polygonkanten. Eine passierbare Öffnung schneidet eine Lücke und, wenn die Räume die Kante nicht teilen, einen Korridor durch die Öffnungsposition.
- Geschlossene Türen, Stufen bei aktiver Stufenfrei-Präferenz und zu schmale Öffnungen bleiben Wände. Geräteflächen sind fest.
- A und B kommen aus der vorhandenen Routenpolylinie. Folgen benutzt diese Polylinie und sucht keinen neuen Weg.
- Die Position bleibt im Seitenlauf. Sie wird nicht in der Sitzung gespeichert und wechselt die Etage nicht.
- Kein neues Feld in OpenAPI.

Ausführung: `docs/specs/map-walker.md`.

## Folgen

- Der Vertrag bleibt v1. Clients dürfen die Figur ignorieren.
- Die Oberfläche rechnet weiterhin keine bewertete Route.
- Gebogene Podeste können eine Lücke an einer Ecke statt an einer rekonstruierten Kehle bekommen.

## Verworfene Alternativen

- Wandflächen in der API: die Daten haben sie nicht, und v1 darf sie nicht still verlangen.
- Zweiter Router im Browser: widerspricht der einen Routenquelle.
- Physikengine: die Prüfung ist zweidimensional und muss ohne Laufzeitabhängigkeit testbar bleiben.
