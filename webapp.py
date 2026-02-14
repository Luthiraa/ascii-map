import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from maps import ascii_map

START_LAT = 43.6446
START_LON = -79.3849
START_ZOOM = 13
START_WIDTH = 180
START_HEIGHT = 60
START_CELL_ASPECT = 0.6
HOST = "127.0.0.1"
PORT = 8000

HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ASCII Map</title>
  <style>
    :root {
      --bg: #101010;
      --panel: #171717;
      --border: #2a2a2a;
      --text: #e9e9e9;
      --muted: #9a9a9a;
      --accent: #87ceeb;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: radial-gradient(1200px 600px at 20%% -10%%, #202020, var(--bg));
      color: var(--text);
      font-family: "IBM Plex Mono", "Menlo", "Consolas", monospace;
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .bar {
      border-bottom: 1px solid var(--border);
      background: color-mix(in oklab, var(--panel) 92%%, black);
      padding: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .bar input {
      width: 95px;
      background: #0f0f0f;
      color: var(--text);
      border: 1px solid var(--border);
      padding: 6px;
      border-radius: 6px;
    }
    .bar button {
      background: #1f1f1f;
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 7px 10px;
      cursor: pointer;
    }
    .bar button:hover { border-color: #3c3c3c; }
    .map-wrap {
      padding: 10px;
      overflow: auto;
    }
    #map {
      margin: 0;
      white-space: pre;
      line-height: 1;
      font-size: 11px;
      color: var(--text);
      background: #0f0f0f;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
      display: inline-block;
      min-width: 100%%;
    }
    .status {
      color: var(--muted);
      margin-left: auto;
      font-size: 12px;
    }
    .hint {
      color: var(--accent);
      font-size: 12px;
      margin-left: 8px;
    }
  </style>
</head>
<body>
  <div class="bar">
    <button data-action="up">W / Up</button>
    <button data-action="left">A / Left</button>
    <button data-action="down">S / Down</button>
    <button data-action="right">D / Right</button>
    <button data-action="zoom_in">+</button>
    <button data-action="zoom_out">-</button>
    <button data-action="reset">Reset</button>
    <input id="lat" title="latitude" />
    <input id="lon" title="longitude" />
    <input id="zoom" title="zoom" type="number" step="1" min="%(min_zoom)s" max="%(max_zoom)s" />
    <input id="width" title="cols" />
    <input id="height" title="rows" />
    <input id="aspect" title="cell aspect" />
    <button id="apply">Render</button>
    <span class="hint">ASCII only. WSAD / arrows / +/-.</span>
    <span class="status" id="status">idle</span>
  </div>
  <div id="mapWrap" class="map-wrap"><pre id="map">Loading...</pre></div>
  <script>
    const MIN_ZOOM = %(min_zoom)s;
    const MAX_ZOOM = %(max_zoom)s;
    const MAX_ACTION_QUEUE = 32;
    const WHEEL_ZOOM_THRESHOLD = 40;
    const WHEEL_ZOOM_TICK_MS = 35;

    const state = {
      lat: %(lat)s,
      lon: %(lon)s,
      zoom: %(zoom)s,
      width: %(width)s,
      height: %(height)s,
      cell_aspect: %(cell_aspect)s,
      inFlight: false,
      queuedActions: []
    };

    const el = {
      mapWrap: document.getElementById("mapWrap"),
      map: document.getElementById("map"),
      status: document.getElementById("status"),
      lat: document.getElementById("lat"),
      lon: document.getElementById("lon"),
      zoom: document.getElementById("zoom"),
      width: document.getElementById("width"),
      height: document.getElementById("height"),
      aspect: document.getElementById("aspect"),
      apply: document.getElementById("apply")
    };

    function clamp(value, min, max) {
      return Math.min(max, Math.max(min, value));
    }

    function parseNumber(raw, fallback) {
      const parsed = Number(raw);
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    function parseIntClamped(raw, fallback, min, max) {
      return clamp(Math.round(parseNumber(raw, fallback)), min, max);
    }

    function syncInputs() {
      el.lat.value = state.lat.toFixed(6);
      el.lon.value = state.lon.toFixed(6);
      el.zoom.value = state.zoom;
      el.width.value = state.width;
      el.height.value = state.height;
      el.aspect.value = state.cell_aspect.toFixed(3);
    }

    function readInputs() {
      state.lat = parseNumber(el.lat.value, state.lat);
      state.lon = parseNumber(el.lon.value, state.lon);
      state.zoom = parseIntClamped(el.zoom.value, state.zoom, MIN_ZOOM, MAX_ZOOM);
      state.width = parseIntClamped(el.width.value, state.width, 1, 10000);
      state.height = parseIntClamped(el.height.value, state.height, 1, 10000);
      state.cell_aspect = parseNumber(el.aspect.value, state.cell_aspect);
    }

    function enqueueAction(action) {
      if (state.queuedActions.length >= MAX_ACTION_QUEUE) {
        state.queuedActions[state.queuedActions.length - 1] = action;
        return;
      }
      state.queuedActions.push(action);
    }

    function queueRender(action = "") {
      if (state.inFlight) {
        enqueueAction(action);
        return;
      }
      if (action === "zoom_in" && state.zoom >= MAX_ZOOM) return;
      if (action === "zoom_out" && state.zoom <= MIN_ZOOM) return;
      render(action);
    }

    async function render(action = "") {
      state.inFlight = true;
      el.status.textContent = "rendering...";
      try {
        const query = new URLSearchParams({
          lat: String(state.lat),
          lon: String(state.lon),
          zoom: String(state.zoom),
          width: String(state.width),
          height: String(state.height),
          cell_aspect: String(state.cell_aspect),
          action
        });
        const res = await fetch("/api/render?" + query.toString());
        const data = await res.json();
        state.lat = data.lat;
        state.lon = data.lon;
        state.zoom = clamp(data.zoom, MIN_ZOOM, MAX_ZOOM);
        state.width = data.width;
        state.height = data.height;
        state.cell_aspect = data.cell_aspect;
        el.map.textContent = data.text;
        el.status.textContent = "lat " + data.lat.toFixed(5) + " lon " + data.lon.toFixed(5) + " z " + data.zoom;
        syncInputs();
      } catch (err) {
        el.status.textContent = "error";
      } finally {
        state.inFlight = false;
        if (state.queuedActions.length > 0) {
          const nextAction = state.queuedActions.shift();
          queueRender(nextAction);
        }
      }
    }

    function zoomStatus(action) {
      if (action === "zoom_in" && state.zoom >= MAX_ZOOM) {
        el.status.textContent = "max zoom " + MAX_ZOOM;
        return false;
      }
      if (action === "zoom_out" && state.zoom <= MIN_ZOOM) {
        el.status.textContent = "min zoom " + MIN_ZOOM;
        return false;
      }
      return true;
    }

    function handleAction(action) {
      if (!action) return;
      readInputs();
      if ((action === "zoom_in" || action === "zoom_out") && !zoomStatus(action)) {
        syncInputs();
        return;
      }
      queueRender(action);
    }

    document.querySelectorAll("button[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        handleAction(btn.dataset.action || "");
      });
    });

    el.apply.addEventListener("click", () => {
      readInputs();
      queueRender("");
    });

    window.addEventListener("keydown", (ev) => {
      let action = "";
      if (ev.key === "w" || ev.key === "ArrowUp") action = "up";
      else if (ev.key === "a" || ev.key === "ArrowLeft") action = "left";
      else if (ev.key === "s" || ev.key === "ArrowDown") action = "down";
      else if (ev.key === "d" || ev.key === "ArrowRight") action = "right";
      else if (ev.key === "+" || ev.key === "=") action = "zoom_in";
      else if (ev.key === "-" || ev.key === "_") action = "zoom_out";
      if (!action) return;
      ev.preventDefault();
      handleAction(action);
    }, { passive: false });

    let wheelDelta = 0;
    let wheelTimer = null;

    function flushWheelZoom() {
      if (Math.abs(wheelDelta) < WHEEL_ZOOM_THRESHOLD) {
        clearInterval(wheelTimer);
        wheelTimer = null;
        wheelDelta = 0;
        return;
      }

      const action = wheelDelta > 0 ? "zoom_out" : "zoom_in";
      wheelDelta += wheelDelta > 0 ? -WHEEL_ZOOM_THRESHOLD : WHEEL_ZOOM_THRESHOLD;
      handleAction(action);
    }

    el.mapWrap.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      wheelDelta += ev.deltaY;
      if (!wheelTimer) {
        wheelTimer = setInterval(flushWheelZoom, WHEEL_ZOOM_TICK_MS);
      }
    }, { passive: false });

    syncInputs();
    queueRender("");
  </script>
