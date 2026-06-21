"""Constants for the RWB1 Solar DTU (local MQTT) integration.

This integration talks to an RWB1 solar dongle *directly* over the user's own
MQTT broker, impersonating the Solar-of-Things cloud.  Everything here is
derived from the reverse-engineered protocol spec (rwb1_protocol_spec.md).

IMPORTANT — value encodings differ from the Siseli cloud API.  The cloud uses
integer enum maps with its own ordering (e.g. SUB=0 / SBU=1); the *dongle*
protocol uses different single-digit enums (e.g. POP0: SBU=0 / SUB=1).  The
tables below are the dongle-side encodings, NOT the cloud ones.  The enum
*labels* are reused from the cloud integration only for UI familiarity.
"""

from __future__ import annotations

DOMAIN = "sot_rwb1"

# ─── Config-entry keys ─────────────────────────────────────────────────────────
CONF_HOST = "host"            # MQTT broker host (the user's own broker)
CONF_PORT = "port"            # MQTT broker port
CONF_DEVICE_ID = "device_id"  # the DTU number (numeric string in dtu/<id>/...)
CONF_USERNAME = "username"    # MQTT broker username (defaults to device_id)
CONF_PASSWORD = "password"    # MQTT broker password
CONF_TLS = "tls"              # use TLS for the broker connection

DEFAULT_PORT = 1883
DEFAULT_TLS = False

# How often (seconds) to nudge the dongle for a fresh full telemetry dump.
# The dongle also auto-pushes roughly every 6 minutes; pushes update state the
# moment they arrive, so this interval mainly bounds staleness on a quiet link.
DEFAULT_SCAN_INTERVAL = 120

# Seconds to wait for a dev_rpc reply (read / write ack) before giving up.
RPC_TIMEOUT = 15

# ─── MQTT topic structure (spec §2) ────────────────────────────────────────────
# The dongle PUBLISHES on .../pub/... and SUBSCRIBES on .../sub/...
# We are the "cloud": we subscribe to pub/# and publish onto sub/...
TOPIC_PUB_PREFIX = "dtu/{device_id}/pub"
TOPIC_SUB_PREFIX = "dtu/{device_id}/sub"

TOPIC_PUB_WILDCARD = "dtu/{device_id}/pub/#"

# Specific sub topics we publish onto.
TOPIC_PROP_POST_REPLY = "dtu/{device_id}/sub/event/dev_prop_post_reply"
TOPIC_EVENT_POST_REPLY = "dtu/{device_id}/sub/event/dev_event_post_reply"
TOPIC_RPC_REQUEST = "dtu/{device_id}/sub/service/dev_rpc"

# Pub topic suffixes we react to (matched against the trailing path).
PUB_EVENT_PROP_POST = "event/dev_prop_post"
PUB_EVENT_EVENT_POST = "event/dev_event_post"
PUB_SERVICE_RPC_REPLY = "service/dev_rpc_reply"
PUB_EVENT_DTU_PROP_POST = "event/dtu_prop_post"

# ─── JSON envelope command codes (spec §4) ─────────────────────────────────────
CMD_DEV_PROP_POST = 1      # dongle→cloud bulk telemetry push
CMD_DEV_EVENT_POST = 2     # dongle→cloud heartbeat/event
CMD_DEV_RPC = 5            # on-demand read / write / full-dump
CMD_DTU_PROP_POST = 21     # device identity handshake

# Envelope `i` bands (spec §4).  Reply `i` is consistently request `i` + 1.
I_RPC_READWRITE = 503      # single read/write request
I_RPC_DUMP = 501           # empty-body full-dump request


# ──────────────────────────────────────────────────────────────────────────────
# Telemetry decode — confirmed live blocks (spec §5)
# ──────────────────────────────────────────────────────────────────────────────
# The per-connection `cn` aliases are scrambled, so we identify each block by
# the structural shape of its decoded `co` text frame (see protocol.decode_frame)
# rather than by alias.  Each decoded value lands under the keys below and is
# surfaced as a sensor / binary_sensor.

