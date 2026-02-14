import math
from collections import OrderedDict

from maps import coords, render, tiles

TILE_SIZE = 256
MIN_ZOOM = 0
# OpenFreeMap returns empty vector tiles at z15+ for this style feed.
# Clamp to the highest useful level to avoid blank screens.
MAX_ZOOM = 14
DEFAULT_CELL_ASPECT = 0.6
WORLD_PX_PER_CELL_Y = 1.0
DEFAULT_PAN_STEP_CELLS = 10
MAX_TILE_CACHE = 512
TERRAIN_FILL_MAX_ZOOM = 14
GEOM_SIMPLIFY_ZOOM = 14
MAX_GEOM_POINTS = 220
LABEL_MIN_ZOOM = 13
MAX_LABEL_CANDIDATES = 600
MAX_LABEL_LEN = 26
ROAD_LABEL_PRIORITY = {
    "motorway": 0,
    "trunk": 1,
    "primary": 2,
    "secondary": 3,
    "tertiary": 4,
    "minor": 5,
    "service": 6,
    "residential": 6,
}
GLYPH_GREEN = "'"
GLYPH_WATER = "~"
GLYPH_WATERWAY = "|"
GLYPH_BUILDING = "#"
GLYPH_CENTER = "@"
ROAD_DEFAULT_CHAR = " "
ROAD_CLASS_TO_CHAR = {
    "motorway": "=",
    "trunk": "-",
    "primary": "+",
    "secondary": ";",
    "tertiary": ":",
    "minor": ".",
    "street": ".",
    "residential": ".",
    "bridge": "%",
    "rail": "x",
    "service": ",",
    "path": "`",
}
GREEN_LANDUSE_CLASSES = {
    "allotments",
    "cemetery",
    "farmland",
    "forest",
    "garden",
    "grass",
    "meadow",
    "nature_reserve",
    "orchard",
    "park",
    "pitch",
    "recreation_ground",
    "village_green",
    "wood",
}
GLYPH_LEGEND = "' green  ~ water  | waterway  # bldg  =-+;:.%x,` roads  @ center"

_tile_cache = OrderedDict()


def _cache_put(key, value):
    _tile_cache[key] = value
    _tile_cache.move_to_end(key)
    if len(_tile_cache) > MAX_TILE_CACHE:
        _tile_cache.popitem(last=False)


def tile_cache_size():
    return len(_tile_cache)


def get_decoded_tile(z, x, y):
    key = (z, x, y)
    if key in _tile_cache:
        _tile_cache.move_to_end(key)
        return _tile_cache[key]

    raw = tiles.fetch_tile(z, x, y)
    decoded = tiles.decode_tile(raw, z, x, y) if raw else {}
    _cache_put(key, decoded)
    return decoded


def normalize_view(lat, lon, zoom):
    zoom = max(MIN_ZOOM, min(int(zoom), MAX_ZOOM))
    wx, wy = coords.latlon_to_world_pixel(lat, lon, zoom, tile_size=TILE_SIZE)
    world_size = TILE_SIZE * (2**zoom)
    wx = wx % world_size
    wy = max(0.0, min(wy, float(world_size - 1)))
    lat, lon = coords.world_pixel_to_latlon(wx, wy, zoom, tile_size=TILE_SIZE)
    return lat, lon, zoom, wx, wy, world_size


def pan(lat, lon, zoom, direction, step_cells=DEFAULT_PAN_STEP_CELLS, cell_aspect=DEFAULT_CELL_ASPECT):
    lat, lon, zoom, wx, wy, world_size = normalize_view(lat, lon, zoom)
    move_x = step_cells * max(0.2, float(cell_aspect))
    move_y = step_cells * WORLD_PX_PER_CELL_Y

    if direction == "up":
        wy -= move_y
    elif direction == "down":
        wy += move_y
    elif direction == "left":
        wx -= move_x
    elif direction == "right":
        wx += move_x

    wx = wx % world_size
    wy = max(0.0, min(wy, float(world_size - 1)))
    return coords.world_pixel_to_latlon(wx, wy, zoom, tile_size=TILE_SIZE)


