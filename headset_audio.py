"""Temporary Linux Bluetooth profiles, scoped to active Walkie recordings."""
import json
import subprocess
import threading
import time


def pactl(*args):
    result = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=1)
    result.check_returncode()
    return result.stdout.strip()


def address(node):
    prefix, _, rest = node.partition(".")
    if prefix not in ("bluez_input", "bluez_output", "bluez_card", "bluez_sink", "bluez_source"):
        return ""
    return rest.split(".")[0].replace(":", "_").upper()


def select_card(cards, mic, sink):
    candidates = []
    for card in cards:
        addr = address(card["name"])
        if not addr:
            continue
        props = card.get("properties", {})
        labels = [props.get(k) for k in ("device.description", "device.alias", "bluez.alias")]
        if mic:
            if address(mic) != addr and mic.casefold() not in [s.casefold() for s in labels if s]:
                continue
        elif address(sink) != addr:
            continue
        candidates.append(card)
    return candidates[0] if len(candidates) == 1 else None


def capture_profile(profile):
    return profile.replace("_", "-").startswith(("headset-head-unit", "handsfree-head-unit"))


class HeadsetAudio:
    def __init__(self, buttons, log):
        self.buttons = buttons
        self.log = log
        self.lock = threading.Lock()
        self.users = {}
        self.changed = {}
        self.closed = threading.Event()

    def prepare(self, owner, mic, headset="auto"):
        if self.closed.is_set():
            return mic
        with self.lock:
            if self.closed.is_set():
                return mic
            try:
                cards = json.loads(pactl("-f", "json", "list", "cards"))
                selected = mic
                if not selected and headset.lower() not in ("auto", "off", ""):
                    selected = headset.removesuffix(" (AVRCP)")
                card = select_card(cards, selected, "" if selected else pactl("get-default-sink"))
                if not card:
                    return mic
                name = card["name"]
                addr = address(name)
                profiles = card.get("profiles", {})
                profile = card["active_profile"]
                if capture_profile(profile) and name not in self.changed:
                    # Already in the headset profile (e.g. left over from a restart or crash):
                    # still return to A2DP afterwards, unless another app keeps recording.
                    a2dp = next((p for p in ("a2dp-sink", *sorted(profiles)) if p in profiles
                                 and p.startswith("a2dp") and profiles[p].get("available") != "no"),
                                None)
                    if a2dp:
                        self.changed[name] = (a2dp, profile)
                if not capture_profile(profile):
                    target = next((p for p in sorted(profiles) if capture_profile(p)
                                   and profiles[p].get("available") != "no"), None)
                    if not target:
                        return mic
                    pactl("set-card-profile", name, target)
                    self.changed[name] = (profile, target)
                self.users[owner] = name
                deadline = time.monotonic() + 3
                while not self.closed.is_set() and time.monotonic() < deadline:
                    for src in json.loads(pactl("-f", "json", "list", "sources")):
                        if address(src["name"]) == addr and not src["name"].endswith(".monitor"):
                            self.buttons.start()
                            return src["name"]
                    self.closed.wait(0.1)
            except (OSError, ValueError, subprocess.SubprocessError) as ex:
                self.log(f"Headset: {ex}")
            return mic

    def release(self, owner):
        with self.lock:
            self.users.pop(owner, None)
            self._restore()

    def _restore(self):
        if not self.users:
            self.buttons.stop()
        for name, (original, target) in list(self.changed.items()):
            if name in self.users.values():
                continue
            try:
                cards = json.loads(pactl("-f", "json", "list", "cards"))
                if any(c["name"] == name and c["active_profile"] == target for c in cards):
                    sources = json.loads(pactl("-f", "json", "list", "sources"))
                    ids = {s["index"] for s in sources if address(s["name"]) == address(name)}
                    streams = json.loads(pactl("-f", "json", "list", "source-outputs"))
                    if any(s["source"] in ids and not s.get("corked") for s in streams):
                        continue
                    pactl("set-card-profile", name, original)
                del self.changed[name]
            except (OSError, ValueError, subprocess.SubprocessError) as ex:
                self.log(f"Headset-Profil: {ex}")

    def retry(self):
        while not self.closed.wait(5):
            with self.lock:
                if self.changed:
                    self._restore()

    def close(self):
        self.closed.set()

        def finish():
            with self.lock:
                self.users.clear()
                self._restore()

        worker = threading.Thread(target=finish, daemon=True)
        worker.start()
        # The caller exits the process after cleanup. Allow time for the
        # bounded pactl calls and the button listener to release their devices.
        worker.join(timeout=10)
        if worker.is_alive():
            self.log("Zeitlimit bei der Freigabe des Headset-Profils erreicht")
