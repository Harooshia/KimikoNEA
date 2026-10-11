from collections import deque
import threading
import time

from flask import Flask, jsonify, request
from werkzeug.serving import make_server


class MinecraftEventService:

    def __init__(self):
        self.last_biome = None
        self.last_is_night = False
        self.last_packet_signature = None
        self.recent_events = deque(maxlen=200)
        self.event_counter = 0

    def reset(self):
        self.last_biome = None
        self.last_is_night = False
        self.last_packet_signature = None
        self.recent_events.clear()
        self.event_counter = 0

    def clean_biome(self, biome=None):
        if biome is None:
            return "Unknown"

        return biome.replace("minecraft:", "").replace("_", " ").title()

    def clean_dimension(self, dim=None):
        if dim is None:
            return "Unknown"

        return dim.replace("minecraft:", "").title()

    def describe_time(tick):
        if tick < 2000:
            return "sunrise"
        if tick < 6000:
            return "morning"
        if tick < 12000:
            return "afternoon"
        if tick < 13000:
            return "sunset"
        if tick < 18000:
            return "night"
        if tick < 22000:
            return "late night"
        return "approaching sunrise"

    def describe_weather(rain=None, thunder=None):
        if thunder:
            return "a thunderstorm"
        if rain:
            return "rain"
        return "clear weather"

    def detect_night_start(self, daytime):
        now_is_night = daytime >= 13000
        if now_is_night and not self.last_is_night:
            self.last_is_night = True
            return True
        if not now_is_night:
            self.last_is_night = False
        return False

    def detect_biome_change(self, biome):
        if self.last_biome is None:
            self.last_biome = biome
            return False
        if biome != self.last_biome:
            self.last_biome = biome
            return True
        return False

    def packet_signature(self, packet):
        keys = (
            "biome",
            "dimension",
            "daytime",
            "is_raining",
            "is_thundering",
            "elytra_flying",
            "underwater",
            "passenger",
            "on_ground",
            "players_online",
            "health",
            "food",
            "reason",
            "message"
        )
        return tuple(packet.get(key) for key in keys)

    def add_event(self, kind, text):
        self.event_counter += 1
        event = {
            "id": self.event_counter,
            "kind": kind,
            "text": (text or "").strip(),
            "timestamp": time.time()
        }
        self.recent_events.append(event)
        return event

    def build_companion_event_text(
        self,
        packet,
        biome_changed=False,
        night_started=False
    ):
        cues = []

        if biome_changed:
            cues.append(
                f"entered {self.clean_biome(packet.get('biome'))}"
            )

        if night_started:
            cues.append("night just started")

        health = packet.get("health")
        food = packet.get("food")

        if isinstance(health, (int, float)) and health <= 6:
            cues.append("player is hurt")
        if isinstance(food, (int, float)) and food <= 6:
            cues.append("player is hungry")
        if packet.get("underwater"):
            cues.append("player is underwater")
        if packet.get("elytra_flying"):
            cues.append("player is flying")
        reason = packet.get("reason")

        if reason == "chat" and packet.get("message"):
            cues.append(
                f'player said "{packet.get("message")}"'
            )
        elif reason == "low_health":
            cues.append("player took heavy damage")

        elif reason == "low_food":
            cues.append("player needs food")

        elif reason == "death":
            cues.append("player died")

        if not cues:
            cues.append("world state changed")

        return (
            "Minecraft world context. "
            f"Current cues: {', '.join(cues)}."
        )
    def build_event_updates(self, packet):
        biome = packet.get("biome")

        daytime = int(
            packet.get("daytime", 0) or 0
        )

        biome_changed = self.detect_biome_change(biome)

        night_started = self.detect_night_start(daytime)

        signature = self.packet_signature(packet)

        changed = signature != self.last_packet_signature

        self.last_packet_signature = signature

        if not changed and not biome_changed and not night_started:
            return []

        if night_started:
            event_kind = "night_start"
        else:
            event_kind = "companion_update"

        return [
            (
                event_kind,
                self.build_companion_event_text(
                    packet,
                    biome_changed,
                    night_started
                )
            )
        ]

def create_app(service=None):

    if service is None:
        service = MinecraftEventService()

    app = Flask(__name__)

    @app.route("/logs", methods=["POST"])
    def logs():

        packet = request.json or {}

        updates = service.build_event_updates(packet)

        events = []

        for kind, text in updates:
            event = service.add_event(kind, text)
            events.append(event)

        if events:
            response_text = events[-1]["text"]
        else:
            response_text = "No significant change detected."

        return jsonify({
            "status": "ok",
            "response": response_text,
            "events": events
        })

    @app.route("/events/recent", methods=["GET"])
    def events_recent():

        after_id = request.args.get(
            "after_id",
            default=0,
            type=int
        )

        events = []

        for event in service.recent_events:
            if int(event.get("id", 0)) > after_id:
                events.append(event)

        return jsonify({
            "status": "ok",
            "events": events
        })

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "status": "ok"
        })

    return app


class MinecraftEventServer:

    def __init__(
        self,
        host="127.0.0.1",
        port=5001
    ):
        self.host = host
        self.port = port

        self.service = MinecraftEventService()

        self.app = create_app(self.service)

        self._thread = None
        self._http_server = None

    def is_running(self):

        return (
            self._thread is not None
            and self._thread.is_alive()
        )

    def start(self):

        if self.is_running():
            return

        self.service.reset()

        self._http_server = make_server(
            self.host,
            self.port,
            self.app
        )

        self._thread = threading.Thread(
            target=self._http_server.serve_forever,
            daemon=True
        )

        self._thread.start()

    def stop(self):

        if self._http_server is not None:

            self._http_server.shutdown()

            self._http_server.server_close()

            self._http_server = None

        if self._thread is not None:

            self._thread.join(timeout=2)

            self._thread = None


if __name__ == "__main__":

    server = MinecraftEventServer(
        host="0.0.0.0",
        port=5001
    )

    print("Minecraft AI Companion server running...")

    server.start()

    try:

        while True:
            time.sleep(1)

    except KeyboardInterrupt:

        server.stop()
