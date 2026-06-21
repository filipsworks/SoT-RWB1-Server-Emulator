# SoT-RWB1-Server-Emulator

A Home Assistant custom integration that talks to an **RWB1 solar DTU dongle**
(Easun SMT 4kW 24V, "Solar of Things" proto v18) **directly over your own MQTT
broker**, with no cloud account and no internet dependency.

Instead of letting the dongle phone home to
`hongkong.broker.mqtt.solar.siseli.com`, you point it at a broker you control.
This integration connects to that same broker, **impersonates the Solar-of-Things
cloud** (acks the dongle, decodes its telemetry, issues read/write commands),
and exposes everything as native Home Assistant entities.

The wire protocol was reverse-engineered via live MITM capture; see
`rwb1_protocol_spec.md` for the full specification. The decoder and the
write-command checksum in this integration are validated against the real
captured samples in that spec (the CRC and the `PCP0=2` write reproduce the
captured bytes exactly).

> ⚠️ This is unofficial, reverse-engineered, and incomplete. Only settings the
> spec marks as high-confidence and NAK-tested are exposed for writing.
> Settings with unconfirmed encodings (e.g. grid-connected power limit, CT zero
> power, output-priority values beyond SBU/SUB) are deliberately **omitted** to
> avoid misconfiguring the inverter.

---

## How it works

```
 ┌──────────┐   MQTT    ┌───────────────┐   MQTT    ┌────────────────────────┐
 │  RWB1    │ ───────▶  │  Your broker  │  ◀─────── │  Home Assistant         │
 │  dongle  │  pub/...  │  (Mosquitto)  │  sub/...  │  (this integration =    │
 │          │  ◀──────  │               │ ───────▶  │   the "cloud")          │
 └──────────┘   sub/... └───────────────┘   pub/... └────────────────────────┘
```

* The dongle **publishes** telemetry on `dtu/<id>/pub/...` and **subscribes**
  to commands on `dtu/<id>/sub/...`.
* This integration subscribes to `dtu/<id>/pub/#`, acks the dongle's pushes,
  and publishes `dev_rpc` requests onto `dtu/<id>/sub/...` to force fresh
  telemetry dumps and to read/write settings.

Telemetry is **push-based** (`local_push`); HA also nudges the dongle for a
fresh dump every couple of minutes so values never go stale between the
dongle's ~6-minute auto-pushes.

---

## Setup

### 1. Run your own MQTT broker

Any broker works (e.g. the Mosquitto add-on). The dongle authenticates with
`username = <DTU number>` and a 32-hex-char password (spec §1). Configure your
broker to accept that login (or allow anonymous on a trusted LAN). **The
integration uses its own client id**, so it never collides with the dongle.

### 2. Redirect the dongle to your broker

Point local DNS for `hongkong.broker.mqtt.solar.siseli.com` at your broker's IP
(e.g. via your router, Pi-hole, AdGuard, or a dnsmasq entry). The dongle
connects over plain MQTT on port 1883.

### 3. Add the integration

Copy `custom_components/sot_rwb1/` into your Home Assistant `config/custom_components/`
directory (or add this repo to HACS as a custom repository), restart, then
**Settings → Devices & Services → Add Integration → "RWB1 Solar DTU"** and fill in:

| Field          | Meaning                                                       |
|----------------|---------------------------------------------------------------|
| MQTT server    | Hostname/IP of your broker                                     |
| MQTT port      | Usually `1883`                                                 |
| DTU number     | The dongle's device id (the `<id>` in `dtu/<id>/...` topics)   |
| MQTT username  | Optional — defaults to the DTU number                         |
| MQTT password  | Your broker password for that user                            |
| Use TLS        | Optional, off by default                                      |

Setup only requires the **broker** to be reachable; the dongle can come online
later and entities will populate automatically.

---

## Entities

**Sensors** (decoded telemetry, spec §5): output voltage/frequency/apparent &
active power/load %, grid voltage/frequency/power, battery
voltage/SOC/charge & discharge current/cells-in-series, PV voltage/current/power,
inverter temperature, and today/week/year/total energy.

**Binary sensors**: solar charging switch, plus a dongle **Online** connectivity
sensor.

**Controls** (writes, spec §6.3) — charging voltages (bulk/float/recharge/
redischarge/low-alarm/cutoff), max charge currents, discharge limit, the BMS
SOC thresholds (validated as multiples of 5), equalization parameters, second-
output settings; **selects** for output-source priority, charger priority and
grid working range; **switches** for backlight, buzzer, equalization and dual
remote; and **buttons** for clear-fault and force-refresh.

> Settings have no reliable read-back in this protocol (they're bit-packed in
> shared frames the spec hasn't fully decoded — §6.5), so control entities are
> **optimistic**: they show the last value you successfully wrote and restore it
> across restarts. A write only "sticks" once the dongle ACKs it; a NAK surfaces
> as an error and leaves the value unchanged.

---

## Limitations / not yet implemented

Mirrors the open questions in `rwb1_protocol_spec.md §8`: grid-connected power
limit (`PGFP`) and CT zero power (`EZCTP`) encodings are unsolved; output-source
priority exposes only the verified SBU/SUB values; the homepage-return toggle
polarity is unconfirmed; battery type, ECO mode, rated voltage/frequency and the
auto-restart toggles lack confirmed dedicated channels. These are intentionally
left out rather than exposed with a guessed encoding.
