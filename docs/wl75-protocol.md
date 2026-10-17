# Beurer WL75 – BLE-Protokoll (aus der Android-App "beurer LightUp" rekonstruiert)

Stand: 2026-10-17. Ergebnis statischer Analyse (jadx-Dekompilat), die APK wurde nicht
ausgeführt. Handshake, alle Status-Abfragen sowie Licht an/aus wurden anschließend am
echten Gerät verifiziert, siehe Abschnitt 10.

## Kennzeichnung

- **[Code]** – direkt aus dem dekompilierten Quelltext abgelesen.
- **[Abgeleitet]** – Schlussfolgerung/Berechnung auf Basis des Codes, nicht direkt dort
  zu lesen (z. B. berechnete Prüfsummen, Interpretation von Wertebereichen).
- **[Offen]** – unklar, muss am Gerät verifiziert werden.

## Quelle

- Paket: `com.beurer.connect.lightup` ("beurer LightUp")
- Analysierte Version: **3.8 (versionCode 50)**, bezogen über APKPure
  (`https://d.apkpure.net/b/APK/com.beurer.connect.lightup?versionCode=50`).
- Zusätzlich gesichtet: 2.1 (versionCode 101, 2016) – reine Classic-/SPP-Version ohne
  WL75-BLE-Code, für dieses Dokument irrelevant. (Achtung: APKPure liefert bei
  `latest` diese alte 2.1, weil ihr versionCode höher ist.)
- Dekompiliert mit jadx 1.5.6. Alle Pfade unten sind relativ zu
  `sources/com/beurer/connect/lightup/` im jadx-Output.
- BLE-Stack der App: inuker BluetoothKit (`com.inuker.bluetooth.library`, leicht
  modifiziert).

## 1. Geräteerkennung

**[Code]** `devices/BeurerDeviceFactory.java` → `getExtraInfoByName(name, mac)` prüft den
Advertising-Namen per Präfix, in dieser Reihenfolge:

1. `WL90…` → `WL90Device`
2. `TL100…` und Name endet auf die letzten 4 Hex-Ziffern der MAC → `TL100NewDevice`
3. `TL100…` → `TL100Device`
4. `WL75…` → `WL75Devices`

**[Code]** `devices/wl75/WL75Devices.java`:

| Feld | Wert |
|---|---|
| Namenspräfix | `WL75` |
| Pair-Name | `WL 75` |
| Protokoll | `2` (= BLE; `1` wäre Classic/SPP) |
| Service | `14839AC4-7D7E-415C-9A42-167340CF2339` |
| Write-Characteristic | `8B00ACE7-EB0B-49B0-BBE9-9AEE0A26E1A3` |
| Notify-Characteristic | `0734594A-A8E7-4B1A-A6B1-CD5243059A57` |
| Versions-Service | `0x180A` (Device Information) |
| Versions-Characteristic | `0x2A28` (Software Revision String) |

Dieselben drei 128-bit-UUIDs stehen auch in `devices/wl75/WL75BleDefaultConfig.java`.

**[Code]** Die Characteristics `ba04c4b2-…` und `e06d5efb-…` sowie die Service-UUID
`0x7336` aus dem Advertising kommen im gesamten Dekompilat nicht vor – die App nutzt
sie nicht.

**[Code]** Scan: `activity/DevicesActivity.java` → `SearchRequest.Builder().searchBluetoothLeDevice(…)`,
Zuordnung über den Namen (nicht über Service-UUID). Für BLE-Geräte (Protokoll 2)
überspringt `activity/PairActivity.java` das Bonding komplett (`deviceType == 2` →
direkt `startConnect()`), es gibt also **kein Pairing/Bonding und keine PIN**.

**[Code]** Verbindung: `activity/AddDeviceActivity.java` → `ClientManager.getClient().connect(…)`
mit `BleConnectOptions` (3 Connect-Retries, 20 s Timeout, 3 Service-Discovery-Retries,
10 s Timeout). Es wird **kein MTU-Request** gestellt → **[Abgeleitet]** alle Frames
müssen in die Default-ATT-Payload von 20 Byte passen (die größten Frames, "Alarm setzen" `05`
sowie die Antworten `F7`/`F8`, haben 15 Byte).

## 2. Framing

### 2.1 WL75 nutzt NICHT das TL100/WL90-Format

**[Code]** Es gibt zwei völlig verschiedene Wrapper:

- `devices/wl90/WL90Wrapper.java` – genutzt von `WL90Device`, `TL100Device`,
  `TL100NewDevice`. Format:
  `FE EF 0A <len+7> AB AA <len+2> <payload…> <chk> 55 0D 0A`
  (das ist das Format, das ha-beurer für die TL100 verwendet).
- `devices/wl75/WL75Wrapper.java` – genutzt **nur** von `WL75Devices`. Deutlich
  kürzer, **ohne** `0A`, **ohne** `AB AA`, **ohne** Trailer `55 0D 0A`.

### 2.2 WL75-Frame

**[Code]** `devices/wl75/WL75Wrapper.java` (sinngemäß): `wrap()` stellt `FE EF` und ein
Längenbyte voran und hängt eine Prüfsumme an; `madeCheckCode()` startet mit dem Längenbyte
und XOR-t alle Payload-Bytes hinein.

Aufbau:

    FE EF  LEN  CMD [ARGS…]  CHK
    LEN = Anzahl(CMD + ARGS) + 1      (zählt also Payload + Prüfsumme)
    CHK = LEN XOR CMD XOR ARG1 XOR …  (XOR über LEN und alle Payload-Bytes)

Gesamtlänge = Payload-Länge + 4.

### 2.3 Antworten / Notifications

**[Code]** `devices/wl75/WL75Resolver.java` → `resolver(byte[])`:

- sucht im Notification-Puffer nach `FE EF`,
- liest `LEN`, nimmt `LEN-1` Bytes als Payload,
- prüft `CHK` mit derselben XOR-Funktion (Seed = `LEN`),
- liefert eine Liste von Payloads (mehrere Frames pro Notification möglich).
- Unvollständige Frames werden verworfen, es gibt **kein Puffern über
  Notification-Grenzen hinweg** → **[Abgeleitet]** das Gerät schickt jedes Frame in
  einer einzigen Notification.

Antworten haben dasselbe Format wie Requests (`FE EF LEN RSP … CHK`). Die Zuordnung
erfolgt über das erste Payload-Byte (`payload[0]`, Response-Code) via
`devices/ObservableCenter.java` (`dispatch`).

### 2.4 Schreib-Semantik der App

**[Code]** `BluetoothActor.java` schreibt immer auf Service `14839AC4…` /
Characteristic `8B00ACE7…` über `ClientManager.getClient().write(…)` (BluetoothKit
`write`, nicht `writeNoRsp`; nur `writeCharacteristicWithNoRsp` in
`com/inuker/bluetooth/library/connect/BleConnectWorker.java` setzt explizit
`setWriteType(1)`). **[Abgeleitet]** Android verwendet dann den Default-Write-Type der
Characteristic; da diese laut Gerät nur write-without-response kann, gehen die Writes
effektiv ohne ATT-Response raus.

**[Abgeleitet]** Für eine Integration: auf `8B00ACE7` ohne Response schreiben
(z. B. bleak `write_gatt_char(..., response=False)`) und nach einem Schalten den
Status neu abfragen (`11` bzw. `16`), statt wie die App bei `E2 01`/`E7 01` nur
lokal zu toggeln.

Zwei Sendepfade:

- **[Code]** `devices/BluetoothDataReceiver.java`: sendet und wartet auf einen
  bestimmten Response-Code; Timeout 10 s (`WorkRequest.MIN_BACKOFF_MILLIS`), bis zu
  3 Wiederholungen.
- **[Code]** `devices/NoReturnDataReceiver.java`: fire-and-forget (verwendet für
  Helligkeit, Timer, Farbe, Szene, Lautstärke …). Das heißt **nicht**, dass das Gerät
  nicht antwortet – die App wartet nur nicht darauf. **[Offen]** ob das Gerät auf
  diese Befehle trotzdem eine Antwort schickt.

## 3. Verbindungsaufbau / Handshake

**[Code]** `activity/wl75/WL75MainActivity.java` (`initView` / `receiveSuccess`):