# Sensor metadata for the decoded telemetry keys.
#   unit / device_class / state_class follow Home Assistant's SensorEntity.
SENSOR_DEFINITIONS: dict[str, dict] = {
    # ── Inverter output / load block (spec §5.2) ──────────────────────────
    "output_voltage": {
        "name": "Output Voltage", "unit": "V",
        "device_class": "voltage", "state_class": "measurement",
        "icon": "mdi:power-plug",
    },
    "output_frequency": {
        "name": "Output Frequency", "unit": "Hz",
        "device_class": "frequency", "state_class": "measurement",
    },
    "output_apparent_power": {
        "name": "Output Apparent Power", "unit": "VA",
        "device_class": "apparent_power", "state_class": "measurement",
    },
    "output_active_power": {
        "name": "Output Active Power", "unit": "W",
        "device_class": "power", "state_class": "measurement",
        "icon": "mdi:home-lightning-bolt",
    },
    "load_percent": {
        "name": "Load", "unit": "%", "state_class": "measurement",
        "icon": "mdi:gauge",
    },

    # ── Grid / mains input block (spec §5.2) ──────────────────────────────
    "grid_voltage": {
        "name": "Grid Voltage", "unit": "V",
        "device_class": "voltage", "state_class": "measurement",
        "icon": "mdi:transmission-tower",
    },
    "grid_frequency": {
        "name": "Grid Frequency", "unit": "Hz",
        "device_class": "frequency", "state_class": "measurement",
    },
    "grid_power": {
        "name": "Grid Power", "unit": "W",
        "device_class": "power", "state_class": "measurement",
        "icon": "mdi:transmission-tower-import",
    },

    # ── Battery block (spec §5.3) ─────────────────────────────────────────
    "battery_voltage": {
        "name": "Battery Voltage", "unit": "V",
        "device_class": "voltage", "state_class": "measurement",
        "icon": "mdi:battery",
    },
    "battery_soc": {
        "name": "Battery State of Charge", "unit": "%",
        "device_class": "battery", "state_class": "measurement",
    },
    "battery_charge_current": {
        "name": "Battery Charge Current", "unit": "A",
        "device_class": "current", "state_class": "measurement",
        "icon": "mdi:battery-arrow-up",
    },
    "battery_discharge_current": {
        "name": "Battery Discharge Current", "unit": "A",
        "device_class": "current", "state_class": "measurement",
        "icon": "mdi:battery-arrow-down",
    },
    "battery_count_series": {
        "name": "Battery Number In Series",
        "icon": "mdi:battery-sync",
    },

    # ── PV / solar input block (spec §5.1 Mpod) ───────────────────────────
    "pv_voltage": {
        "name": "PV Voltage", "unit": "V",
        "device_class": "voltage", "state_class": "measurement",
        "icon": "mdi:solar-power",
    },
    "pv_current": {
        "name": "PV Current", "unit": "A",
        "device_class": "current", "state_class": "measurement",
    },
    "pv_power": {
        "name": "PV Power", "unit": "W",
        "device_class": "power", "state_class": "measurement",
        "icon": "mdi:solar-power",
    },

    # ── Temperature (spec §5.1 V4W3, first field confirmed) ───────────────
    "inverter_temperature": {
        "name": "Inverter Temperature", "unit": "°C",
        "device_class": "temperature", "state_class": "measurement",
    },

    # ── Energy / cost counters (spec §5.1 COST) ───────────────────────────
    "energy_today": {
        "name": "Energy Today", "unit": "kWh",
        "device_class": "energy", "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "energy_week": {
        "name": "Energy This Week", "unit": "kWh",
        "device_class": "energy", "state_class": "total_increasing",
    },
    "energy_year": {
        "name": "Energy This Year", "unit": "kWh",
        "device_class": "energy", "state_class": "total_increasing",
    },
    "energy_total": {
        "name": "Energy Total", "unit": "kWh",
        "device_class": "energy", "state_class": "total_increasing",
        "icon": "mdi:counter",
    },
}

