# Danfoss Icon for Home Assistant

Custom integration for Danfoss Icon floor heating, through the Icon **App module
(088U1101, Wi-Fi)**. It runs inside Home Assistant: no add-on, no MQTT broker,
no Java.

> **Status:** early. The cloud protocol layer is proven on DEVIreg Smart
> thermostats, and the Icon logic is ported from two working Java
> implementations, but this integration has only been tested against a
> simulated master controller so far. Reports from real systems are welcome:
> please attach the diagnostics download to issues.

## How it works

The Icon App module has no local API. The module and the Danfoss Icon app talk
through Danfoss's SecureDeviceGrid cloud relay. This integration joins your
house the same way another phone would: you generate a one-time code in the
app, Home Assistant pairs with the app, receives the master controller's ID,
and then connects to it. The master pushes changes, so there is no polling.

Things to know:

- **Pair with the Android app.** The iPhone app uses a different pairing
  protocol that is not supported. Any Android phone works for the pairing;
  you can uninstall the app afterwards.
- It depends on Danfoss's cloud. If their relay is down, so is this.
- Pairing creates a key that lives only in Home Assistant's config entry. If
  you remove the integration, pair again with a new code.
- The **Zigbee module (088U1130)** is not covered here. It works locally with
  Zigbee2MQTT or ZHA instead.

## Installation (HACS)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=v3nom&repository=ha-danfoss-icon&category=integration)

1. HACS > Integrations > ⋮ > Custom repositories, add
   `https://github.com/v3nom/ha-danfoss-icon` as *Integration*.
2. Install **Danfoss Icon** and restart Home Assistant.
3. Settings > Devices & services > Add integration > **Danfoss Icon**.
4. In the Danfoss Icon app on Android, open Settings > Share house, enter the
   code (with or without dashes), and keep the app open until pairing
   finishes.

Manual install: copy `custom_components/danfoss_icon` into your Home Assistant
`config/custom_components/` folder and restart.

Rooms appear a few seconds after setup, as the master reports them.

## Entities

Each room becomes its own device, linked to the master controller.

| Platform | Per room | House (master controller) |
| --- | --- | --- |
| Climate | Thermostat: *Auto* follows the weekly schedule, *Heat* holds a fixed temperature | |
| Sensor | Room temperature; floor temperature (rooms with a floor sensor); battery (wireless thermostats); schedule period (at home, away, asleep) | |
| Number | At home, away and asleep temperatures; minimum and maximum floor temperature (rooms with a floor sensor) | Vacation and pause temperatures |
| Binary sensor | Thermostat connection lost (diagnostic) | Cloud connection (diagnostic) |

Setting the climate entity's temperature changes the setpoint of the schedule
period that is active right now: in an *away* period it changes the away
temperature. The three setpoints are also available as number entities.

## Troubleshooting

- **Pairing says the code was rejected:** codes expire quickly. Generate a new
  one and enter it straight away, with the app still open.
- **Removed Home Assistant in the app, or entities stay unavailable:** open the
  integration's ⋮ menu > Reconfigure and pair again with a new code.
- **Debug logging:**
  ```yaml
  logger:
    logs:
      custom_components.danfoss_icon: debug
  ```

## Development

```bash
pip install pytest-homeassistant-custom-component PyNaCl
pytest
```

- `sdg/` is the SecureDeviceGrid client, vendored unchanged from
  [devireg-ha](https://github.com/infestdead/devireg-ha).
- `icon.py` is the master controller's message format, and `api.py` the
  house and room model.
- `tests/fake_sdg.py` simulates the grid and an Icon master over real
  sockets.

## Credits

- [OpenSDG](https://github.com/Sonic-Amiga/opensdg) and the openHAB Danfoss
  binding by Pavel Fedin (Sonic-Amiga), who reverse engineered the protocol.
- [devireg-ha](https://github.com/infestdead/devireg-ha) by infestdead, the
  Python port of the SDG client used here.
- [ha-danfoss](https://github.com/soundvibe/ha-danfoss) by soundvibe, the Java
  add-on whose Icon handling this ports.

## License

GPL-3.0, matching OpenSDG and devireg-ha. SecureDeviceGrid is proprietary
technology of Trifork; this project is not affiliated with Danfoss and is for
non-commercial use only.