1. Notifications auf `0734594A-…` aktivieren (CCCD) – `ClientManager.getClient().notify(…)`.
2. Bei Erfolg `queryDeviceVersion()`: **GATT-Read** von `0x180A`/`0x2A28`
   (ASCII, z. B. `V1.39…`). `"V"` wird entfernt und mit `REPAIR_VERSION = "1.35"`
   verglichen (`utils/VersionUtils.versionComparison`). Ist die Version > 1.35, wird
   `IS_REPAIR_VERSION = true`.
   - **[Code]** Auswirkung nur in der UI: bei `IS_REPAIR_VERSION` werden Helligkeit,
     Timer und Farbe schon während des Ziehens des Sliders laufend gesendet, sonst
     erst beim Loslassen (`WL75LightActivity.updateSeekbarProgress`,
     `WL75MoonLightActivity` ColorPicker). **[Abgeleitet]** Firmware ≤ 1.35 kam mit
     schnellen Befehlsfolgen nicht klar. Am Protokoll ändert sich nichts.
   - **[Abgeleitet]** Die Lampe meldet SW V1.39.0518 → `IS_REPAIR_VERSION = true`.
3. **Permission/Handshake**: Payload `00 75` senden, Antwort `F0` erwarten.
   **[Code]** Ist `payload[1] != 0x75`, zeigt die App "device is not under control"
   (`R.string.device_is_not_under_control`), trennt die Verbindung und beendet sich.
4. Einstellungen abfragen: `01` → Antwort `F1` (`model/SettingInfo.build`). Die App
   kopiert die Payload immer in ein um ein Byte längeres Array mit abschließender `0`,
   bevor sie `SettingInfo.build` aufruft (ohne Längenprüfung). **[Abgeleitet]** Das
   deutet darauf hin, dass die Firmware nur `[1..4]` sendet und `fade` fehlt.
5. Ist in den Settings `time == 0` (Auto), Zeit synchronisieren: `03 …` → Antwort `F3`,
   danach weiter mit 6. Bei `time == 1` (Manual) direkt 6.
6. Alarm 1 abfragen (`04 01` → `F4`), dann Alarm 2 (`04 02` → `F4`). Danach ist der
   Startvorgang abgeschlossen.

**[Abgeleitet]** Minimal-Handshake für eine Integration: Notify an → `00 75` → auf
`F0 75` warten. Ob die Firmware ohne `00 75` Befehle ablehnt oder trennt, ist
**[Offen]**; die App sendet ihn aber immer als ersten Befehl.

## 4. Befehlstabelle (Requests)

**[Code]** `devices/wl75/WL75Bytes.java`. Spalte "Antwort" = Response-Code, auf den die
App wartet (aus den `mReceiver.write(…, code)`-Aufrufen in `activity/wl75/*`), bzw.
"–" für fire-and-forget.

| CMD | Funktion | Argumente | Antwort |
|---|---|---|---|
| `00` | Permission/Handshake | `75` | `F0` |
| `01` | Settings abfragen | – | `F1` |
| `02` | Settings setzen | display, date, time, feedbackFlag | `F2` |
| `03` | Uhrzeit setzen | sec, min, hour, day, month, year−2000 | `F3` |
| `04` | Alarm abfragen | id (1/2) | `F4` |
| `05` | Alarm setzen | id, min, hour, (enable<<7)\|days, tone, volume, snooze, wakeUp, sunrise, light | `F5` |
| `06` | Radio-Status | – | `F6` |
| `07` | Radio-Presets 1–5 | – | `F7` |
| `08` | Radio-Presets 6–10 | – | `F8` |
| `09` | Radio an/aus | 0/1 | `F9` |
| `0A` | Radio-Kanal (Preset) wählen | n (1–10) | `FA` |
| `0B` | Sendersuchlauf | dir (0/1) | `FB` |
| `0C` | Feinabstimmung | dir (0/1) | `FC` |
| `0D` | Radio-Lautstärke | 1–10 | – |
| `0E` | Radio-Sleeptimer an/aus | 0/1 | – |
| `0F` | Radio-Sleeptimer-Dauer | Minuten | – |
| `10` | Frequenz speichern | – | `E0` |
| `11` | **Licht-Status abfragen** | – | `E1` |
| `12` | **Licht an/aus** | 0/1 | `E2` |
| `13` | **Licht-Helligkeit** | 1–100 | – |
| `14` | Licht-Timer an/aus | 0/1 | – |
| `15` | Licht-Timer-Dauer | Minuten (1–60) | – |
| `16` | Stimmungslicht-Status | – | `E6` |
| `17` | Stimmungslicht an/aus | 0/1 | `E7` |
| `18` | Stimmungslicht-Helligkeit | 1–100 | – |
| `19` | Stimmungslicht-Timer an/aus | 0/1 | – |
| `1A` | Stimmungslicht-Timer-Dauer | Minuten (1–120) | – |
| `1B` | Stimmungslicht-Farbe | R, G, B | – |
| `1C` | Stimmungslicht-Szene | n (0–10) | – |
| `1D` | Sleep-Status | – | `ED` |
| `1E` | Sleep an/aus | 0/1 | `EE` |
| `1F` | Sleep-Konfig Licht | `01`, timer, light, brightness | – |
| `1F` | Sleep-Konfig Ton | `02`, tone, volume, fade (0/1) | – |