# Map of HA-friendly unit string → (device_class default, state_class default).
# sensor.py uses SENSOR_DEFINITIONS directly; this lives here for reuse/tests.
NUMERIC_UNITS: frozenset[str] = frozenset(
    {"V", "A", "W", "VA", "Hz", "%", "°C", "kWh"}
)

# ── Binary telemetry (decoded enum fields exposed as on/off) ──────────────────
# solarChargingSwitch: Mpod field 6, value "2" == "Open"/on (spec §5.1).
BINARY_SENSOR_DEFINITIONS: dict[str, dict] = {
    "solar_charging_switch": {
        "name": "Solar Charging Switch",
        "device_class": "running",
        "icon": "mdi:solar-power",
    },
}
# Raw value(s) that count as "on" for solar_charging_switch.
SOLAR_CHARGING_SWITCH_ON = {"2"}


# ──────────────────────────────────────────────────────────────────────────────
# Write channels (spec §6.3 / §7) — dongle-side channel name + value formatting
# ──────────────────────────────────────────────────────────────────────────────
# Only channels with high-confidence, NAK-tested encodings are exposed.  The
# spec flags several as unconfirmed (PGFP, EZCTP, POP0 enums 2/3, PD/PE+k
# polarity); those are deliberately omitted to avoid sending values the
# firmware would reject or that could misconfigure the inverter.

