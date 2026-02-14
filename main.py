import curses
import locale
import sys
import warnings

import urllib3

from maps import ascii_map

locale.setlocale(locale.LC_ALL, "")
urllib3.disable_warnings()
warnings.filterwarnings("ignore")

START_LAT = 43.6446
START_LON = -79.3849
START_ZOOM = 13
DEFAULT_CELL_ASPECT = 0.6
APP_TITLE = "ASCII MAP EXPLORER"
MIN_MAP_COLS = 20
MIN_MAP_ROWS = 10


def _float_arg(name, default):
    token = f"--{name}="
    for arg in sys.argv:
        if arg.startswith(token):
            try:
                return float(arg.split("=", 1)[1])
            except ValueError:
                return float(default)
    return float(default)


def _int_arg(name, default):
    token = f"--{name}="
    for arg in sys.argv:
        if arg.startswith(token):
            try:
                return int(arg.split("=", 1)[1])
            except ValueError:
                return int(default)
    return int(default)


def run_dump_mode():
    lat = _float_arg("lat", START_LAT)
    lon = _float_arg("lon", START_LON)
    zoom = _int_arg("zoom", START_ZOOM)
    width = _int_arg("width", 160)
    height = _int_arg("height", 50)
    aspect = _float_arg("aspect", DEFAULT_CELL_ASPECT)
    result = ascii_map.render_ascii(
        lat=lat,
        lon=lon,
        zoom=zoom,
        width=width,
        height=height,
        cell_aspect=aspect,
        show_street_names=True,
    )
    with open("map.txt", "w") as f:
        f.write(result["text"] + "\n")


def init_color_attrs():
    attrs = {}
    ui = {
        "title": curses.A_BOLD,
        "meta": curses.A_DIM,
        "hint": curses.A_BOLD,
        "border": curses.A_DIM,
    }
    if not curses.has_colors():
        return attrs, ui

    try:
        curses.start_color()
        curses.use_default_colors()
    except curses.error:
        return attrs, ui

    color_pairs = {
        1: (curses.COLOR_BLUE, -1),      # water
        2: (curses.COLOR_CYAN, -1),      # waterway/rail
        3: (curses.COLOR_WHITE, -1),     # buildings
        4: (curses.COLOR_RED, -1),       # motorway
        5: (curses.COLOR_MAGENTA, -1),   # trunk/bridge
        6: (curses.COLOR_YELLOW, -1),    # primary
        7: (curses.COLOR_GREEN, -1),     # green + secondary roads
        8: (curses.COLOR_WHITE, -1),     # local roads
        9: (curses.COLOR_CYAN, -1),      # title
        10: (curses.COLOR_WHITE, -1),    # subtle ui
        11: (curses.COLOR_YELLOW, -1),   # hints
    }

    for pair_id, (fg, bg) in color_pairs.items():
        try:
            curses.init_pair(pair_id, fg, bg)
        except curses.error:
            pass

    attrs = {
        ascii_map.GLYPH_GREEN: curses.color_pair(7) | curses.A_DIM,
        ascii_map.GLYPH_WATER: curses.color_pair(1) | curses.A_BOLD,
        ascii_map.GLYPH_WATERWAY: curses.color_pair(2),
        ascii_map.GLYPH_BUILDING: curses.color_pair(3) | curses.A_BOLD,
        "=": curses.color_pair(4) | curses.A_BOLD,
        "-": curses.color_pair(5) | curses.A_BOLD,
        "+": curses.color_pair(6) | curses.A_BOLD,
        ";": curses.color_pair(7),
        ":": curses.color_pair(7) | curses.A_DIM,
        ".": curses.color_pair(8) | curses.A_DIM,
        "%": curses.color_pair(5) | curses.A_BOLD,
        "x": curses.color_pair(2) | curses.A_BOLD,
        ",": curses.color_pair(8) | curses.A_DIM,
        "`": curses.color_pair(8),
        ascii_map.GLYPH_CENTER: curses.color_pair(11) | curses.A_BOLD,
    }
    ui = {
        "title": curses.color_pair(9) | curses.A_BOLD,
        "meta": curses.color_pair(10) | curses.A_DIM,
        "hint": curses.color_pair(11) | curses.A_BOLD,
        "border": curses.color_pair(10) | curses.A_DIM,
    }
    return attrs, ui


def _safe_add(stdscr, y, x, text, limit, attr=0):
    if limit <= 0:
        return
    max_y, max_x = stdscr.getmaxyx()
    if y < 0 or y >= max_y or x < 0 or x >= max_x:
        return
    max_len = min(limit, max_x - x)
    if max_len <= 0:
        return
    try:
        stdscr.addnstr(y, x, text, max_len, attr)
    except curses.error:
        pass


def draw_colored_line(stdscr, y, x_offset, line, max_cols, char_attrs):
    x = 0
    line_len = min(len(line), max_cols)
    while x < line_len:
        ch = line[x]
        attr = char_attrs.get(ch, 0)
        run_start = x
        x += 1
        while x < line_len and char_attrs.get(line[x], 0) == attr:
            x += 1
        segment = line[run_start:x]
        _safe_add(stdscr, y, x_offset + run_start, segment, len(segment), attr)


