#!/usr/bin/env python3
"""Optical-drive inspection and a shell-owned mpv controller. Standard library only."""
import ctypes
import fcntl
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import time

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "omarchy-disc-deck"


def decode_mount(value):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)


def drive_path():
    for item in sorted(Path("/sys/class/block").glob("sr*")):
        if re.fullmatch(r"sr\d+", item.name):
            return item
    return None


def toc(fd):
    header = bytearray(2)
    fcntl.ioctl(fd, 0x5305, header)
    first, last = header
    if not 1 <= first <= last <= 99:
        raise ValueError("Invalid disc table of contents")
    entries = []
    for number in [*range(first, last + 1), 0xAA]:
        entry = bytearray(12)
        entry[0], entry[2] = number, 1  # CDROM_LBA; aligned address starts at byte 4
        fcntl.ioctl(fd, 0x5306, entry)
        entries.append((number, struct.unpack_from("=i", entry, 4)[0], bool(entry[1] & 0x40)))
    origin = entries[0][1]
    return [{"number": n, "title": f"Track {n:02d}", "start": (lba - origin) / 75,
             "duration": max(0, (entries[i + 1][1] - lba) / 75), "audio": not data}
            for i, (n, lba, data) in enumerate(entries[:-1])]


def probe():
    item = drive_path()
    state = dict(present=bool(item), path="", model="", kind="none", status="disconnected",
                 title="No drive connected", tracks=[], total=0, mountpoint="", error="")
    if item is None:
        return state
    path = "/dev/" + item.name
    vendor = (item / "device/vendor").read_text().strip()
    model = (item / "device/model").read_text().strip()
    state.update(path=path, model=f"{vendor} {model}", title="Insert a disc", status="empty")
    props = {}
    udev = Path("/run/udev/data/b" + (item / "dev").read_text().strip())
    if udev.exists():
        for line in udev.read_text().splitlines():
            if line.startswith("E:") and "=" in line:
                key, value = line[2:].split("=", 1)
                props[key] = value
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            status = fcntl.ioctl(fd, 0x5326, 0)  # CDSL_CURRENT
            if status != 4:
                state["status"] = {1: "empty", 2: "tray", 3: "reading"}.get(status, "empty")
                state["title"] = {"tray": "Tray is open", "reading": "Reading disc…"}.get(state["status"], "Insert a disc")
                return state
            disc_type = fcntl.ioctl(fd, 0x5327, 0)
            state.update(status="ready", kind="audio" if disc_type == 100 else "data")
            if disc_type in (100, 105):
                state["tracks"] = toc(fd)
                if any(t["audio"] for t in state["tracks"]):
                    state["kind"] = "audio" if disc_type == 100 else "mixed"
                state["total"] = sum(t["duration"] for t in state["tracks"])
            state["title"] = props.get("ID_FS_LABEL", "Audio CD" if state["kind"] == "audio" else "Data disc")
            state["title"] = state["title"].replace("_", " ")
            for line in Path("/proc/self/mountinfo").read_text().splitlines():
                left, _, right = line.partition(" - ")
                fields = right.split()
                if len(fields) > 1 and fields[1] == path:
                    state["mountpoint"] = decode_mount(left.split()[4])
                    break
        finally:
            os.close(fd)
    except PermissionError:
        state.update(status="error", error="Permission denied. Your session cannot access this drive.")
    except (OSError, ValueError) as exc:
        state.update(status="reading", title="Disc not ready", error=str(exc))
    return state