**[Code]** Schema der Response-Codes: Requests `00`–`0F` → `F0`–`FF`; `10` → `E0`;
`11`–`1F` → `E1`–`EF` (also `0xF0 | cmd` bzw. `0xE0 | (cmd & 0x0F)`).

Zusätzlich unaufgefordert vom Gerät:

- **[Code]** `B0 xx` – Timer abgelaufen; `xx`: `1` = Radio, `2` = Licht,
  `3` = Stimmungslicht, `4` = Sleep. Die App fragt daraufhin den jeweiligen Status
  neu ab (z. B. `WL75LightActivity`: `B0 02` → `queryLight()`).

Hinweis: `BeurerDeviceFactory.getMusicTimerEndCode()` liefert `0xEE`; das ist ein
App-interner Code (Musik-Player der App) und kollidiert zufällig mit der Antwort auf
`1E`.

## 5. Antwort-Layouts

Indizes beziehen sich auf die Payload (`[0]` = Response-Code).

| Code | Quelle | Layout |
|---|---|---|
| `F0` | `activity/wl75/WL75MainActivity.java` | `[1]` muss `0x75` sein |
| `F1` | `model/SettingInfo.build` | `[1]` display (0–3), `[2]` date (0 = 24h, 1 = 12h), `[3]` time (0 = Auto, 1 = Manual), `[4]` feedback (0 = an), `[5]` fade (optional) |
| `F4` | `model/AlarmInfo.build1` | `[1]` id (& 0x7F), `[2]` min, `[3]` hour, `[4]` bit7 = enable, bit0–6 = Tage, `[5]` tone, `[6]` volume, `[7]` snooze, `[8]` wakeUp, `[9]` sunrise, `[10]` light |
| `F5` | `activity/wl75/WL75AlarmDetailsActivity.java`, `WL75AlarmsActivity.java` | `[1] == 0` → Fehler |
| `F6` | `model/RadioInfo.build` | `[1]` an, `[2]` Kanal (1-basiert), `[3..4]` Frequenz big-endian in 0,1 MHz, `[5]` volume, `[6]` timer an, `[7]` timer-Minuten |
| `F7`/`F8` | `model/RadioInfo.buildwl75` | 5 × u16 big-endian Frequenzen (0,1 MHz) an `[1..10]` |
| `FB`/`FC` | `activity/wl75/WL75RadioActivity.java` | Frequenz an `[2..3]` |
| `E1` | `activity/wl75/WL75LightActivity.java` | `[1]` an (1/0), `[2]` Helligkeit, `[3]` Timer an, `[4]` Timer-Minuten |
| `E2` | `activity/wl75/WL75LightActivity.java` | `[1] == 1` → OK (App toggelt dann ihren lokalen Zustand) |
| `E6` | `activity/wl75/WL75MoonLightActivity.java` | `[1]` an (1/0; `0xFF` → App setzt Helligkeit 100), `[2]` Helligkeit, `[3]` Timer an, `[4]` Timer-Minuten, `[5..7]` R, G, B, `[8]` Szene |
| `E7` | `activity/wl75/WL75MoonLightActivity.java` | `[1] == 1` → OK; beim Einschalten nimmt die App Szene 2 (Rainbow) an |
| `ED` | `activity/wl75/SleepActivity.java` | `[1]` enable, `[2]` timer, `[3]` light, `[4]` brightness, `[5]` tone, `[6]` volume, `[7]` fadeout |

## 6. Wertebereiche

**[Code]** aus den Activities und `resources/res/values/arrays.xml`:

- **Hauptlicht:** Helligkeit 1–100 (Slider min 1), Timer 1–60 min (beim Einschalten
  setzt die UI 60).
- **Stimmungslicht:** Helligkeit 1–100, Timer 1–120 min, Szenen (`R.array.scenes`):
  0 = aus (feste Farbe), 1 Random, 2 Rainbow, 3 Rainbow Slow, 4 Fusion, 5 Pulse,
  6 Wave, 7 Chill, 8 Action, 9 Forest, 10 Summer. Bei Szene 5 ist der
  Helligkeits-Slider deaktiviert. Eine Farbwahl setzt die Szene in der App auf 0.
