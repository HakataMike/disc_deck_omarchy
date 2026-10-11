#!/usr/bin/env python3
"""Focused checks for TOC arithmetic, optical-only operations, and real mpv IPC."""
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

spec = importlib.util.spec_from_file_location("deck", Path(__file__).parent / "plugin/disc_deck.py")
deck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deck)


class DiscChecks(unittest.TestCase):
    def test_toc_offsets_durations_and_data_track(self):
        def ioctl(fd, code, buffer):
            if code == 0x5305:
                buffer[:] = bytes([1, 3])
            else:
                lba = {1: 150, 2: 1650, 3: 3900, 170: 6900}[buffer[0]]
                if buffer[0] == 3:
                    buffer[1] = 0x40
                struct.pack_into("=i", buffer, 4, lba)
        with patch.object(deck.fcntl, "ioctl", side_effect=ioctl):
            tracks = deck.toc(10)
        self.assertEqual([t["start"] for t in tracks], [0, 20, 50])
        self.assertEqual([t["duration"] for t in tracks], [20, 30, 40])
        self.assertEqual([t["audio"] for t in tracks], [True, True, False])

    def test_no_device_does_not_execute_eject(self):
        player = deck.Player()
        with patch.object(deck, "run_checked") as run:
            with self.assertRaises(ValueError):
                player.action({"action": "eject"}, {"present": False})
            run.assert_not_called()

    def test_mount_path_with_spaces(self):
        self.assertEqual(deck.decode_mount(r"/media/My\040CD\134Folder"), "/media/My CD\\Folder")

    def test_real_mpv_transport(self):
        # Silent synthetic media exercises the same socket protocol without touching the tray.
        with tempfile.TemporaryDirectory(prefix="disc-deck-check-") as directory:
            base = Path(directory)
            wav = base / "source.wav"
            with wave.open(str(wav), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(8000)
                out.writeframes(b"\0\0" * 8000 * 12)
            metadata = base / "chapters.txt"
            metadata.write_text(";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=6000\ntitle=Track 01\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=6000\nEND=12000\ntitle=Track 02\n")
            media = base / "test.mka"
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-i", str(metadata),
                            "-map_metadata", "1", "-c:a", "pcm_s16le", str(media)], check=True)
            with patch.object(deck, "RUNTIME", base):
                player = deck.Player()
                player.process = subprocess.Popen(["mpv", "--no-config", "--ao=null", "--no-video",
                    "--no-terminal", "--idle=yes", "--pause=yes", f"--input-ipc-server={player.ipc}",
                    str(media)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                state = {"kind": "audio", "tracks": [
                    {"number": 1, "audio": True, "start": 0, "duration": 6},
                    {"number": 2, "audio": True, "start": 6, "duration": 6}]}
                try:
                    deadline = time.monotonic() + 5
                    while not player.snapshot(state)["loaded"] and time.monotonic() < deadline:
                        time.sleep(0.05)
                    self.assertTrue(player.loaded)
                    self.assertFalse(player.snapshot(state)["playing"])
                    player.action({"action": "play"}, state)
                    time.sleep(0.25)
                    self.assertTrue(player.snapshot(state)["playing"])
                    player.action({"action": "play"}, state)
                    self.assertFalse(player.snapshot(state)["playing"])
                    player.action({"action": "seek", "value": 0.5}, state)
                    time.sleep(0.1)
                    self.assertAlmostEqual(player.snapshot(state)["position"], 3, delta=0.2)
                    player.action({"action": "next"}, state)
                    time.sleep(0.1)
                    self.assertEqual(player.snapshot(state)["track"], 1)
                    player.action({"action": "previous"}, state)
                    time.sleep(0.1)
                    self.assertEqual(player.snapshot(state)["track"], 0)
                    player.action({"action": "volume", "value": 120}, state)
                    self.assertEqual(player.snapshot(state)["volume"], 100)
                finally:
                    player.stop()
                self.assertIsNone(player.process)


if __name__ == "__main__":
    unittest.main(verbosity=2)
