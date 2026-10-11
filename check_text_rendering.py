#!/usr/bin/env python3
"""Exercise production text bindings in Qt, with a loopback image-request trap."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import zlib


def main():
    source = (Path(__file__).parent / "plugin/Panel.qml").read_text()
    bindings = (
        'root.state.model || "Optical drive"',
        'root.state.title || "Insert a disc"',
        'root.track ? root.track.title : ""',
        'row.modelData.title + (row.modelData.audio ? "" : " · Data")',
        'root.commandError || root.state.error || ""',
    )
    bodies = re.findall(r"\bText\s*\{([^{}]*)\}", source)
    components = []
    for index, binding in enumerate(bindings):
        matches = [body for body in bodies if f"text: {binding}\n" in body]
        if len(matches) != 1:
            raise AssertionError(f"Expected one production Text for {binding}")
        # Keep the complete production Text body and bindings; stub shell-only styling.
        body = matches[0]
        body = re.sub(r"Style\.font\.family", '"sans-serif"', body)
        body = re.sub(r"Style\.font\.\w+", "16", body)
        body = re.sub(r"Style\.space\((\d+)\)", r"\1", body)
        body = re.sub(r"Color\.\w+", '"red"', body)
        components.append(f"Text {{ id: label{index}; {body}\n}}")

    requests = []

    class Trap(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            def chunk(kind, data):
                return (struct.pack(">I", len(data)) + kind + data
                        + struct.pack(">I", zlib.crc32(kind + data)))
            image = (b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(b"\0\0\0\0"))
                     + chunk(b"IEND", b""))
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(image)))
            self.end_headers()
            self.wfile.write(image)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Trap) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        address = f"http://127.0.0.1:{server.server_port}"
        payload = f'<img src="{address}/payload.png">'
        control = f'<img src="{address}/control.png">'
        items = ", ".join(f"label{i}" for i in range(len(bindings)))
        qml = f"""import QtQuick
import QtTest
Item {{
    width: 640; height: 480
    QtObject {{
        id: root
        property string payload: ""
        property var state: ({{model: payload, title: payload, error: payload}})
        property var track: ({{title: payload}})
        property bool audio: true
        property color fg: "white"
        property color muted: "gray"
        property string commandError: ""
    }}
    QtObject {{
        id: row
        property var modelData: ({{title: root.payload, audio: true}})
        property bool selected: false
    }}
    {chr(10).join(components)}
    Text {{ id: automaticControl; text: "" }}
    TestCase {{
        name: "DiscDeckUntrustedText"
        when: windowShown
        function test_untrusted_strings() {{
            var labels = [{items}];
            var values = ["Audio CD", "日本語 & <b>literal</b>", {json.dumps(payload)}];
            for (var v = 0; v < values.length; ++v) {{
                root.payload = values[v];
                wait(500);
                for (var i = 0; i < labels.length; ++i) {{
                    compare(labels[i].text, values[v]);
                    compare(labels[i].textFormat, Text.PlainText);
                }}
            }}
            // Positive control: prove this Qt engine can fetch an automatic-format image.
            automaticControl.text = {json.dumps(control)};
            wait(1000);
        }}
    }}
}}
"""
        runner = "/usr/lib/qt6/bin/qmltestrunner"
        if not Path(runner).is_file():
            runner = shutil.which("qmltestrunner")
        if not runner:
            raise RuntimeError("Qt 6 qmltestrunner is required")
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                   QT_QPA_PLATFORMTHEME="generic", QT_QUICK_BACKEND="software",
                   QT_STYLE_OVERRIDE="Fusion")
        try:
            with tempfile.TemporaryDirectory(prefix="disc-deck-text-check-") as folder:
                test = Path(folder) / "tst_untrusted_text.qml"
                test.write_text(qml)
                result = subprocess.run([runner, "-input", str(test)], env=env, timeout=20)
                if result.returncode:
                    raise AssertionError("Production text rendering checks failed")
            assert "/control.png" in requests, "Image-request positive control did not fire"
            assert "/payload.png" not in requests, "Untrusted text caused an image request"
            print("Five production text bindings rendered literally; no payload image requests.")
            print("Automatic-format positive control requested its image as expected.")
        finally:
            server.shutdown()
            thread.join(timeout=2)


if __name__ == "__main__":
    main()