</body>
</html>
""" % {
    "lat": START_LAT,
    "lon": START_LON,
    "zoom": START_ZOOM,
    "min_zoom": ascii_map.MIN_ZOOM,
    "max_zoom": ascii_map.MAX_ZOOM,
    "width": START_WIDTH,
    "height": START_HEIGHT,
    "cell_aspect": START_CELL_ASPECT,
}


def _float_arg(query, name, default):
    try:
        return float(query.get(name, [default])[0])
    except (TypeError, ValueError):
        return float(default)


def _int_arg(query, name, default):
    try:
        return int(query.get(name, [default])[0])
    except (TypeError, ValueError):
        return int(default)


def render_payload(query):
    lat = _float_arg(query, "lat", START_LAT)
    lon = _float_arg(query, "lon", START_LON)
    zoom = _int_arg(query, "zoom", START_ZOOM)
    zoom = max(ascii_map.MIN_ZOOM, min(zoom, ascii_map.MAX_ZOOM))
    width = _int_arg(query, "width", START_WIDTH)
    height = _int_arg(query, "height", START_HEIGHT)
    cell_aspect = _float_arg(query, "cell_aspect", START_CELL_ASPECT)
    action = query.get("action", [""])[0]

    if action == "reset":
        lat = START_LAT
        lon = START_LON
        zoom = START_ZOOM
    elif action == "zoom_in":
        zoom = min(zoom + 1, ascii_map.MAX_ZOOM)
    elif action == "zoom_out":
        zoom = max(zoom - 1, ascii_map.MIN_ZOOM)
    elif action in {"up", "down", "left", "right"}:
        lat, lon = ascii_map.pan(lat, lon, zoom, action, cell_aspect=cell_aspect)

    return ascii_map.render_ascii(
        lat=lat,
        lon=lon,
        zoom=zoom,
        width=width,
        height=height,
        cell_aspect=cell_aspect,
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/render":
            query = parse_qs(parsed.query)
            payload = render_payload(query)
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Not found")

    def log_message(self, format, *args):
        return


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"ASCII map server running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