- **Alarm:** tone 1–8 (`wl75tones`: Buzzer, Nature, Bells, Classic, Passion,
  Morning lights, Joyful, Radio), volume 1–10, snooze-Index 1–6 = 1/2/5/10/20/30 min,
  wakeUp 0 = Off, 1 = Sunrise, 2 = Energizing Light, sunrise 2–60 min, light 1–100,
  Tage: bit0 = So, bit1 = Mo … bit6 = Sa, `0x7F` = täglich
  (`WL75ChooseDaysActivity.getDay`, `TimeUtils.getDayString`).
- **Radio:** volume 1–10, Sleeptimer 1–60 min (UI-Default 10), Frequenz in 0,1 MHz,
  Suchrichtung: Button "Down" sendet `0`, "Up" sendet `1` (Konstanten heißen
  `DIRECTION_NEXT = 0`, `DIRECTION_PERIOUS = 1` – Benennung widersprüchlich, **[Offen]**).
- **Sleep:** timer 1–60, brightness 10–100, volume 1–10, light 0 = Off, 1 = Sunset,
  2 = Mood, 3 = Relax; tone 0 = Off, 1 = Radio, 2 = Harmony, 3 = Relax,
  4 = Instrumental, 5 = Rain drops. Beim Einschalten setzt die App timer = 2.
- **Settings (`02`):** display 0–3, date 0 = 24h / 1 = 12h, time 0 = Auto /
  1 = Manual, 4. Byte = `!feedback ? 1 : 0`.

## 7. Beispiel-Frames

**[Abgeleitet]** Alle Frames mit der Wrapper-Logik aus 2.2 berechnet (Python-Nachbau
der XOR-Prüfsumme), **nicht am Gerät getestet**.

Handshake / Permission (Request und erwartete Antwort):

    -> FE EF 03 00 75 76
    <- FE EF 03 F0 75 86

Settings abfragen:

    -> FE EF 02 01 03

Licht-Status abfragen (Antwort `E1`, Beispiel: an, 50 %, Timer aus, 60 min):

    -> FE EF 02 11 13
    <- FE EF 06 E1 01 32 00 3C E8

Licht an / aus (Antwort `E2 01` = OK):

    -> FE EF 03 12 01 10      (an)
    -> FE EF 03 12 00 11      (aus)

Helligkeit setzen:

    -> FE EF 03 13 01 11      (1 %)
    -> FE EF 03 13 32 22      (50 %)
    -> FE EF 03 13 64 74      (100 %)

Licht-Timer:

    -> FE EF 03 14 01 16      (Timer an)
    -> FE EF 03 15 1E 08      (30 min)

Stimmungslicht:

    -> FE EF 02 16 14         (Status)
    -> FE EF 03 17 01 15      (an)
    -> FE EF 03 17 00 14      (aus)
    -> FE EF 05 1B FF 00 00 E1   (Farbe Rot)
    -> FE EF 03 1C 02 1D      (Szene Rainbow)

Sonstige Status-Abfragen:

    -> FE EF 03 04 01 06      (Alarm 1)
    -> FE EF 02 06 04         (Radio)
    -> FE EF 02 1D 1F         (Sleep)

Uhrzeit setzen (2026-10-17 12:34:56):

    -> FE EF 08 03 38 22 0C 11 0A 1A 1C

Prüfsummen-Nachbau:

    def wl75_frame(payload: bytes) -> bytes:
        n = len(payload) + 1
        chk = n
        for b in payload:
            chk ^= b
        return bytes([0xFE, 0xEF, n, *payload, chk])

## 8. Warum das TL100-Frame die Verbindung getrennt hat

Gesendet wurde `FE EF 0A 09 AB AA 04 30 01 35 55 0D 0A`.

- **[Code]** Das ist das `WL90Wrapper`-Format mit TL100-Befehl `0x30`. Die App
  verwendet dieses Format für die WL75 nie.
- **[Abgeleitet]** Aus Sicht eines WL75-Parsers ist das `FE EF`, `LEN = 0x0A`, also
  9 Payload-Bytes `09 AB AA 04 30 01 35 55 0D` und Prüfsumme `0A`. Erwartet wäre
  `0x0A ^ 09 ^ AB ^ AA ^ 04 ^ 30 ^ 01 ^ 35 ^ 55 ^ 0D = 0x5A` statt `0x0A`. Die
  Prüfsumme stimmt nicht, ein Parser wie der `WL75Resolver` der App würde das Frame
  verwerfen. Würde es trotzdem ausgewertet, wäre es `09 AB …` = "Radio an/aus" mit
  Müll-Argumenten – in keiner Lesart ein Licht-Befehl.
