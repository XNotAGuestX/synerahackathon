# ADR-0004 — Notfallmodus: drinnen oder draußen

- Status: Accepted
- Datum: 2026-10-25
- Entscheider: Umsetzung von FR-17. Ersetzt den Roll-Call-Mock (safe/pending/unsafe, 2-Minuten-Frist). Der Vertrag bleibt v1, alle Änderungen sind additiv.

## Kontext

Im Notfall soll die Feuerwehr wissen, wie viele Menschen noch im Gebäude sind und wo. Ein Admin löst den Notfall am Telefon aus. Danach zeigt eine Live-Liste jedes Telefon als drinnen oder draußen. Wer ohne Telefon draußen ist, wird von Hand markiert. Die App hat keine Benutzerkonten. Echte Wi-Fi-Ortung gibt es nicht: Positionen kommen von der Figur auf dem Plan (`PUT .../position`). Rechtlich dürfen Ortungsdaten nur während des Alarms erhoben und nur von Admins gesehen werden (`EMERGENCY_MOCK_REASONING.md`).

## Entscheidung

- Admin-Recht kommt aus einer PIN in `EMERGENCY_ADMIN_PIN`. `POST /admin-tokens` tauscht sie gegen ein zufälliges Token. Die PIN bleibt nicht im Browser. Ein eigener Header `X-Admin-Token`, weil `Authorization` schon für `API_TOKEN` steht. Ohne PIN sind Admin-Endpunkte aus (`10003_admin_disabled`).
- Aktivieren braucht nur Name und PIN in einem Formular (Wunsch des Teams). Ein zusätzlicher Einmalcode, den der Admin abtippen musste, war zuerst umgesetzt (Commit `d960441`) und wurde vor jeder Veröffentlichung wieder entfernt: Im Notfall zählt jede Sekunde, und die PIN schützt schon vor versehentlichem Auslösen.
- Liste und Karte sind während des Alarms für jedes Telefon sichtbar, nicht nur für Admins (Entscheidung des Teams): Wer drinnen ist, sieht, wer noch fehlt, und Retter brauchen kein Admin-Gerät. Damit weicht die Demo von der Empfehlung in `EMERGENCY_MOCK_REASONING.md` ab (Ortung nur für Admins). Ein echter Betrieb müsste das mit Betriebsrat und Datenschutz klären. Markieren, Rückgängig und Beenden bleiben Admins vorbehalten.
- Showcase: Beim Start stehen drei simulierte Personen schon draußen, markiert vom „Assembly point warden“. Die übrigen gehen in Demo-Tempo los (2–12 s, 3 m/s), damit sich die Liste in einer kurzen Vorführung sichtbar leert.
- Zwei Quellen: zwölf simulierte Personen pro Gebäude (geseedet aus der Gebäude-Id, ein Viertel bleibt drinnen) und jede Sitzung mit Position. Sitzungs-Ids verlassen `emergency.py` nie, Telefone heißen `D01`, `D02` und so weiter.
- Drinnen ist jeder Punkt in einem Raum, auch in einem `outdoor`-Raum: Ein Balkon gehört zum Gebäude. Draußen ist ein Punkt nur außerhalb aller Räume auf einer Etage mit Eingang. Ein Punkt neben einem Raum im Obergeschoss ist eine ungenaue Messung, kein Mensch in der Luft.
- Eine veraltete Position (über 15 s) drinnen bleibt drinnen. Retter müssen annehmen, dass dort noch jemand ist.
- Polling statt Push: ohne Alarm der Status alle 3 s, während des Alarms die Liste alle 2 s auf jedem Telefon. Die Middleware puffert Antworten (ADR-0003), und die Liste ist klein.
- Alles liegt im Speicher, pro Gebäude. Beenden oder Neustart löscht alles.
- Die Figur auf dem Plan bekommt vor jedem Eingang eine begehbare Fläche von 2,5 m. Nur so kann ein echtes Telefon in der Demo draußen sein (Ergänzung zu ADR-0002).

## Folgen

- Neue Operationen: `create_admin_token`, `get_emergency`, `put_emergency`, `delete_emergency`, `list_emergency_people`, `put_exit_confirmation`, `delete_exit_confirmation`, `put_profile`. Neue Codes: `10003_admin_disabled`, `30019`, `30020`, `30022`. `30021` war kurz `challenge_invalid` und bleibt reserviert. `10002_forbidden` wird jetzt genutzt.
- Ein Neustart beendet den Alarm und meldet Admins ab. Das ist gewollt.
- Der Idempotenz-Cache hält die Antwort von `create_admin_token` samt Token 24 Stunden im Speicher.
- Jedes Telefon fragt alle 3 s, während des Alarms alle 2 s. Ein aktives `--rate-limit` muss das tragen.
- Der Terminal-Chat hat die Tools `start_emergency_mode`, `emergency_status`, `mark_person_outside`, `end_emergency_mode`, nur mit simulierten Personen. Der HTTP-Chat bekommt keine Notfall-Tools.
- Echte Ortung (Opt-in-App oder Wi-Fi-Infrastruktur) ersetzt später nur die Quelle der Positionen.
