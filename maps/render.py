class Framebuffer:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.buffer = [[' ' for _ in range(width)] for _ in range(height)]
        self.colors = [[0 for _ in range(width)] for _ in range(height)]
    
    def clear(self):
        for y in range(self.height):
            for x in range(self.width):
                self.buffer[y][x] = ' '
                self.colors[y][x] = 0
                
    def set_char(self, x, y, char, color=0):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.buffer[y][x] = char
            self.colors[y][x] = color

    def draw_line(self, x0, y0, x1, y1, char, color=0):
        """Bresenham's Line Algorithm"""
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        
        while True:
            self.set_char(x0, y0, char, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def draw_poly_filled(self, points, char, color=0):
        """Fill a single polygon ring."""
        self.draw_polygon_filled([points], char, color)

    def draw_polygon_filled(self, rings, char, color=0):
        """Even-odd scanline fill for polygon rings (supports holes)."""
        if not rings:
            return

        valid_rings = [ring for ring in rings if len(ring) >= 3]
        if not valid_rings:
            return

        min_y = min(int(p[1]) for ring in valid_rings for p in ring)
        max_y = max(int(p[1]) for ring in valid_rings for p in ring)
        min_y = max(0, min_y)
        max_y = min(self.height - 1, max_y)

        for y in range(min_y, max_y + 1):
            nodes = []
            for ring in valid_rings:
                j = len(ring) - 1
                for i in range(len(ring)):
                    xi, yi = ring[i]
                    xj, yj = ring[j]
                    if (yi < y and yj >= y) or (yj < y and yi >= y):
                        x = xi + (y - yi) / (yj - yi) * (xj - xi)
                        nodes.append(int(x))
                    j = i

            nodes.sort()
            for i in range(0, len(nodes), 2):
                if i + 1 >= len(nodes):
                    break
                x_start = max(0, nodes[i])
                x_end = min(self.width - 1, nodes[i + 1])
                for x in range(x_start, x_end + 1):
                    self.buffer[y][x] = char
                    self.colors[y][x] = color

    def draw_poly_outline(self, points, char, color=0):
        for i in range(len(points) - 1):
            x0, y0 = points[i]
            x1, y1 = points[i+1]
            self.draw_line(int(x0), int(y0), int(x1), int(y1), char, color)
            
    def get_row(self, y):
        return "".join(self.buffer[y])

    def get_row_colors(self, y):
        return self.colors[y]