# Number settings.  Each entry drives one NumberEntity.
#   channel : dongle write-channel name (spec §6.3)
#   fmt     : value encoding — see protocol.format_value()
#       "v1"  -> one decimal,        e.g. 28.0  -> "28.0"
#       "v2"  -> two decimals,       e.g. 28.00 -> "28.00"
#       "i3"  -> 3-digit zero-pad,   e.g. 70    -> "070"
#       "i4"  -> 4-digit zero-pad,   e.g. 0     -> "0000"
#   step5   : if True, value must be a multiple of 5 (firmware-enforced, §6.4)
NUMBER_SETTING_DEFINITIONS: list[dict] = [
    {
        "channel": "PCVV", "key": "bulk_voltage", "name": "Bulk Charging Voltage",
        "fmt": "v1", "min": 24.0, "max": 30.0, "step": 0.1, "unit": "V",
        "device_class": "voltage", "icon": "mdi:battery-charging-high",
    },
    {
        "channel": "PBFT", "key": "float_voltage", "name": "Float Charging Voltage",
        "fmt": "v1", "min": 24.0, "max": 30.0, "step": 0.1, "unit": "V",
        "device_class": "voltage", "icon": "mdi:battery-heart",
    },
    {
        "channel": "PSLV", "key": "low_battery_alarm_voltage",
        "name": "Low Battery Alarm Voltage",
        "fmt": "v1", "min": 20.0, "max": 27.0, "step": 0.1, "unit": "V",
        "device_class": "voltage", "icon": "mdi:battery-alert",
    },
    {
        "channel": "PSDV", "key": "battery_cutoff_voltage",
        "name": "Battery Cutoff Voltage",
        "fmt": "v1", "min": 20.0, "max": 27.0, "step": 0.1, "unit": "V",
        "device_class": "voltage", "icon": "mdi:battery-off",
    },
    {
        "channel": "PBCV", "key": "battery_recharge_voltage",
        "name": "Battery Recharge Voltage",
        "fmt": "v1", "min": 24.0, "max": 28.0, "step": 0.1, "unit": "V",
        "device_class": "voltage", "icon": "mdi:transmission-tower-import",
    },
    {
        "channel": "PBDV", "key": "battery_redischarge_voltage",
        "name": "Battery Redischarge Voltage",
        "fmt": "v1", "min": 24.5, "max": 29.0, "step": 0.1, "unit": "V",
        "device_class": "voltage", "icon": "mdi:battery-check",
    },
    {
        "channel": "MUCHGC", "key": "max_utility_charge_current",
        "name": "Max Utility Charge Current",
        "fmt": "i3", "min": 2, "max": 100, "step": 1, "unit": "A",
        "device_class": "current", "icon": "mdi:transmission-tower-import",
    },
    {
        "channel": "MNCHGC", "key": "max_total_charge_current",
        "name": "Max Total Charge Current",
        # Firmware enforces a ceiling around 120 A (121 NAKed, spec §6.3).
        "fmt": "i3", "min": 10, "max": 120, "step": 1, "unit": "A",
        "device_class": "current", "icon": "mdi:battery-arrow-up",
    },
    {
        "channel": "DISCC", "key": "discharge_current_limit",
        "name": "Discharge Current Limit",
        "fmt": "i3", "min": 20, "max": 200, "step": 1, "unit": "A",
        "device_class": "current", "icon": "mdi:battery-arrow-down",
    },
    {
        "channel": "BMSSDC", "key": "bms_inverter_cutoff",
        "name": "BMS Inverter Cutoff SOC",
        "fmt": "i3", "min": 5, "max": 95, "step": 5, "unit": "%", "step5": True,
        "icon": "mdi:battery-arrow-down",
    },
    {
        "channel": "BMSSRC", "key": "inverter_startup_soc",
        "name": "Inverter Startup SOC",
        "fmt": "i3", "min": 5, "max": 100, "step": 5, "unit": "%", "step5": True,
        "icon": "mdi:battery-check",
    },
    {
        "channel": "BMSB2UC", "key": "restore_mains_charging_soc",
        "name": "Restore Mains-Charging SOC",
        "fmt": "i3", "min": 5, "max": 95, "step": 5, "unit": "%", "step5": True,
        "icon": "mdi:battery-charging-high",
    },
    {
        "channel": "BMSU2BC", "key": "restore_utility_discharging_soc",
        "name": "Restore Utility-Discharging SOC",
        "fmt": "i3", "min": 5, "max": 95, "step": 5, "unit": "%", "step5": True,
        "icon": "mdi:battery-charging-high",
    },
    {
        "channel": "PDSDS", "key": "parallel_shutdown_soc",
        "name": "Parallel Shutdown SOC",
        "fmt": "i3", "min": 5, "max": 95, "step": 5, "unit": "%", "step5": True,
        "icon": "mdi:battery-off",
    },
    {
        "channel": "PDSRS", "key": "second_output_restore_soc",
        "name": "Second Output Restore SOC",
        "fmt": "i3", "min": 5, "max": 100, "step": 5, "unit": "%", "step5": True,
        "icon": "mdi:battery-charging-50",
    },
    {
        "channel": "PDSRV", "key": "second_output_restore_voltage",
        "name": "Second Output Restore Voltage",
        "fmt": "v1", "min": 22.0, "max": 29.0, "step": 0.1, "unit": "V",
        "device_class": "voltage", "icon": "mdi:battery-charging-50",
    },
    {
        "channel": "PDDLYT", "key": "second_output_delay",
        "name": "Second Output Reconnect Delay",
        # 4 s NAKed; firmware minimum is 5 s (spec §6.3).
        "fmt": "i3", "min": 5, "max": 600, "step": 1, "unit": "s",
        "icon": "mdi:timer-outline",
    },
    {
        "channel": "PDDCGT", "key": "second_output_discharge_time",
        "name": "Second Output Discharge Time",
        # 4-digit field, unlike most other time settings (spec §6.3).
        "fmt": "i4", "min": 0, "max": 1440, "step": 1, "unit": "min",
        "icon": "mdi:timer-sand",
    },
    {
        "channel": "PBEQV", "key": "equalization_voltage",
        "name": "Equalization Voltage",
        # Two decimals, unlike the other voltage channels (spec §6.3).
        "fmt": "v2", "min": 24.0, "max": 30.0, "step": 0.1, "unit": "V",
        "device_class": "voltage", "icon": "mdi:battery-charging-high",
    },
    {
        "channel": "PBEQT", "key": "equalization_time", "name": "Equalization Time",
        "fmt": "i3", "min": 5, "max": 900, "step": 1, "unit": "min",
        "icon": "mdi:clock-outline",
    },
    {
        "channel": "PBEQOT", "key": "equalization_timeout",
        "name": "Equalization Timeout",
        "fmt": "i3", "min": 5, "max": 900, "step": 1, "unit": "min",
        "icon": "mdi:timer-outline",
    },
    {
        "channel": "PBEQP", "key": "equalization_interval",
        "name": "Equalization Interval",
        "fmt": "i3", "min": 0, "max": 90, "step": 1, "unit": "d",
        "icon": "mdi:calendar-repeat",
    },
]