def render_ascii(lat, lon, zoom, width, height, cell_aspect=DEFAULT_CELL_ASPECT, show_street_names=False):
    width = max(20, min(int(width), 320))
    height = max(10, min(int(height), 140))
    cell_aspect = max(0.2, min(float(cell_aspect), 2.0))

    lat, lon, zoom, cam_wx, cam_wy, _ = normalize_view(lat, lon, zoom)
    view_world_w = width * cell_aspect
    view_world_h = height * WORLD_PX_PER_CELL_Y
    tl_wx = cam_wx - view_world_w / 2
    tl_wy = cam_wy - view_world_h / 2

    world_tiles = 2**zoom
    fb = render.Framebuffer(width, height)
    street_label_candidates = [] if show_street_names else None

    def world_to_screen(wx, wy):
        sx = int((wx - tl_wx) / cell_aspect)
        sy = int((wy - tl_wy) / WORLD_PX_PER_CELL_Y)
        return sx, sy

    def tile_point_to_screen(tx, ty, pt, extent):
        wx = tx * TILE_SIZE + (pt[0] / extent * TILE_SIZE)
        wy = ty * TILE_SIZE + (pt[1] / extent * TILE_SIZE)
        return world_to_screen(wx, wy)

    def simplify_points(points):
        if zoom < GEOM_SIMPLIFY_ZOOM or len(points) <= MAX_GEOM_POINTS:
            return points
        step = max(2, math.ceil(len(points) / MAX_GEOM_POINTS))
        sampled = points[::step]
        if sampled[-1] != points[-1]:
            sampled.append(points[-1])
        return sampled

    def normalize_label_text(raw):
        if raw is None:
            return ""
        text = " ".join(str(raw).split())
        text = text.encode("ascii", "ignore").decode("ascii")
        if not text:
            return ""
        if len(text) > MAX_LABEL_LEN:
            text = text[: MAX_LABEL_LEN - 3] + "..."
        return text

    def draw_polygon_layer(tile_data, layer_name, char, filled):
        if layer_name not in tile_data:
            return
        layer = tile_data[layer_name]
        extent = layer["extent"]
        for feature in layer["features"]:
            geo = feature["geometry"]
            gtype = geo["type"]
            if gtype == "Polygon":
                polygons = [geo["coordinates"]]
            elif gtype == "MultiPolygon":
                polygons = geo["coordinates"]
            else:
                continue

            for polygon in polygons:
                rings = []
                for ring in polygon:
                    simplified_ring = simplify_points(ring)
                    points = [tile_point_to_screen(tx, ty, pt, extent) for pt in simplified_ring]
                    if len(points) >= 3:
                        rings.append(points)
                if not rings:
                    continue
                if filled:
                    fb.draw_polygon_filled(rings, char, 0)
                else:
                    for ring in rings:
                        fb.draw_poly_outline(ring, char, 0)

    def draw_green_layer(tile_data):
        layer = tile_data.get("landuse") or tile_data.get("landcover")
        if not layer:
            return
        extent = layer["extent"]
        for feature in layer["features"]:
            props = feature.get("properties", {})
            if props.get("class") not in GREEN_LANDUSE_CLASSES:
                continue

            geo = feature["geometry"]
            gtype = geo["type"]
            if gtype == "Polygon":
                polygons = [geo["coordinates"]]
            elif gtype == "MultiPolygon":
                polygons = geo["coordinates"]
            else:
                continue

            for polygon in polygons:
                rings = []
                for ring in polygon:
                    simplified_ring = simplify_points(ring)
                    points = [tile_point_to_screen(tx, ty, pt, extent) for pt in simplified_ring]
                    if len(points) >= 3:
                        rings.append(points)
                if rings:
                    fb.draw_polygon_filled(rings, GLYPH_GREEN, 0)

    def draw_line_layer(layer, class_to_char, default_char):
        extent = layer["extent"]
        for feature in layer["features"]:
            geo = feature["geometry"]
            props = feature.get("properties", {})
            char = class_to_char.get(props.get("class", ""), default_char)
            if char == " ":
                continue
            if geo["type"] == "LineString":
                lines = [geo["coordinates"]]
            elif geo["type"] == "MultiLineString":
                lines = geo["coordinates"]
            else:
                continue

            for line in lines:
                simplified_line = simplify_points(line)
                points = [tile_point_to_screen(tx, ty, pt, extent) for pt in simplified_line]
                if len(points) >= 2:
                    fb.draw_poly_outline(points, char, 0)

    def collect_street_label_candidates(tile_data, out_candidates):
        if zoom < LABEL_MIN_ZOOM:
            return
        layer = tile_data.get("transportation_name")
        if not layer:
            return
        extent = layer.get("extent")
        if not extent:
            return

        for feature in layer.get("features", []):
            props = feature.get("properties", {})
            road_class = props.get("class")
            if road_class not in ROAD_LABEL_PRIORITY:
                continue

            text = normalize_label_text(props.get("name_en") or props.get("name"))
            if not text:
                continue

            geo = feature.get("geometry", {})
            gtype = geo.get("type")
            if gtype == "LineString":
                lines = [geo.get("coordinates", [])]
            elif gtype == "MultiLineString":
                lines = geo.get("coordinates", [])
            else:
                continue

            for line in lines:
                if len(line) < 2:
                    continue
                simplified_line = simplify_points(line)
                if not simplified_line:
                    continue
                mid = simplified_line[len(simplified_line) // 2]
                sx, sy = tile_point_to_screen(tx, ty, mid, extent)
                if sx < 0 or sx >= width or sy < 0 or sy >= height:
                    continue
                out_candidates.append((ROAD_LABEL_PRIORITY[road_class], sy, sx, text))
                if len(out_candidates) >= MAX_LABEL_CANDIDATES:
                    return

    def draw_street_labels(candidates):
        if not candidates:
            return
        max_labels = max(10, min(48, width // 4 + height // 3))
        occupied = [[False for _ in range(width)] for _ in range(height)]
        placed_names = set()
        placed = 0

        for _, y, x, text in sorted(candidates, key=lambda item: (item[0], item[1], item[2])):
            if text in placed_names:
                continue
            label_len = len(text)
            start_x = x - (label_len // 2)
            end_x = start_x + label_len - 1
            if start_x < 1 or end_x >= width - 1 or y < 1 or y >= height - 1:
                continue

            blocked = False
            for oy in range(max(0, y - 1), min(height, y + 2)):
                for ox in range(max(0, start_x - 1), min(width, end_x + 2)):
                    if occupied[oy][ox]:
                        blocked = True
                        break
                if blocked:
                    break
            if blocked:
                continue

            for i, ch in enumerate(text):
                fb.set_char(start_x + i, y, ch, 0)
            if start_x - 1 >= 0:
                fb.set_char(start_x - 1, y, " ", 0)
            if end_x + 1 < width:
                fb.set_char(end_x + 1, y, " ", 0)
            for oy in range(max(0, y - 1), min(height, y + 2)):
                for ox in range(max(0, start_x - 1), min(width, end_x + 2)):
                    occupied[oy][ox] = True
            placed_names.add(text)
            placed += 1
            if placed >= max_labels:
                break

    min_tx = math.floor(tl_wx / TILE_SIZE)
    max_tx = math.floor((tl_wx + view_world_w) / TILE_SIZE)
    min_ty = math.floor(tl_wy / TILE_SIZE)
    max_ty = math.floor((tl_wy + view_world_h) / TILE_SIZE)

    for tx in range(min_tx, max_tx + 1):
        for ty in range(min_ty, max_ty + 1):
            if ty < 0 or ty >= world_tiles:
                continue

            wrapped_tx = tx % world_tiles
            tile_data = get_decoded_tile(zoom, wrapped_tx, ty)
            if not tile_data:
                continue

            if zoom <= TERRAIN_FILL_MAX_ZOOM:
                draw_green_layer(tile_data)
                draw_polygon_layer(tile_data, "water", GLYPH_WATER, filled=True)
            draw_polygon_layer(tile_data, "water", GLYPH_WATER, filled=False)

            draw_polygon_layer(tile_data, "building", GLYPH_BUILDING, filled=False)

            road_layer = tile_data.get("road") or tile_data.get("transportation")
            if road_layer:
                draw_line_layer(
                    road_layer,
                    ROAD_CLASS_TO_CHAR,
                    ROAD_DEFAULT_CHAR,
                )

            if "waterway" in tile_data:
                draw_line_layer(tile_data["waterway"], {}, GLYPH_WATERWAY)
            if street_label_candidates is not None:
                collect_street_label_candidates(tile_data, street_label_candidates)

    if street_label_candidates is not None:
        draw_street_labels(street_label_candidates)
    fb.set_char(width // 2, height // 2, GLYPH_CENTER, 0)
    lines = [fb.get_row(y) for y in range(height)]
    return {
        "text": "\n".join(lines),
        "lat": lat,
        "lon": lon,
        "zoom": zoom,
        "width": width,
        "height": height,
        "cell_aspect": cell_aspect,
    }
