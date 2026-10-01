import json
import os
import re
import shutil
import subprocess
from typing import Any

import pytest

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="needs node")

STUBS = """
const listeners = {};
const factories = {};
var window = { innerWidth: 1440, addEventListener() {}, dispatchEvent() {} };
var document = {
  elements: {},
  addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
  getElementById(id) { return document.elements[id] || null; },
  querySelectorAll() { return []; },
  documentElement: { classList: { add() {}, remove() {}, toggle() {} } },
};
class CustomEvent {
  constructor(type, init) { this.type = type; this.detail = init && init.detail; }
}
var htmx = { config: {} };
globalThis.Event = CustomEvent;
var Alpine = { data(name, fn) { factories[name] = fn; } };
var localStorage = { getItem() { return null; }, setItem() {} };
function fire(type, evt) { (listeners[type] || []).forEach((fn) => fn(evt)); }
"""


def _main_script(html: str) -> str:
    for body in re.findall(r"<script>(.*?)</script>", html, re.DOTALL):
        if 'Alpine.data("theme"' in body:
            return body
    raise AssertionError("main inline script not found")


def run_layout_js(html: str, probe: str, tz: str = "UTC") -> Any:
    """Run the layout's main inline script in node with DOM stubs, then `probe`.

    Returns the JSON of the last line `probe` prints.
    """
    script = STUBS + _main_script(html) + '\nfire("alpine:init");\n' + probe
    assert NODE is not None
    run = subprocess.run(
        [NODE, "-e", script],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "TZ": tz},
    )
    assert run.returncode == 0, run.stderr[-2000:]
    return json.loads(run.stdout.strip().splitlines()[-1])