# Select settings — dongle single-digit enums (spec §6.3).
#   options maps the UI label → the raw value string sent to the dongle.
SELECT_SETTING_DEFINITIONS: list[dict] = [
    {
        "channel": "POP0", "key": "output_source_priority",
        "name": "Output Source Priority",
        "icon": "mdi:transmission-tower",
        # Only SBU/SUB are verified; SUF/PEC (2/3) are unconfirmed (spec §8.4).
        "options": {
            "Solar+Battery First (SBU)": "0",
            "Solar First (SUB)": "1",
        },
    },
    {
        "channel": "PCP0", "key": "charger_priority",
        "name": "Charger Priority",
        "icon": "mdi:battery-sync",
        "options": {
            "Solar Only (OSO)": "0",
            "Solar + Utility (CSO)": "1",
            "Solar First (SNU)": "2",
            "Solar Residual (SOR)": "3",
        },
    },
    {
        "channel": "PGR0", "key": "grid_working_range",
        "name": "Grid Working Range",
        "icon": "mdi:sine-wave",
        "options": {
            "UPS": "0",
            "Appliance (APL)": "1",
        },
    },
]

# Switch settings.
#   "kind": "prefix" -> boolean encoded purely in the PD/PE name prefix
#           (spec §6.3): on -> "PE" + suffix, off -> "PD" + suffix.
#   "kind": "digit"  -> channel name + single/zero-padded digit value.
SWITCH_SETTING_DEFINITIONS: list[dict] = [
    {
        "kind": "prefix", "suffix": "x", "key": "lcd_backlight",
        "name": "LCD Backlight", "icon": "mdi:lightbulb",
    },
    {
        "kind": "prefix", "suffix": "a", "key": "buzzer",
        "name": "Buzzer", "icon": "mdi:bell-alert",
    },
    {
        "kind": "digit", "channel": "PBEQE", "on": "1", "off": "0",
        "key": "equalization_mode", "name": "Battery Equalization",
        "icon": "mdi:battery-heart-outline",
    },
    {
        "kind": "digit", "channel": "PDAULC", "on": "01", "off": "00",
        "key": "dual_remote_switch", "name": "Dual Remote Switch",
        "icon": "mdi:remote",
    },
]

# Button settings — fire-and-forget actions.
#   "fault" -> FAULTC clear-fault write (name-only, spec §6.3)
#   "refresh" -> force a fresh telemetry dump (empty-body dev_rpc, spec §6.6)
BUTTON_DEFINITIONS: list[dict] = [
    {
        "kind": "fault", "key": "clear_fault", "name": "Clear Fault",
        "icon": "mdi:alert-circle-check-outline",
    },
    {
        "kind": "refresh", "key": "refresh", "name": "Refresh Now",
        "icon": "mdi:refresh",
    },
]
