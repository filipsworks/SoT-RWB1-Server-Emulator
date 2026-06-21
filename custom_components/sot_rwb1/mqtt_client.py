"""MQTT bridge that impersonates the Solar-of-Things cloud to an RWB1 dongle.

Deployment model (spec §9)
──────────────────────────
The dongle is redirected (via local DNS) to the user's own MQTT broker instead
of ``hongkong.broker.mqtt.solar.siseli.com``.  This bridge connects to that
same broker as a *separate* client and plays the cloud's role:

* subscribes to ``dtu/<id>/pub/#`` to receive the dongle's telemetry,
* acks the dongle's ``dev_prop_post`` / ``dev_event_post`` pushes (the dongle
  only needs an ``e:0`` reply to stay happy — spec §9),
* issues ``dev_rpc`` requests to force fresh dumps and to read / write settings.

paho-mqtt runs its network loop on its own thread; everything that crosses back
into Home Assistant's event loop is marshalled via ``loop.call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import paho.mqtt.client as mqtt

from . import protocol
from .const import (
    CMD_DEV_EVENT_POST,
    CMD_DEV_PROP_POST,
    CMD_DEV_RPC,
    CMD_DTU_PROP_POST,
    I_RPC_DUMP,
    I_RPC_READWRITE,
    PUB_EVENT_DTU_PROP_POST,
    PUB_EVENT_EVENT_POST,
    PUB_EVENT_PROP_POST,
    PUB_SERVICE_RPC_REPLY,
    RPC_TIMEOUT,
    TOPIC_EVENT_POST_REPLY,
    TOPIC_PROP_POST_REPLY,
    TOPIC_PUB_WILDCARD,
    TOPIC_RPC_REQUEST,
)

_LOGGER = logging.getLogger(__name__)


class RWB1WriteError(Exception):
    """Raised when a setting write is rejected (NAK) or times out."""


class RWB1Bridge:
    """Owns the paho client and the decoded device state for one dongle."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        host: str,
        port: int,
        device_id: str,
        username: str | None,
        password: str | None,
        tls: bool = False,
    ) -> None:
        self._loop = loop
        self._host = host
        self._port = port
        self._device_id = device_id

        # Topics resolved once for this device.
        self._pub_wildcard = TOPIC_PUB_WILDCARD.format(device_id=device_id)
        self._pub_prefix = f"dtu/{device_id}/pub/"
        self._t_prop_reply = TOPIC_PROP_POST_REPLY.format(device_id=device_id)
        self._t_event_reply = TOPIC_EVENT_POST_REPLY.format(device_id=device_id)
        self._t_rpc_request = TOPIC_RPC_REQUEST.format(device_id=device_id)

        # Latest decoded telemetry + metadata, surfaced to the coordinator.
        self.state: dict[str, Any] = {"online": False}
        self.connected: bool = False

        # token -> Future, for correlating dev_rpc read/write replies.
        self._pending: dict[str, asyncio.Future] = {}

        # Notifier set by the coordinator (called on every state change).
        self._on_update: Callable[[dict[str, Any]], None] | None = None
        self._connect_future: asyncio.Future | None = None

        # Build the client, tolerating both paho 1.x and 2.x signatures.
        client_id = f"sot_rwb1_ha_{device_id}"
        try:
            self._client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1, client_id=client_id
            )
        except (AttributeError, TypeError):  # paho < 2.0
            self._client = mqtt.Client(client_id=client_id)

        if username:
            self._client.username_pw_set(username, password or "")
        if tls:
            self._client.tls_set()

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def set_update_callback(self, cb: Callable[[dict[str, Any]], None]) -> None:
        """Register the coordinator notifier (invoked on the HA loop)."""
        self._on_update = cb

    async def async_start(self) -> None:
        """Connect and start the network loop; wait for the first CONNACK."""
        self._connect_future = self._loop.create_future()
        try:
            self._client.connect_async(self._host, self._port, keepalive=60)
            self._client.loop_start()
            await asyncio.wait_for(self._connect_future, timeout=RPC_TIMEOUT)
        except asyncio.TimeoutError as err:
            self._client.loop_stop()
            raise ConnectionError(
                f"Timed out connecting to MQTT broker {self._host}:{self._port}"
            ) from err
        except OSError as err:
            self._client.loop_stop()
            raise ConnectionError(f"Cannot reach MQTT broker: {err}") from err

    async def async_stop(self) -> None:
        """Disconnect cleanly, then stop the network loop thread."""
        self._client.disconnect()
        await self._loop.run_in_executor(None, self._client.loop_stop)

    # ── paho callbacks (run on the paho network thread) ─────────────────────────

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            self.connected = True
            client.subscribe(self._pub_wildcard, qos=0)
            _LOGGER.info(
                "RWB1 %s: connected to broker, subscribed to %s",
                self._device_id, self._pub_wildcard,
            )
            self._loop.call_soon_threadsafe(self._resolve_connect, None)
            # Ask for a fresh dump right away so entities populate immediately.
            self.request_dump()
        else:
            _LOGGER.error("RWB1 %s: MQTT connect failed rc=%s", self._device_id, rc)
            self._loop.call_soon_threadsafe(
                self._resolve_connect, ConnectionError(f"CONNACK rc={rc}")
            )

    def _on_disconnect(self, client, userdata, rc) -> None:
        self.connected = False
        self.state["online"] = False
        _LOGGER.warning("RWB1 %s: disconnected (rc=%s)", self._device_id, rc)
        self._loop.call_soon_threadsafe(self._notify)

    def _on_message(self, client, userdata, msg) -> None:
        env = protocol.parse_envelope(msg.payload)
        if env is None:
            _LOGGER.debug("RWB1 %s: undecodable payload on %s", self._device_id, msg.topic)
            return
        suffix = msg.topic[len(self._pub_prefix):] if msg.topic.startswith(
            self._pub_prefix
        ) else msg.topic
        try:
            self._dispatch(suffix, env)
        except Exception:  # noqa: BLE001 — never let the paho thread die
            _LOGGER.exception("RWB1 %s: error handling %s", self._device_id, suffix)

    # ── Message dispatch ────────────────────────────────────────────────────────

    def _dispatch(self, suffix: str, env: dict[str, Any]) -> None:
        c = env.get("c")
        token = env.get("t")
        body = env.get("b") or {}

        if suffix == PUB_EVENT_PROP_POST or c == CMD_DEV_PROP_POST:
            self._ingest_telemetry(body)
            self._ack(self._t_prop_reply, env)
        elif suffix == PUB_EVENT_EVENT_POST or c == CMD_DEV_EVENT_POST:
            self.state["online"] = bool(body.get("ol", 1))
            self.state["last_event"] = body.get("ts")
            self._ack(self._t_event_reply, env)
            self._loop.call_soon_threadsafe(self._notify)
        elif suffix == PUB_EVENT_DTU_PROP_POST or c == CMD_DTU_PROP_POST:
            self._ingest_identity(body)
        elif suffix == PUB_SERVICE_RPC_REPLY or c == CMD_DEV_RPC:
            self._handle_rpc_reply(token, body)
        else:
            _LOGGER.debug("RWB1 %s: unhandled topic suffix %s", self._device_id, suffix)

    def _ingest_telemetry(self, body: dict[str, Any]) -> None:
        ct = body.get("ct")
        if not isinstance(ct, list):
            return
        values, unmatched = protocol.decode_ct(ct)
        if unmatched:
            _LOGGER.debug("RWB1 %s: unmatched channels %s", self._device_id, unmatched)
        if not values:
            return
        protocol.derive_binary_state(values)
        self.state.update(values)
        self.state["online"] = True
        if body.get("ts"):
            self.state["last_telemetry"] = body["ts"]
        self._loop.call_soon_threadsafe(self._notify)

    def _ingest_identity(self, body: dict[str, Any]) -> None:
        # dtu_prop_post (spec §4, c:21): md/sv/mc/ip/...
        self.state["identity"] = {
            "model": body.get("md"),
            "firmware": body.get("sv"),
            "mac": body.get("mc"),
            "ip": body.get("ip"),
        }
        self._loop.call_soon_threadsafe(self._notify)

    def _handle_rpc_reply(self, token: str | None, body: dict[str, Any]) -> None:
        # Two shapes: a full dump carries `ct`; a read/write reply carries `co`.
        if isinstance(body.get("ct"), list):
            self._ingest_telemetry(body)
            self._loop.call_soon_threadsafe(self._resolve_pending, token, None)
        elif "co" in body:
            self._loop.call_soon_threadsafe(self._resolve_pending, token, body["co"])

    # ── Reply / ack publishing ──────────────────────────────────────────────────

    def _ack(self, topic: str, request_env: dict[str, Any]) -> None:
        """Send a minimal ``e:0`` ack echoing the request token (spec §3/§4).

        Reply `i` is consistently request `i` + 1 across all observed pairs
        (101->102, 501->502, 503->504), so we apply that rule generically.
        """
        request_i = request_env.get("i")
        reply_i = (request_i + 1) if isinstance(request_i, int) else request_i
        reply = protocol.build_envelope(
            c=request_env.get("c", 0),
            body={},
            i=reply_i,
            token=request_env.get("t"),
            e=0,
        )
        self._client.publish(topic, protocol.encode_envelope(reply), qos=0)

    # ── Outbound requests ───────────────────────────────────────────────────────

    def request_dump(self) -> None:
        """Force a fresh full telemetry dump (empty-body dev_rpc, spec §6.6)."""
        env = protocol.build_envelope(CMD_DEV_RPC, body={}, i=I_RPC_DUMP)
        self._client.publish(
            self._t_rpc_request, protocol.encode_envelope(env), qos=0
        )

    async def async_write_setting(self, channel: str, value: str) -> None:
        """Send a dev_rpc write and await its ACK/NAK reply (spec §6.1).

        The JSON-level ``e`` is unreliable (always 0), so success is decided by
        the decoded ``co`` containing ``ACK`` vs ``NAK`` (spec §6.1).
        """
        ci = protocol.build_write_ci(channel, value)
        co = await self._async_rpc(ci)
        if protocol.co_is_nak(co):
            raise RWB1WriteError(
                f"{channel}={value!r} rejected by dongle (NAK): {protocol.decode_co(co)!r}"
            )
        if not protocol.co_is_ack(co):
            _LOGGER.warning(
                "RWB1 %s: write %s=%s got ambiguous reply %r",
                self._device_id, channel, value, protocol.decode_co(co),
            )

    async def async_read_setting(self, channel: str) -> str:
        """Send a dev_rpc read and return the decoded ``co`` text (spec §6.1)."""
        ci = protocol.build_read_ci(channel)
        co = await self._async_rpc(ci)
        return protocol.decode_co(co)

    async def _async_rpc(self, ci: str) -> str:
        """Publish a single-channel dev_rpc request and await the matching reply."""
        if not self.connected:
            raise RWB1WriteError("not connected to broker")
        token = protocol.gen_token()
        future: asyncio.Future = self._loop.create_future()
        self._pending[token] = future
        env = protocol.build_envelope(
            CMD_DEV_RPC,
            body={"ci": ci, "no": 0, "rs": 0},
            i=I_RPC_READWRITE,
            token=token,
        )
        self._client.publish(
            self._t_rpc_request, protocol.encode_envelope(env), qos=0
        )
        try:
            return await asyncio.wait_for(future, timeout=RPC_TIMEOUT)
        except asyncio.TimeoutError as err:
            raise RWB1WriteError(f"no reply within {RPC_TIMEOUT}s") from err
        finally:
            self._pending.pop(token, None)

    # ── HA-loop helpers ─────────────────────────────────────────────────────────

    def _resolve_connect(self, error: Exception | None) -> None:
        if self._connect_future and not self._connect_future.done():
            if error:
                self._connect_future.set_exception(error)
            else:
                self._connect_future.set_result(True)

    def _resolve_pending(self, token: str | None, co: str | None) -> None:
        future = self._pending.get(token)
        if future and not future.done():
            future.set_result(co)

    def _notify(self) -> None:
        if self._on_update:
            self._on_update(dict(self.state))