- **[Abgeleitet]** Zweite mögliche Ursache: der `00 75`-Handshake wurde vorher nicht
  gesendet.
- **[Offen]** Ob die Firmware bei ungültigen Frames oder bei fehlendem Handshake aktiv
  trennt, ist aus der App nicht ablesbar.

## 9. Offene Punkte

- Keine Live-Verifikation – alle Beispiel-Frames sind berechnet.
- Characteristics `ba04c4b2-…` und `e06d5efb-…` werden von der App nicht genutzt
  (evtl. OTA/Hersteller-Service).
- Ob Befehle ohne vorherigen `00 75` akzeptiert werden; Verhalten bei
  `F0`-Antwort ≠ `75` (App interpretiert das als "nicht unter Kontrolle", z. B. weil
  bereits ein anderes Gerät verbunden ist – **[Abgeleitet]**).
- Ob fire-and-forget-Befehle (`13`, `14`, `15`, `18`–`1C`, `0D`–`0F`, `1F`) vom Gerät
  trotzdem beantwortet werden.
- Bedeutung des optionalen `fade`-Bytes in `F1`.
- Ob `time` in den Settings nur die automatische Zeitsynchronisation durch die App
  steuert oder auch geräteseitige Bedeutung hat.
- Semantik der Suchrichtung bei `0B`/`0C`.
- Kein MTU-Request → Frames müssen ≤ 20 Byte sein (größtes bekanntes Frame: 15 Byte).

## 10. Verifikation am Gerät (2026-10-17)

WL75, FW V2.0.0518, HW V4, SW V1.39.0518, per bleak vom Mac (`tools/wl75_probe.py`).
Alle Antworten kamen jeweils in einer Notification, ~130–220 ms nach dem Write.

    -> FE EF 03 00 75 76                 <- FE EF 03 F0 75 86
    -> FE EF 02 01 03     (Settings)     <- FE EF 06 F1 00 00 00 01 F6
    -> FE EF 03 04 01 06  (Alarm 1)      <- FE EF 0C F4 01 00 07 BE 05 06 03 01 0A 50 1B
    -> FE EF 03 04 02 05  (Alarm 2)      <- FE EF 0C F4 02 2D 08 01 01 05 03 01 0A 50 82
    -> FE EF 02 06 04     (Radio)        <- FE EF 09 F6 00 05 03 6B 03 00 00 91
    -> FE EF 02 07 05     (Presets 1-5)  <- FE EF 0C F7 03 6B 03 6B 03 6B 03 6B 03 6B 93
    -> FE EF 02 08 0A     (Presets 6-10) <- FE EF 0C F8 03 6B 03 6B 03 6B 03 6B 03 6B 9C
    -> FE EF 02 11 13     (Licht)        <- FE EF 06 E1 00 51 00 0A BC
    -> FE EF 02 16 14     (Stimmung)     <- FE EF 0A E6 00 64 00 00 FF A4 00 02 D1
    -> FE EF 02 1D 1F     (Sleep)        <- FE EF 09 ED 00 02 01 63 00 06 01 83
    -> FE EF 03 12 01 10  (Licht an)     <- FE EF 03 E2 01 E0
    -> FE EF 03 12 00 11  (Licht aus)    <- FE EF 03 E2 01 E0

Dekodiert:

- `F1`: display 0, 24h, Zeit Auto, feedback-Byte 1. Nur 4 Datenbytes – das `fade`-Byte
  fehlt tatsächlich.
- Alarm 1: 07:00, `BE` = aktiv + Mo–Fr, Ton 5 (Passion), Lautstärke 6, Snooze-Index 3
  (5 min), Sunrise, 10 min, Licht 80 %.
- Alarm 2: 08:45, `01` = inaktiv, nur So, Ton 1, Lautstärke 5, Snooze 3, Sunrise 10 min, 80 %.
- Radio: aus, Kanal 5, 87,5 MHz, Lautstärke 3, Timer aus. Presets alle 87,5 MHz.
- Licht: aus, Helligkeit 81, Timer aus, 10 min. Nach `12 01`: `E1 01 51 …` → an.
- Stimmungslicht: aus, Helligkeit 100, Timer aus/0 min, RGB `FF A4 00`, Szene 2.
- Sleep: aus, Timer 2, Licht 1 (Sunset), Helligkeit 99, Ton 0 (aus), Lautstärke 6, Fadeout 1.

