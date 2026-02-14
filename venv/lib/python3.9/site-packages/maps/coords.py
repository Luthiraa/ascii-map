import math

# Web Mercator constants
EARTH_RADIUS = 6378137.0
MAX_LATITUDE = 85.05112878

def latlon_to_world_pixel(lat, lon, zoom, tile_size=256):
    """
    Converts lat/lon to world pixel coordinates at a given zoom level.
    Returns (px, py).
    """
    scale = (tile_size * (2 ** zoom))
    
    # Longitude to x
    x = (lon + 180.0) / 360.0 * scale
    
    # Latitude to y (Mercator)
    # Clip latitude to valid range
    lat = max(min(lat, MAX_LATITUDE), -MAX_LATITUDE)
    sin_lat = math.sin(lat * math.pi / 180.0)
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * scale
    
    return x, y

def world_pixel_to_latlon(x, y, zoom, tile_size=256):
    """
    Converts world pixel coordinates to lat/lon.
    Returns (lat, lon).
    """
    scale = (tile_size * (2 ** zoom))
    
    lon = (x / scale) * 360.0 - 180.0
    
    n = math.pi - 2.0 * math.pi * y / scale
    lat = 180.0 / math.pi * math.atan(0.5 * (math.exp(n) - math.exp(-n)))
    
    return lat, lon

def get_tile_coords(lat, lon, zoom):
    """
    Returns the tile (x, y) containing the given lat/lon at zoom.
    """
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return xtile, ytile

def get_visible_tiles(center_lat, center_lon, zoom, width_px, height_px, tile_size=256):
    """
    Calculates the range of tiles visible in the viewport.
    Returns generator of (z, x, y) tuples.
    """
    center_x, center_y = latlon_to_world_pixel(center_lat, center_lon, zoom, tile_size)
    
    left = center_x - width_px / 2
    right = center_x + width_px / 2
    top = center_y - height_px / 2
    bottom = center_y + height_px / 2
    
    min_tile_x = int(math.floor(left / tile_size))
    max_tile_x = int(math.floor(right / tile_size))
    min_tile_y = int(math.floor(top / tile_size))
    max_tile_y = int(math.floor(bottom / tile_size))
    
    # Handle wrapping logic if needed (not strictly for MVP unless crossing dateline)
    # For now, simple range
    
    for x in range(min_tile_x, max_tile_x + 1):
        for y in range(min_tile_y, max_tile_y + 1):
            yield (zoom, x, y)