def draw_frame(stdscr, top, left, width, height, attr=0):
    if width < 2 or height < 2:
        return
    horizontal = "-" * max(0, width - 2)
    _safe_add(stdscr, top, left, f"+{horizontal}+", width, attr)
    for y in range(top + 1, top + height - 1):
        _safe_add(stdscr, y, left, "|", 1, attr)
        _safe_add(stdscr, y, left + width - 1, "|", 1, attr)
    _safe_add(stdscr, top + height - 1, left, f"+{horizontal}+", width, attr)


def main(stdscr):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.nodelay(True)
    stdscr.timeout(30)
    stdscr.keypad(True)
    char_attrs, ui_attrs = init_color_attrs()

    lat = START_LAT
    lon = START_LON
    zoom = START_ZOOM
    cell_aspect = DEFAULT_CELL_ASPECT
    show_street_names = True

    while True:
        height, width = stdscr.getmaxyx()
        max_cols = max(1, width)

        key = stdscr.getch()
        if key == ord("q"):
            break
        if key == ord("r"):
            lat, lon, zoom = START_LAT, START_LON, START_ZOOM
        elif key in (ord("+"), ord("=")):
            zoom = min(zoom + 1, ascii_map.MAX_ZOOM)
        elif key in (ord("-"), ord("_")):
            zoom = max(zoom - 1, ascii_map.MIN_ZOOM)
        elif key in (ord("["),):
            cell_aspect = max(0.25, cell_aspect - 0.05)
        elif key in (ord("]"),):
            cell_aspect = min(1.5, cell_aspect + 0.05)
        elif key in (ord("n"), ord("N")):
            show_street_names = not show_street_names
        elif key in (curses.KEY_UP, ord("w"), ord("W")):
            lat, lon = ascii_map.pan(lat, lon, zoom, "up", cell_aspect=cell_aspect)
        elif key in (curses.KEY_DOWN, ord("s"), ord("S")):
            lat, lon = ascii_map.pan(lat, lon, zoom, "down", cell_aspect=cell_aspect)
        elif key in (curses.KEY_LEFT, ord("a"), ord("A")):
            lat, lon = ascii_map.pan(lat, lon, zoom, "left", cell_aspect=cell_aspect)
        elif key in (curses.KEY_RIGHT, ord("d"), ord("D")):
            lat, lon = ascii_map.pan(lat, lon, zoom, "right", cell_aspect=cell_aspect)

        if height < 8 or width < 32:
            stdscr.erase()
            _safe_add(stdscr, 0, 0, "Terminal too small. Resize to at least 32x8. Press q to quit.", max_cols)
            stdscr.refresh()
            continue

        header_rows = 2
        footer_rows = 2
        frame_top = header_rows
        frame_left = 0
        frame_width = max(2, max_cols)
        frame_height = max(3, height - header_rows - footer_rows)
        map_cols = max(1, frame_width - 2)
        map_height = max(1, frame_height - 2)

        rendered = ascii_map.render_ascii(
            lat=lat,
            lon=lon,
            zoom=zoom,
            width=max(MIN_MAP_COLS, map_cols),
            height=max(MIN_MAP_ROWS, map_height),
            cell_aspect=cell_aspect,
            show_street_names=show_street_names,
        )
        lat, lon, zoom = rendered["lat"], rendered["lon"], rendered["zoom"]

        stdscr.erase()
        title = f"{APP_TITLE}"
        meta = (
            f"lat {lat:.5f}  lon {lon:.5f}  zoom {zoom}  aspect {cell_aspect:.2f}  "
            f"view {rendered['width']}x{rendered['height']}"
        )
        _safe_add(stdscr, 0, 0, title.ljust(max_cols), max_cols, ui_attrs["title"])
        _safe_add(stdscr, 0, min(len(title) + 2, max_cols - 1), meta, max_cols, ui_attrs["meta"])
        _safe_add(
            stdscr,
            1,
            0,
            "Controls: WSAD/Arrows pan  +/- zoom  [ ] aspect  n names  r reset  q quit".ljust(max_cols),
            max_cols,
            ui_attrs["hint"],
        )

        draw_frame(stdscr, frame_top, frame_left, frame_width, frame_height, ui_attrs["border"])
        _safe_add(stdscr, frame_top, 2, "[ MAP ]", max(0, frame_width - 4), ui_attrs["hint"])

        lines = rendered["text"].splitlines()
        for y, line in enumerate(lines):
            screen_y = frame_top + 1 + y
            if screen_y >= frame_top + frame_height - 1:
                break
            draw_colored_line(stdscr, screen_y, frame_left + 1, line, map_cols, char_attrs)

        legend_y = frame_top + frame_height
        status_y = legend_y + 1
        _safe_add(stdscr, legend_y, 0, ascii_map.GLYPH_LEGEND.ljust(max_cols), max_cols, ui_attrs["meta"])
        _safe_add(
            stdscr,
            status_y,
            0,
            (
                f"Zoom range {ascii_map.MIN_ZOOM}-{ascii_map.MAX_ZOOM}  "
                f"Street names {'on' if show_street_names else 'off'}  "
                f"Cached tiles {ascii_map.tile_cache_size()}"
            ).ljust(max_cols),
            max_cols,
            ui_attrs["meta"],
        )
        stdscr.refresh()


def main_wrapper():
    if "--dump" in sys.argv:
        run_dump_mode()
    else:
        curses.wrapper(main)

if __name__ == "__main__":
    main_wrapper()