class Player:
    def __init__(self):
        self.process = None
        self.loaded = False
        self.volume = 65
        self.pending = None
        self.deadline = 0
        self.error = ""
        self.ipc = RUNTIME / "mpv.sock"
        self.log = None

    def commands(self, commands):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(0.6)
            client.connect(str(self.ipc))
            for i, command in enumerate(commands):
                client.sendall((json.dumps({"command": command, "request_id": i}) + "\n").encode())
            results, buffer = {}, b""
            while len(results) < len(commands):
                data = client.recv(65536)
                if not data:
                    raise OSError("Player closed its connection")
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    reply = json.loads(line)
                    if "request_id" in reply:
                        results[reply["request_id"]] = reply
            return [results[i] for i in range(len(commands))]

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.process = None
        self.loaded = False
        self.pending = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def start(self, state, index=0):
        tracks = state["tracks"]
        if state["kind"] not in ("audio", "mixed") or not tracks:
            raise ValueError("Insert an audio CD to play music.")
        if not 0 <= index < len(tracks) or not tracks[index]["audio"]:
            raise ValueError("This is not an audio track.")
        self.stop()
        self.error = ""
        self.ipc.unlink(missing_ok=True)
        self.log = (RUNTIME / "player.log").open("w")
        self.process = subprocess.Popen(["mpv", "--no-config", "--no-video", "--no-terminal",
            "--idle=yes", "--pause=yes", f"--volume={self.volume}",
            f"--input-ipc-server={self.ipc}", f"--cdda-device={state['path']}",
            f"--start=#{index + 1}", "cdda://"], stdout=self.log, stderr=self.log)
        self.pending = index
        self.deadline = time.monotonic() + 30

    def snapshot(self, state):
        out = dict(playing=False, loading=False, loaded=False, track=0, position=0, volume=self.volume)
        if self.process is None:
            return out
        if self.process.poll() is not None:
            self.error = "The player stopped. Check the disc and try again."
            self.stop()
            return out
        out["loading"] = self.pending is not None
        try:
            props = ["idle-active", "pause", "chapter", "time-pos", "volume"]
            replies = self.commands([["get_property", prop] for prop in props])
            data = {p: r.get("data") for p, r in zip(props, replies)}
            if not data["idle-active"] and data["time-pos"] is not None:
                self.loaded = True
                if self.pending is not None:
                    self.commands([["set_property", "pause", False]])
                    self.pending = None
                index = max(0, int(data["chapter"] or 0))
                tracks = state["tracks"]
                index = min(index, max(0, len(tracks) - 1))
                position = max(0, float(data["time-pos"]) - (tracks[index]["start"] if tracks else 0))
                self.volume = float(data["volume"] or 0)
                out.update(loaded=True, loading=False, playing=not data["pause"],
                           track=index, position=position, volume=self.volume)
            elif self.loaded:
                self.loaded = False
        except (OSError, ValueError):
            pass  # mpv IPC appears before the CD has finished loading.
        if self.pending is not None and time.monotonic() > self.deadline:
            self.error = "Could not read audio from this disc. Try reinserting it."
            self.stop()
            out["loading"] = False
        return out

    def action(self, request, state):
        action, value = request.get("action"), request.get("value")
        if action == "volume":
            self.volume = min(100, max(0, float(value)))
            if self.process and self.ipc.exists():
                self.commands([["set_property", "volume", self.volume]])
        elif action in ("play", "track"):
            index = int(value or 0)
            if action == "play" and self.loaded:
                self.commands([["cycle", "pause"]])
            elif self.loaded and action == "track":
                if not 0 <= index < len(state["tracks"]) or not state["tracks"][index]["audio"]:
                    raise ValueError("This is not an audio track.")
                self.commands([["set_property", "chapter", index], ["set_property", "pause", False]])
            elif self.pending is None:
                self.start(state, index)
        elif action in ("previous", "next"):
            if self.loaded:
                direction = -1 if action == "previous" else 1
                current = self.snapshot(state)["track"]
                target = min(len(state["tracks"]) - 1, max(0, current + direction))
                self.action({"action": "track", "value": target}, state)
        elif action == "seek":
            if self.loaded:
                current = self.snapshot(state)["track"]
                track = state["tracks"][current]
                seconds = track["start"] + min(0.999, max(0, float(value))) * track["duration"]
                self.commands([["seek", seconds, "absolute+exact"]])
        elif action == "stop":
            self.stop()
        elif action in ("eject", "close-tray", "open-files"):
            # Only the currently discovered optical device is accepted; no caller-supplied disk path.
            if not state["present"] or not Path(state["path"]).exists():
                raise ValueError("The optical drive is no longer connected.")
            if action == "open-files":
                if state["kind"] not in ("data", "mixed"):
                    raise ValueError("This disc has no data filesystem.")
                mount = state["mountpoint"]
                if not mount:
                    run_checked(["udisksctl", "mount", "--no-user-interaction", "-b", state["path"]])
                    mount = probe()["mountpoint"]
                if not mount:
                    raise ValueError("Could not find the mounted disc.")
                subprocess.Popen(["xdg-open", mount], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                self.stop()
                if state["mountpoint"]:
                    run_checked(["udisksctl", "unmount", "--no-user-interaction", "-b", state["path"]])
                run_checked(["eject", *( ["-t"] if action == "close-tray" else []), state["path"]])
        elif action != "refresh":
            raise ValueError("Unknown player action")
        self.error = ""


def run_checked(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError((result.stderr or result.stdout).strip() or "Drive operation failed")


def save_state(state):
    temp = RUNTIME / "state.tmp"
    temp.write_text(json.dumps(state))
    temp.replace(RUNTIME / "state.json")


def watch():
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Quickshell may instantiate the widget on multiple monitors. Exactly one owns mpv.
    lock = (RUNTIME / "owner.lock").open("w")
    running = True

    def shutdown(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    # Ensure the helper exits if its shell host dies unexpectedly.
    parent = os.getppid()
    ctypes.CDLL(None).prctl(1, signal.SIGTERM, 0, 0, 0)
    if os.getppid() != parent:
        return
    last = ""
    while running:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            try:
                raw = (RUNTIME / "state.json").read_text()
                if raw != last:
                    print(raw, flush=True)
                    last = raw
            except OSError:
                pass
            time.sleep(0.5)
    if not running:
        return
    control = RUNTIME / "control.sock"
    control.unlink(missing_ok=True)
    player = Player()
    state, scanned = probe(), time.monotonic()
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(control))
        os.chmod(control, 0o600)
        server.listen(8)
        try:
            while running:
                if time.monotonic() - scanned > 4:
                    try:
                        new = probe()
                        if (new["path"], new["kind"], new["tracks"]) != (state["path"], state["kind"], state["tracks"]):
                            player.stop()
                            player.error = ""
                        state = new
                    except OSError:
                        state = dict(state, present=False, tracks=[], kind="none")
                        player.stop()
                    scanned = time.monotonic()
                snapshot = dict(state, **player.snapshot(state))
                snapshot["error"] = player.error or state["error"]
                raw = json.dumps(snapshot)
                if raw != last:
                    save_state(snapshot)
                    print(raw, flush=True)
                    last = raw
                readable, _, _ = select.select([server], [], [], 0.5)
                if not readable:
                    continue
                client, _ = server.accept()
                with client:
                    client.settimeout(1)
                    try:
                        buffer = b""
                        while b"\n" not in buffer:
                            part = client.recv(4096)
                            if not part or len(buffer) > 8192:
                                raise ValueError("Invalid control request")
                            buffer += part
                        request = json.loads(buffer.split(b"\n", 1)[0])
                        # Recheck physical state before operations rather than trust the last poll.
                        if request.get("action") in ("play", "track", "eject", "close-tray", "open-files", "refresh"):
                            state, scanned = probe(), time.monotonic()
                        player.action(request, state)
                        client.sendall(b'{"ok":true}\n')
                    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
                        player.error = str(exc)
                        client.sendall((json.dumps({"ok": False, "error": str(exc)}) + "\n").encode())
        finally:
            player.stop()
            control.unlink(missing_ok=True)


def request(payload):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(20)
        client.connect(str(RUNTIME / "control.sock"))
        client.sendall((payload + "\n").encode())
        print(client.recv(8192).decode().strip())


if __name__ == "__main__":
    try:
        action = sys.argv[1] if len(sys.argv) > 1 else "probe"
        if action == "watch":
            watch()
        elif action == "probe":
            print(json.dumps(probe(), indent=2))
        elif action == "request":
            request(sys.argv[2])
        else:
            raise ValueError("Use probe, watch, or request <json>")
    except (OSError, ValueError, IndexError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)
