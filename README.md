# Beurer WL75 für Home Assistant

Custom Integration für das Beurer **WL75** Tageslichtwecker-Licht über Bluetooth Low
Energy. Funktioniert mit dem eingebauten Bluetooth-Adapter von Home Assistant und mit
ESPHome Bluetooth-Proxys.

## Funktionen

- Automatische Erkennung über Bluetooth (Name `WL75`)
- **Licht**: an/aus, Helligkeit
- **Stimmungslicht**: an/aus, Helligkeit, RGB-Farbe, 10 Effekte (Random, Rainbow,
  Rainbow Slow, Fusion, Pulse, Wave, Chill, Action, Forest, Summer)
- Stellt beim Verbinden die Uhr der Lampe auf die Home-Assistant-Zeit (wenn die Lampe auf
  automatische Zeit eingestellt ist)

Geplant: Wecker, Einschlaffunktion, Radio.

## Installation

[![In HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=paukul&repository=beurer-ha-bt&category=integration)

1. Über den Knopf oben das Repository in HACS öffnen und herunterladen (HACS muss
   installiert sein). Ohne HACS: `custom_components/beurer_wl75` nach
   `config/custom_components/` kopieren.
2. Home Assistant neu starten.
3. Die Lampe wird automatisch gefunden. Sonst:

   [![Integration hinzufügen](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=beurer_wl75)

Für ESPHome-Bluetooth-Proxys muss `bluetooth_proxy: active: true` gesetzt sein (bei den
fertigen Proxy-Firmwares ist das der Fall).
3. Die Lampe wird automatisch gefunden. Alternativ *Einstellungen → Geräte & Dienste →
   Integration hinzufügen → Beurer WL75*.

Die Lampe akzeptiert nur **eine** Bluetooth-Verbindung gleichzeitig. Die LightUp-App
muss also geschlossen sein, während Home Assistant mit der Lampe spricht. Die
Integration trennt die Verbindung nach 60 Sekunden ohne Befehl.

Standardmäßig fragt die Integration den Zustand nicht regelmäßig ab. Sie liest ihn nur beim
Start und nach eigenen Befehlen. Wer an der Lampe oder in der App schaltet, sieht das in Home
Assistant erst beim nächsten Befehl. In den Optionen der Integration lässt sich ein
Abfrageintervall in Minuten einstellen (0 = aus).

## Protokoll

Das BLE-Protokoll ist in [docs/wl75-protocol.md](docs/wl75-protocol.md) dokumentiert
und wurde am Gerät verifiziert (FW V2.0.0518). `tools/wl75_probe.py` ist ein kleines
Werkzeug zum Testen von Befehlen (`uv run tools/wl75_probe.py scan`).

## Entwicklung

```sh
uv sync
uv run pytest
```

## Danksagung

Inspiriert von [ha-beurer](https://github.com/Deadolus/ha-beurer) (MIT) von Sayyid
Sofwan und Simon Egli. Diese Integration ist eine Neuentwicklung für das abweichende
Protokoll der WL75.

Kein offizielles Produkt von Beurer; Beurer und LightUp sind Marken der Beurer GmbH.

---

*English:* Home Assistant custom integration for the Beurer WL75 wake-up light over
BLE (works with ESPHome Bluetooth proxies). Supports the main light (brightness) and the
mood light (RGB, brightness, effects). Close the LightUp app while using it – the lamp
accepts a single connection only.
