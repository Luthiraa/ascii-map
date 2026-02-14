"""
Lightweight Mapbox Vector Tile (MVT) decoder.

Replaces the `mapbox-vector-tile` library (which pulls in shapely, pyclipper,
numpy, Cython, cmake, meson … and takes forever to compile).

Only decoding is implemented – encoding is not needed for ascii-map.

The output dict matches the format expected by ascii_map.py:
    {
        "layer_name": {
            "extent": 4096,
            "features": [
                {
                    "geometry": {"type": "Polygon", "coordinates": [...]},
                    "properties": {"class": "park", ...},
                },
                ...
            ],
        },
        ...
    }
"""

import struct

# ── Protobuf wire-format helpers (no external dependency) ────────────────

def _read_varint(buf, pos):
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ValueError("Truncated varint")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return result, pos
        shift += 7

def _read_sint(buf, pos):
    v, pos = _read_varint(buf, pos)
    return (v >> 1) ^ -(v & 1), pos

def _parse_message(buf, start=0, end=None):
    """Yield (field_number, wire_type, value, raw_bytes) tuples."""
    if end is None:
        end = len(buf)
    pos = start
    while pos < end:
        tag, pos = _read_varint(buf, pos)
        field = tag >> 3
        wtype = tag & 0x07
        if wtype == 0:  # varint
            val, pos = _read_varint(buf, pos)
            yield field, wtype, val, None
        elif wtype == 2:  # length-delimited
            length, pos = _read_varint(buf, pos)
            yield field, wtype, buf[pos : pos + length], None
            pos += length
        elif wtype == 5:  # 32-bit
            yield field, wtype, struct.unpack_from("<f", buf, pos)[0], None
            pos += 4
        elif wtype == 1:  # 64-bit
            yield field, wtype, struct.unpack_from("<d", buf, pos)[0], None
            pos += 8
        else:
            break  # skip unknown wire types


def _decode_packed_uint32(buf):
    """Decode a packed repeated uint32 field."""
    values = []
    pos = 0
    end = len(buf)
    while pos < end:
        v, pos = _read_varint(buf, pos)
        values.append(v)
    return values


# ── MVT geometry decoding ────────────────────────────────────────────────

_CMD_MOVE_TO = 1
_CMD_LINE_TO = 2
_CMD_CLOSE_PATH = 7

_GEOM_POINT = 1
_GEOM_LINESTRING = 2
_GEOM_POLYGON = 3


def _decode_geometry(geom_data, geom_type, extent, y_coord_down):
    """
    Decode MVT geometry commands into GeoJSON-style coordinates.
    """
    commands = _decode_packed_uint32(geom_data)
    idx = 0
    cx, cy = 0, 0
    rings = []
    current_ring = []

    while idx < len(commands):
        cmd_int = commands[idx]
        idx += 1
        cmd_id = cmd_int & 0x07
        cmd_count = cmd_int >> 3

        if cmd_id == _CMD_MOVE_TO:
            for _ in range(cmd_count):
                if idx + 1 >= len(commands):
                    break
                dx = (commands[idx] >> 1) ^ -(commands[idx] & 1)
                dy = (commands[idx + 1] >> 1) ^ -(commands[idx + 1] & 1)
                idx += 2
                cx += dx
                cy += dy
                if current_ring:
                    rings.append(current_ring)
                current_ring = [(cx, cy)]
        elif cmd_id == _CMD_LINE_TO:
            for _ in range(cmd_count):
                if idx + 1 >= len(commands):
                    break
                dx = (commands[idx] >> 1) ^ -(commands[idx] & 1)
                dy = (commands[idx + 1] >> 1) ^ -(commands[idx + 1] & 1)
                idx += 2
                cx += dx
                cy += dy
                current_ring.append((cx, cy))
        elif cmd_id == _CMD_CLOSE_PATH:
            if current_ring and len(current_ring) >= 2:
                current_ring.append(current_ring[0])
            if current_ring:
                rings.append(current_ring)
                current_ring = []

    if current_ring:
        rings.append(current_ring)

    if not y_coord_down:
        # Flip Y so it goes up (standard GeoJSON convention)
        rings = [[(x, extent - y) for x, y in ring] for ring in rings]

    # Format output based on geometry type
    if geom_type == _GEOM_POINT:
        points = []
        for ring in rings:
            points.extend(ring)
        if len(points) == 1:
            return {"type": "Point", "coordinates": points[0]}
        return {"type": "MultiPoint", "coordinates": points}

    elif geom_type == _GEOM_LINESTRING:
        if len(rings) == 1:
            return {"type": "LineString", "coordinates": rings[0]}
        return {"type": "MultiLineString", "coordinates": rings}

    elif geom_type == _GEOM_POLYGON:
        # Group rings into polygons (exterior + holes)
        polygons = []
        current_polygon = None
        for ring in rings:
            area = _signed_area(ring)
            if area >= 0:
                # Exterior ring (clockwise in screen coords = positive area)
                if current_polygon is not None:
                    polygons.append(current_polygon)
                current_polygon = [ring]
            else:
                # Hole (counter-clockwise)
                if current_polygon is None:
                    current_polygon = [ring]
                else:
                    current_polygon.append(ring)
        if current_polygon is not None:
            polygons.append(current_polygon)

        if len(polygons) == 1:
            return {"type": "Polygon", "coordinates": polygons[0]}
        return {"type": "MultiPolygon", "coordinates": polygons}

    return {"type": "Unknown", "coordinates": []}