Ohne vorherigen `00 75` und mit TL100-Frame trennte die Lampe sofort (siehe Abschnitt 8);
mit WL75-Framing und Handshake blieb die Verbindung stabil.

## 11. Abgleich mit HCI-Mitschnitt der App (2026-10-17)

Android-Telefon, LightUp-App. Mitschnitt, Ablauf und extrahierte Frames liegen lokal in
`captures/` (nicht im Repo, enthält persönliche Daten). Die App-Befehle stimmen mit der
Befehlstabelle aus Abschnitt 4 überein. Neue Erkenntnisse:

- **Auch die "fire-and-forget"-Befehle werden beantwortet**, immer mit `<Antwortcode> 01`:
  `13` → `E3 01`, `1B` → `EB 01`, `1C` → `EC 01`, `0D` → `FD 01`, `1F` → `EF 01`.
  Damit hat jeder Befehl eine Antwort nach dem Schema aus Abschnitt 4.
- **Schnelle Befehlsfolgen bringen die Lampe durcheinander.** Beim Ziehen eines Sliders
  sendet die App Writes im Abstand von ~10–30 ms. Die Antworten kommen dann gebündelt
  (mehrere Frames pro Notification) und teilweise kaputt, z. B.
  `FE EF 03 E3 01 E1 FE EF 03 E3 01 E1 FE EF 03 FE EF`. Konsequenz für die Integration:
  Befehle serialisieren, auf die Antwort warten (Timeout), erst dann den nächsten senden;
  Parser muss auf `FE EF` resynchronisieren und Frames mit falscher Prüfsumme verwerfen.
- **Uhrzeit setzen** bestätigt: `03 1F 2D 11 11 0A 1A` = 17:45:31, 17.10.(20)26 → `F3 01`.
- **Alarm setzen** bestätigt: `05 01 00 07 BE 05 06 03 01 0A 50` (Alarm 1 auf 07:00,
  aktiv, Mo–Fr). Deaktivieren = gleiches Frame mit Tage-Byte `3E` (Bit 7 gelöscht).
  Antwort `F5 01`. Die App sendet immer den kompletten Alarm.
- **Sleep an/aus** bestätigt: `1E 01` / `1E 00` → `EE 01`.
- **Sleep-Konfig Ton:** `1F 02 00 06 01` = Ton aus, Lautstärke 6, Fade an → `EF 01`.
- **Sleep-Konfig Licht:** `1F 01 1A 01 63` → `EF 01`. Das zweite Byte (`1A` = 26) tauchte
  im Sleep-Status (`ED`) nicht auf, dort stand weiterhin `[2] = 02`. Geklärt in
  Abschnitt 14: Im Ruhezustand nimmt die Lampe die Sleep-Konfig nicht an.
- **Radio:** an/aus `09 01`/`09 00` → `F9 01`; Preset `0A 03`/`0A 04`/`0A 05` → `FA 01`;
  Lautstärke `0D 03` → `FD 01`. Status `F6 01 01 03 6B 07 00 00` = an, Kanal 1,
  87,5 MHz, Lautstärke 7, Timer aus.
- **Stimmungslicht:** Farbe `1B FF 08 00`, `1B 18 FF 00`, `1B 00 00 FF`, Szene `1C 02`.
  Während Szene 2 (Rainbow) läuft, liefert `E6[5..7]` die aktuelle Farbe des Effekts.
- Nach jedem Schalten (`12`, `17`, `1E`, `09`) fragt die App den Status erneut ab – so
  sollte es auch die Integration machen.

## 12. Live-Test Licht + Stimmungslicht (2026-10-17)

In einer Verbindung, je ~140 ms bis zur Antwort, vom Nutzer optisch bestätigt:
`00 75` → `12 01` → 2 s → `12 00` → `17 01` → `1B FF 00 00` (rot) → `1B 00 FF 00` (grün)
→ `1B 00 00 FF` (blau) → `17 00`. Alle mit `<Antwortcode> 01` quittiert.

- Ein Farbbefehl `1B` beendet den beim Einschalten aktiven Effekt (Szene 2) sofort,
  ein vorheriges `1C 00` ist nicht nötig.
- Bei ≥ 0,5 s Abstand zwischen den Befehlen kamen alle Antworten sauber einzeln.

