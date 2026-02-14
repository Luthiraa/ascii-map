import os
import concurrent.futures
import requests
from maps import mvt_decoder
# import env removed

# Config (Move to a better place later)
CACHE_DIR = os.path.expanduser("~/.asciimaps/cache")
# TILE_URL_TEMPLATE = "https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/{z}/{x}/{y}.mvt?access_token={token}"
TILE_URL_TEMPLATE = "https://tiles.openfreemap.org/planet/latest/{z}/{x}/{y}.pbf"

# Try to get token from env (Not needed for OpenFreeMap but kept for compat if we switch back)
MAPBOX_TOKEN = os.environ.get("MAPBOX_ACCESS_TOKEN", "")

def get_tile_path(z, x, y):
    return os.path.join(CACHE_DIR, str(z), str(x), f"{y}.mvt")

def fetch_tile(z, x, y):
    """
    Returns tile bytes. Checks cache first, then downloads.
    """
    path = get_tile_path(z, x, y)
    
    if os.path.exists(path):
        # Guard against previously cached empty files; they decode as blank tiles.
        if os.path.getsize(path) == 0:
            try:
                os.remove(path)
            except OSError:
                pass
        else:
            with open(path, "rb") as f:
                return f.read()
            
    # Download
    # if not MAPBOX_TOKEN:
    #     return None # Graceful fail for MVP if no token
        
    url = TILE_URL_TEMPLATE.format(z=z, x=x, y=y, token=MAPBOX_TOKEN)
    try:
        resp = requests.get(url, timeout=5) # Increased timeout
        if resp.status_code == 200:
            if not resp.content:
                return None
            # Save to cache
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(resp.content)
            return resp.content
        else:
            print(f"Error fetching {url}: {resp.status_code} {resp.text[:100]}")
    except Exception as e:
        print(f"Exception fetching {url}: {e}")
        pass # Log error
        
    return None

def decode_tile(tile_bytes, z, x, y):
    """
    Decodes MVT bytes into a dictionary of features.
    """
    if not tile_bytes:
        return {}
    try:
        # Vector tiles are encoded with Y increasing downward from the tile origin.
        # Keep that orientation so decoded geometry aligns with world/tile pixel math.
        decoded = mvt_decoder.decode(tile_bytes, default_options={"y_coord_down": True})
        return decoded
    except Exception:
        return {}

class TileLoader:
    def __init__(self):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.futures = {} # (z,x,y) -> future
        self.loaded = {} # (z,x,y) -> decoded_data
        
    def request_tile(self, z, x, y):
        key = (z, x, y)
        if key in self.loaded:
            return
        if key in self.futures:
            return # Already fetching
            
        # Check cache synchronously first (fast I/O)
        path = get_tile_path(z, x, y)
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    raw = f.read()
                self.loaded[key] = decode_tile(raw, z, x, y)
                return
            except Exception:
                pass
        
        # If not in cache, submit to thread pool
        self.futures[key] = self.executor.submit(self._fetch_and_decode, z, x, y)
        
    def _fetch_and_decode(self, z, x, y):
        raw = fetch_tile(z, x, y)
        if raw:
            return decode_tile(raw, z, x, y)
        return {}

    def update(self):
        """Check for completed futures"""
        # Iterate over copy of keys since we modify dict
        for key in list(self.futures.keys()):
            future = self.futures[key]
            if future.done():
                try:
                    result = future.result()
                    self.loaded[key] = result
                except Exception as e:
                    pass # Log?
                del self.futures[key]

    def get_tile(self, z, x, y):
        return self.loaded.get((z, x, y))
        
    def clear(self):
        self.executor.shutdown(wait=False)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.futures = {}
        self.loaded = {}
