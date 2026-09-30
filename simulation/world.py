"""
World canvas — 2000×2000 virtual environment.
The camera is a 640×480 viewport that pans within this world.
All objects live in world pixel coordinates (0..2000, 0..2000).
"""
import pygame
import numpy as np
import random
import math

class World:
    def __init__(self, cfg):
        self.cfg = cfg
        self.W = int(cfg.world.width)
        self.H = int(cfg.world.height)
        self.cam_w = int(cfg.camera.resolution_width)
        self.cam_h = int(cfg.camera.resolution_height)
        self._stars = self._gen_stars()
        self.surface = pygame.Surface((self.cam_w, self.cam_h))

    def _gen_stars(self):
        stars = []
        for _ in range(int(self.cfg.world.num_stars)):
            x = random.uniform(0, self.W)
            y = random.uniform(0, self.H)
            b = random.randint(
                int(self.cfg.world.star_min_brightness),
                int(self.cfg.world.star_max_brightness))
            sz = random.choices([1,1,1,2,2,3], k=1)[0]
            stars.append((x, y, b, sz))
        return stars

    def world_to_screen(self, wx, wy, cam_x, cam_y):
        """Convert world coords to screen pixel coords."""
        sx = wx - cam_x + self.cam_w / 2
        sy = wy - cam_y + self.cam_h / 2
        return (sx, sy)

    def _draw_square_beacon(self, surf, sx, sy, size, color, intensity=255):
        """Draw a square beacon (PS default shape)."""
        c = tuple(min(255, int(ch * intensity / 255)) for ch in color)

        # Place a w-px square so the centre of its lit pixels (pixel i has
        # its centre at i) is (sx, sy) to within rounding — int()
        # truncation plus the size//2 offset used to draw it ~1 px up-left.
        def centred(w):
            return pygame.Rect(math.floor(sx - (w - 1) / 2 + 0.5),
                               math.floor(sy - (w - 1) / 2 + 0.5), w, w)

        pygame.draw.rect(surf, c, centred(size))
        # Bright center
        core = tuple(min(255, int(ch * 1.3)) for ch in c)
        pygame.draw.rect(surf, core, centred(max(2, size // 2)))

    def _draw_round_beacon(self, surf, sx, sy, size, color, intensity=255):
        """Draw a round beacon-like spot (distractors): filled disc of
        diameter `size` with a brighter core, same brightness scaling as
        _draw_square_beacon."""
        c = tuple(min(255, int(ch * intensity / 255)) for ch in color)
        pygame.draw.circle(surf, c, (int(sx), int(sy)), max(1, size // 2))
        core = tuple(min(255, int(ch * 1.3)) for ch in c)
        pygame.draw.circle(surf, core, (int(sx), int(sy)), max(1, size // 4))

    def render(self, cam_x, cam_y, targets, distractors=None,
               obstacles=None, scintillation=1.0):
        """
        Render the 640×480 camera viewport.
        cam_x, cam_y: camera center in world coordinates.
        targets: list of Target objects.
        Returns (surface, list_of_occluded_bools).
        """
        bg = tuple(self.cfg.world.background_color)
        self.surface.fill(bg)

        # Clip region for culling
        mx = self.cam_w / 2
        my = self.cam_h / 2

        # Stars
        for (wx, wy, b, sz) in self._stars:
            sx, sy = self.world_to_screen(wx, wy, cam_x, cam_y)
            if -sz <= sx <= self.cam_w+sz and -sz <= sy <= self.cam_h+sz:
                col = (b, b, int(b*0.9))
                if sz == 1:
                    if 0 <= int(sx) < self.cam_w and 0 <= int(sy) < self.cam_h:
                        self.surface.set_at((int(sx), int(sy)), col)
                else:
                    pygame.draw.circle(self.surface, col,
                                       (int(sx), int(sy)), sz)

        # Distractors
        if distractors:
            for d in distractors:
                sx, sy = self.world_to_screen(
                    d['wx'], d['wy'], cam_x, cam_y)
                if (-d['size'] <= sx <= self.cam_w+d['size'] and
                        -d['size'] <= sy <= self.cam_h+d['size']):
                    draw = (self._draw_round_beacon
                            if d.get('shape') == 'round'
                            else self._draw_square_beacon)
                    draw(self.surface, sx, sy,
                         d['size'], d['color'],
                         d['brightness'])

        # Targets
        occluded_list = []
        for t in targets:
            sx, sy = self.world_to_screen(t.wx, t.wy, cam_x, cam_y)
            occ = False
            if obstacles:
                for obs in obstacles:
                    ox, oy = self.world_to_screen(
                        obs['wx'], obs['wy'], cam_x, cam_y)
                    if (abs(sx - ox) < obs['w']//2 and
                            abs(sy - oy) < obs['h']//2):
                        occ = True
                        break
            occluded_list.append(occ)
            if not occ:
                bi = int(t.brightness * scintillation)
                bi = max(30, min(255, bi))
                sz = int(t.size_px)
                self._draw_square_beacon(
                    self.surface, sx, sy, sz, t.color, bi)

        # Obstacles (drawn on top)
        if obstacles:
            for obs in obstacles:
                ox, oy = self.world_to_screen(
                    obs['wx'], obs['wy'], cam_x, cam_y)
                rect = pygame.Rect(
                    int(ox - obs['w']//2),
                    int(oy - obs['h']//2),
                    obs['w'], obs['h'])
                pygame.draw.rect(self.surface, (15, 18, 25), rect)
                pygame.draw.rect(self.surface, (30, 45, 60), rect, 1)

        return self.surface, occluded_list