## 13. Live-Test der Integrationsschicht (2026-10-17, 18:14)

`WL75Device` aus `custom_components/beurer_wl75/device.py` vom Mac gegen die Lampe,
ein Request gleichzeitig, jeweils ~130–180 ms bis zur Antwort, keine verstümmelten Frames.

- Helligkeit Hauptlicht `13 1e` / `13 64` → `E3 01`, Status danach `E1 01 1E …` bzw.
  `E1 01 64 …`.
- Helligkeit Stimmungslicht `18 1e` / `18 64` → `E8 01`, Status `E6 01 1E …`.
- **Szenen-Byte `E6[8]` ist zuverlässig:** Nach `1B FF 00 00` meldet die Lampe Szene `00`,
  nach `1C 09` Szene `09` (Farbe dann `00 FF 7E` = aktuelle Effektfarbe). Nach `17 00`
  bleibt die zuletzt aktive Szene im Status stehen.
- Zeit-Sync beim Verbinden: `03 2B 0E 12 11 0A 1A` = 18:14:43 → `F3 01`.
- Reconnect nach Idle-Trennung inkl. Handshake, Settings und Zeit-Sync: ~1,5 s
  (Mac-Bluetooth direkt, über einen ESP32-Proxy vermutlich etwas mehr).
- **[Offen]** Ob `17 01` immer Rainbow startet (so nimmt es die App an, Abschnitt 5) oder
  die zuletzt aktive Szene bzw. Farbe fortsetzt, ist nicht verifiziert. Die Integration
  liest nach dem Einschalten den Status und zeigt an, was die Lampe meldet.

## 14. Live-Test Wecker und Einschlaffunktion (2026-10-17, 19:00–19:20)

### Wecker

Über `WL75Device.modify_alarm` an Alarm 2 (inaktiv), danach mit dem gesicherten
Original-Frame zurückgeschrieben und byteidentisch zurückgelesen:

- Zeit 06:15, Samstag dazu, Ton 8 (Radio), Schlummern Index 4, Sonnenaufgang 30 min,
  Lautstärke 3, Helligkeit 55, Wecklicht 2 → `F4 02 0F 06 41 08 03 04 02 1E 37`.
  Jedes Feld kommt so zurück, wie es gesendet wurde.
- Sonnenaufgang 60 min wird angenommen (`…02 3C 37`), die Obergrenze 60 aus der App stimmt.
- Das ID-Byte hatte bei beiden Weckern nie Bit 7 gesetzt.
- Schlummer-Byte = Index 1–6 (1/2/5/10/20/30 min): `03` = 5 min.

### Einschlaffunktion

- **`1F` wird im Ruhezustand abgelehnt** (`EF 00`) und nur angenommen, während die
  Einschlaffunktion läuft. Die App schickt die Konfig deshalb nach `1E 01`.
- `1E 01` allein startet mit 2 min Dauer. **`1F 01 N …` startet den Countdown neu
  mit N Minuten**, auch mitten im Lauf. Gemessen: `1F 01 02 …` um 19:14:25, `B0 04` um
  19:16:25.
- `ED[2]` ist während des Laufs die **Restzeit** in Minuten. Sie wird mal ab-, mal
  aufgerundet: direkt nach `1F 01 02` steht `02`, zwei Sekunden später `01`.
- `ED[4]` ist während des Laufs die **aktuelle Helligkeit**, die Richtung Ende abnimmt
  (50 → 30 → 10 innerhalb von gut einer Minute).
- Nach dem Ende bzw. `1E 00` meldet `ED[2]` wieder `02`. Licht, Helligkeit, Ton,
  Lautstärke und Fade bleiben gespeichert (z. B. `ED 00 02 01 46 00 03 01`).
- Ende per Notification `B0 04`, solange eine Verbindung besteht.
- `1F 02 00 …` (Ton aus) wird angenommen.
- Während Sleep-Licht 1 (Sunset) oder 2 (Mood) läuft, melden Hauptlicht (`E1`) und
  Stimmungslicht (`E6[1]`) „aus“. Bei Mood ändern sich nur die Farbwerte in `E6[5..7]`.

Folgerungen für die Integration: Dauer und Einstellungen hält Home Assistant und sendet sie
bei jedem Start nach `1E 01`. Das Ende wird lokal mitgezählt und nach jedem gesendeten
`1F 01` neu gesetzt, ohne dafür eine Verbindung zu öffnen.
