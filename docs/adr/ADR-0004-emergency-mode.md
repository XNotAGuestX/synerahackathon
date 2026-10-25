# ADR-0004 — Notfallmodus: drinnen oder draußen

- Status: Accepted
- Datum: 2026-10-25
- Entscheider: Umsetzung von FR-17. Ersetzt den Roll-Call-Mock (safe/pending/unsafe, 2-Minuten-Frist). Der Vertrag bleibt v1, alle Änderungen sind additiv.

## Kontext

Im Notfall soll die Feuerwehr wissen, wie viele Menschen noch im Gebäude sind und wo. Ein Admin löst den Notfall am Telefon aus. Danach zeigt eine Live-Liste jedes Telefon als drinnen oder draußen. Wer ohne Telefon draußen ist, wird von Hand markiert. Die App hat keine Benutzerkonten. Echte Wi-Fi-Ortung gibt es nicht: Positionen kommen von der Figur auf dem Plan (`PUT .../position`). Rechtlich dürfen Ortungsdaten nur während des Alarms erhoben und nur von Admins gesehen werden (`EMERGENCY_MOCK_REASONING.md`).

## Entscheidung

- Admin-Recht kommt aus einer PIN in `EMERGENCY_ADMIN_PIN`. `POST /admin-tokens` tauscht sie gegen ein zufälliges Token. Die PIN bleibt nicht im Browser. Ein eigener Header `X-Admin-Token`, weil `Authorization` schon für `API_TOKEN` steht. Ohne PIN sind Admin-Endpunkte aus (`10003_admin_disabled`).
- Aktivieren braucht zusätzlich einen sechsstelligen Einmalcode (`emergency-challenges`), den die Oberfläche zeigt und der Admin abtippt. Das schützt vor versehentlichem Auslösen. Ein Versuch pro Code.
- Zwei Quellen: zwölf simulierte Personen pro Gebäude (geseedet aus der Gebäude-Id, ein Viertel bleibt drinnen) und jede Sitzung mit Position. Sitzungs-Ids verlassen `emergency.py` nie, Telefone heißen `D01`, `D02` und so weiter.
- Drinnen ist jeder Punkt in einem Raum, auch in einem `outdoor`-Raum: Ein Balkon gehört zum Gebäude. Draußen ist ein Punkt nur außerhalb aller Räume auf einer Etage mit Eingang. Ein Punkt neben einem Raum im Obergeschoss ist eine ungenaue Messung, kein Mensch in der Luft.
- Eine veraltete Position (über 15 s) drinnen bleibt drinnen. Retter müssen annehmen, dass dort noch jemand ist.
- Polling statt Push: Status alle 3 s, Liste alle 2 s. Die Middleware puffert Antworten (ADR-0003), und die Liste ist klein.
- Alles liegt im Speicher, pro Gebäude. Beenden oder Neustart löscht alles.
- Die Figur auf dem Plan bekommt vor jedem Eingang eine begehbare Fläche von 2,5 m. Nur so kann ein echtes Telefon in der Demo draußen sein (Ergänzung zu ADR-0002).

## Folgen

- Neue Operationen: `create_admin_token`, `get_emergency`, `create_emergency_challenge`, `put_emergency`, `delete_emergency`, `list_emergency_people`, `put_exit_confirmation`, `delete_exit_confirmation`, `put_profile`. Neue Codes: `10003_admin_disabled`, `30019` bis `30022`. `10002_forbidden` wird jetzt genutzt.
- Ein Neustart beendet den Alarm und meldet Admins ab. Das ist gewollt.
- Der Idempotenz-Cache hält die Antwort von `create_admin_token` samt Token 24 Stunden im Speicher.
- Jedes Telefon fragt alle 3 s. Ein aktives `--rate-limit` muss das tragen.
- Der Terminal-Chat hat die Tools `start_emergency_mode`, `emergency_status`, `mark_person_outside`, `end_emergency_mode`, nur mit simulierten Personen. Der HTTP-Chat bekommt keine Notfall-Tools.
- Echte Ortung (Opt-in-App oder Wi-Fi-Infrastruktur) ersetzt später nur die Quelle der Positionen.