def _signed_area(ring):
    """Compute signed area of a ring (shoelace formula)."""
    area = 0
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        area += ring[i][0] * ring[j][1]
        area -= ring[j][0] * ring[i][1]
    return area / 2.0


# ── MVT tile decoding ────────────────────────────────────────────────────

# Protobuf field numbers from the MVT specification
_TILE_LAYER = 3

_LAYER_NAME = 1
_LAYER_FEATURE = 2
_LAYER_KEY = 3
_LAYER_VALUE = 4
_LAYER_EXTENT = 5
_LAYER_VERSION = 15

_FEATURE_ID = 1
_FEATURE_TAGS = 2
_FEATURE_TYPE = 3
_FEATURE_GEOMETRY = 4

_VALUE_STRING = 1
_VALUE_FLOAT = 2
_VALUE_DOUBLE = 3
_VALUE_INT = 4
_VALUE_UINT = 5
_VALUE_SINT = 6
_VALUE_BOOL = 7


def _decode_value(data):
    """Decode a protobuf Value message."""
    for field, wtype, val, _ in _parse_message(data):
        if field == _VALUE_STRING:
            return val.decode("utf-8", errors="replace")
        elif field == _VALUE_FLOAT:
            return val
        elif field == _VALUE_DOUBLE:
            return val
        elif field == _VALUE_INT:
            return val
        elif field == _VALUE_UINT:
            return val
        elif field == _VALUE_SINT:
            return (val >> 1) ^ -(val & 1)
        elif field == _VALUE_BOOL:
            return bool(val)
    return None


def _decode_feature(data, keys, values, extent, y_coord_down):
    """Decode a single Feature message."""
    geom_type = _GEOM_POINT
    geom_data = b""
    tags_raw = b""
    properties = {}

    for field, wtype, val, _ in _parse_message(data):
        if field == _FEATURE_TYPE and wtype == 0:
            geom_type = val
        elif field == _FEATURE_GEOMETRY and wtype == 2:
            geom_data = val
        elif field == _FEATURE_TAGS and wtype == 2:
            tags_raw = val

    # Decode tags (alternating key/value indices)
    if tags_raw:
        tag_indices = _decode_packed_uint32(tags_raw)
        for i in range(0, len(tag_indices) - 1, 2):
            ki = tag_indices[i]
            vi = tag_indices[i + 1]
            if ki < len(keys) and vi < len(values):
                properties[keys[ki]] = values[vi]

    geometry = _decode_geometry(geom_data, geom_type, extent, y_coord_down)

    return {
        "geometry": geometry,
        "properties": properties,
    }


def _decode_layer(data, y_coord_down):
    """Decode a single Layer message."""
    name = ""
    keys = []
    values = []
    extent = 4096
    feature_datas = []

    for field, wtype, val, _ in _parse_message(data):
        if field == _LAYER_NAME and wtype == 2:
            name = val.decode("utf-8", errors="replace")
        elif field == _LAYER_KEY and wtype == 2:
            keys.append(val.decode("utf-8", errors="replace"))
        elif field == _LAYER_VALUE and wtype == 2:
            values.append(_decode_value(val))
        elif field == _LAYER_EXTENT and wtype == 0:
            extent = val
        elif field == _LAYER_FEATURE and wtype == 2:
            feature_datas.append(val)

    features = [
        _decode_feature(fd, keys, values, extent, y_coord_down)
        for fd in feature_datas
    ]

    return name, {"extent": extent, "features": features}


def decode(tile_bytes, default_options=None):
    """
    Decode MVT tile bytes into a dict of layers.

    Compatible with ``mapbox_vector_tile.decode()`` API.
    
    Options:
        y_coord_down (bool): If True, keep Y pointing down (default True).
    """
    if default_options is None:
        default_options = {}
    y_coord_down = default_options.get("y_coord_down", True)

    result = {}
    buf = bytes(tile_bytes) if not isinstance(tile_bytes, (bytes, bytearray)) else tile_bytes

    for field, wtype, val, _ in _parse_message(buf):
        if field == _TILE_LAYER and wtype == 2:
            name, layer = _decode_layer(val, y_coord_down)
            if name:
                result[name] = layer

    return result
