# ADR-0003 — Sprachmodus, Live-Position und Wegpunktführung

- Status: Accepted
- Datum: 2026-10-25
- Entscheider: Umsetzung von EXT-02. Ersetzt von ADR-0002 die Klausel „Die Position bleibt im Seitenlauf“. Der Vertrag bleibt v1, alle Änderungen sind additiv.

## Kontext

Der Nutzer soll freihändig sprechen und den Weg gesprochen geführt bekommen. Die Position kommt heute von der Debug-Figur, später von einer Wi-Fi-Ortung, und wird wie ein Webhook an das Backend gesendet. Der Server führt den Nutzer von Wegpunkt zu Wegpunkt. `ProtocolMiddleware` puffert jede Antwort. Der Branch `origin/Audio` ist nicht vertrauenswürdig: Zustandsmaschine, Turn-Zusammenführung, Raumzuordnung, Clip-Cache und eine fälschbare Kontextzeile hatten Fehler.

## Entscheidung

- Die Führung läuft im Server. `LiveState` einer Sitzung ist der einzige Besitzer von Position und Fortschritt. Ein Wegpunkt gilt bei höchstens 3 m als erreicht. Pro Wegpunkt gibt es höchstens eine `wrong_way`-Warnung, keine Neuroute.
- `position` und `guidance` sind PUT-Singletons nach dem Muster von `preferences`, ohne `Idempotency-Key` und ohne `revision`. Das weicht von „Nomen im Plural“ ab, weil ein Fix pro Sekunde keinen 24-Stunden-Replay-Eintrag braucht.
- Der Feed ist ein Long-Poll (`GET guidance?after=&wait_s=`, höchstens 25 s) und kein SSE, weil die Middleware Antworten puffert. `fetch` kann den Auth-Header senden.
- Sprachclips sind vom Server vergebene Ids für Text. `GET speech-clips/{id}` synthetisiert beim ersten Abruf und cached. Es gibt keinen Freitext-TTS-Endpunkt, nur Servertext kostet Credits.
- STT und TTS laufen serverseitig mit ElevenLabs. `POST transcriptions` nimmt rohes Audio bis 2 MiB. Das ist die einzige Ausnahme von der 64-KiB-Grenze.
- Ein KI-Erzähler wählt pro Route Sätze aus einem Phrasenkatalog und füllt Landmarken. Distanzen, Seiten und Namen kommen aus Code. Bei Fehlern gelten die Standardphrasen.
- Nichts aus `origin/Audio` wird übernommen. Nur Ideen werden neu umgesetzt, mit eigenen Tests.
- Die Sprache ist nur Englisch.

## Folgen

- Der Vertrag bleibt v1. Neue Operationen: `put_position`, `create_transcription`, `get_guidance`, `put_guidance`, `delete_guidance`, `get_speech_clip`. Neue Codes: `30017_speech_clip_not_found`, `40004_speech_unavailable`.
- Jeder offene Long-Poll belegt einen Threadpool-Thread, bis er endet. Abgebrochene Polls tun das bis zum Timeout. Das ist für die Demo vertretbar.
- Das Rate-Limit muss etwa einen Fix pro Sekunde plus Long-Polls tragen.
- Lautsprecher-Echo kann Barge-in auslösen. Für die Demo gelten Kopfhörer.
- `structure_reply` kostet pro Turn einen Modellaufruf. Ist es zu langsam, endet der Voice-Turn direkt mit JSON.
- Ein Fix ändert `revision` nicht und kann kein `30012_revision_conflict` auslösen.
- Browser-Mikrofontest und Live-Prüfung mit ElevenLabs und Anthropic sind noch nicht gelaufen.

## Verworfene Alternativen

- Führung im Browser: zweiter Fortschrittsbesitzer, widerspricht der einen Routenquelle.
- SSE oder gestreamtes Audio: die Middleware puffert.
- Freitext-TTS: offene Kostenfläche.
- Code aus `origin/Audio`: nicht vertrauenswürdig.
