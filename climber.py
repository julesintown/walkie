"""Wo die Figur gerade ist und wie sie sich dort bewegt – reine Logik, ohne Qt.

Modi:
  floor    Boden (Bildschirmunterkante) – das Laufen dort macht weiterhin walkie.py
  fall     fällt (Schwerkraft), landet auf der ersten Fensterkante darunter oder am Boden
  ledge    steht/läuft auf der Oberkante eines Fensters und wandert mit, wenn es verschoben wird
  edge     sitzt auf der Fensterkante, Beine baumeln
  wall     klettert am linken/rechten Bildschirmrand hoch
  ceiling  hängt kopfüber an der Oberkante und krabbelt entlang
  drag     wird gerade mit der Maus gehalten
  jump     springt im Bogen auf eine Fensterkante (z. B. das Terminal der arbeitenden Session)

Koordinaten: fx = Mitte der Figur (Bildschirm-x). fy = Bodenlinie (floor/fall/ledge/edge),
Mitte der Figur (wall) bzw. Oberkante (ceiling). walkie.py rechnet daraus die Fensterposition.

env (pro Schritt von walkie.py):
  screen = (links, oben, rechts, unten), floor = y der Bodenlinie,
  ledges = [(fenster_id, x1, x2, y)], win_x = {fenster_id: x}, idle = bool,
  can = {"Climb", "Ceiling", "SitEdge", …}, size = (Breite, Höhe) der Figur
"""
import random

GRAVITY = 0.9          # px/Tick² (Tick = 33 ms)
MAX_FALL = 22
CLIMB_SPEED = 1.5
CEILING_SPEED = 0.8
WALK_SPEED = 1
BIG_FALL = 120         # ab dieser Fallhöhe gibt's eine Landung mit Aufprall


class Climber:
    def __init__(self, rnd=random.random):
        self.rnd = rnd
        self.mode = "floor"
        self.fx = self.fy = 0.0
        self.vy = 0.0
        self.dir = 1
        self.side = "left"          # Wand
        self.win = None             # Fenster, auf dessen Kante sie steht
        self.win_x = None
        self.target = None
        self.moving = False
        self.timer = 0
        self.fell_from = 0.0
        self.landed = None          # nach einer Landung: Fallhöhe (walkie spielt Aufprall)

    # ------------------------------------------------------------ Übergänge von außen
    def drop(self, fx, fy):
        self.mode, self.fx, self.fy, self.vy = "fall", fx, fy, 0.0
        self.fell_from = fy
        self.target, self.moving = None, False

    def climb(self, side, fx, center_y):
        self.mode, self.side, self.fx, self.fy = "wall", side, fx, center_y
        self.moving = True

    def jump(self, fx, fy, tx, ty, win, win_x):
        """Im Bogen von (fx, fy) auf die Kante (tx, ty) des Fensters win springen."""
        dist = ((tx - fx) ** 2 + (ty - fy) ** 2) ** 0.5
        self.mode, self.win, self.win_x = "jump", win, win_x
        self.j0, self.j1 = (fx, fy), (tx, ty)
        self.jt, self.jn = 0, int(max(20, min(55, dist / 14)))
        self.jh = 70 + max(0.0, fy - ty) * 0.25          # Höhe des Bogens über der Linie
        self.dir = 1 if tx >= fx else -1
        self.target, self.moving, self.fell_from = None, False, fy

    def hold(self):
        self.mode, self.target, self.moving = "drag", None, False

    def to_floor(self):
        self.mode, self.target, self.moving = "floor", None, False

    # ------------------------------------------------------------ ein Tick
    def step(self, env):
        m = getattr(self, "_" + self.mode, None)
        if m:
            m(env)

    def _fall(self, env):
        left, top, right, _ = env["screen"]
        self.fx = max(left + 10, min(self.fx, right - 10))
        self.vy = min(self.vy + GRAVITY, MAX_FALL)
        ny = self.fy + self.vy
        hits = [(y, wid) for wid, x1, x2, y in env["ledges"]
                if x1 + 8 <= self.fx <= x2 - 8 and self.fy - 1 <= y <= ny]
        if hits:
            y, wid = min(hits)
            self.mode, self.win, self.win_x = "ledge", wid, env["win_x"].get(wid)
            self._land(y)
        elif ny >= env["floor"]:
            self.mode = "floor"
            self._land(env["floor"])
        else:
            self.fy = ny

    def _jump(self, env):
        nx = env["win_x"].get(self.win)
        if nx is None:                         # Ziel ist weg: einfach fallen
            return self.drop(self.fx, self.fy)
        if self.win_x is not None and nx != self.win_x:   # Ziel verschoben: mitzielen
            self.j1 = (self.j1[0] + nx - self.win_x, self.j1[1])
        self.win_x = nx
        seg = [(x1, x2, y) for wid, x1, x2, y in env["ledges"] if wid == self.win]
        if seg:                                # Kante kann sich auch in der Höhe bewegt haben
            self.j1 = (self.j1[0], min(seg, key=lambda s: abs(s[2] - self.j1[1]))[2])
        self.jt += 1
        k = self.jt / self.jn
        (x0, y0), (x1, y1) = self.j0, self.j1
        self.fx = x0 + (x1 - x0) * k
        self.fy = y0 + (y1 - y0) * k - self.jh * 4 * k * (1 - k)
        if self.jt >= self.jn:
            self.fell_from = self.fy
            self.mode = "ledge"
            self._land(y1)
            self.landed = 0                    # sanfte Landung, kein Aufprall

    def _land(self, y):
        self.landed = y - self.fell_from
        self.fy, self.vy, self.target, self.moving = y, 0.0, None, False

    def _my_ledge(self, env):
        """Kantenstück meines Fensters unter der Figur – folgt verschobenen Fenstern."""
        nx = env["win_x"].get(self.win)
        if nx is not None and self.win_x is not None:
            self.fx += nx - self.win_x
            if self.target is not None:
                self.target += nx - self.win_x
        self.win_x = nx
        for wid, x1, x2, y in env["ledges"]:
            if wid == self.win and x1 <= self.fx <= x2:
                return x1, x2, y
        return None

    def _ledge(self, env):
        seg = self._my_ledge(env)
        if seg is None:                        # Fenster weg, verdeckt oder darunter weggezogen
            return self.drop(self.fx, self.fy)
        x1, x2, self.fy = seg
        self.moving = False
        if not env["idle"]:
            self.target = None
            return
        if self.target is None:
            r = self.rnd()
            if r < 0.004 and "SitEdge" in env["can"]:
                self.mode, self.timer = "edge", int(150 + self.rnd() * 450)
                return
            if r < 0.006:                      # einfach runterspringen
                self.target = x1 - 30 if self.fx - x1 < x2 - self.fx else x2 + 30
            elif r < 0.02:
                self.target = x1 + 20 + self.rnd() * max(0, x2 - x1 - 40)
        if self.target is not None:
            dx = self.target - self.fx
            if abs(dx) <= WALK_SPEED:
                self.target = None
            else:
                self.dir = 1 if dx > 0 else -1
                self.fx += self.dir * WALK_SPEED
                self.moving = True

    def _edge(self, env):
        seg = self._my_ledge(env)
        if seg is None:
            return self.drop(self.fx, self.fy)
        self.fy = seg[2]
        self.timer -= 1
        if self.timer <= 0 or not env["idle"]:
            self.mode = "ledge"

    def _wall(self, env):
        left, top, right, _ = env["screen"]
        w, h = env["size"]
        if not env["idle"] or self.rnd() < 0.0005:
            return self._let_go(env)
        if self.rnd() < 0.008:
            self.moving = not self.moving       # kurz verschnaufen / weiter
        if self.moving:
            self.fy -= CLIMB_SPEED
        if self.fy - h / 2 <= top + 2:
            if "Ceiling" in env["can"]:
                self.mode = "ceiling"
                self.dir = 1 if self.side == "left" else -1
                self.fx = left + w / 2 + 4 if self.side == "left" else right - w / 2 - 4
                self.fy = top
                self.moving = True
            else:
                self._let_go(env)

    def _ceiling(self, env):
        left, top, right, _ = env["screen"]
        w, _h = env["size"]
        if not env["idle"] or self.rnd() < 0.003:
            return self._let_go(env)
        self.fx += self.dir * CEILING_SPEED
        if self.fx <= left + w / 2 or self.fx >= right - w / 2:
            self.dir = -self.dir
        self.fy = top
        self.moving = True

    def _let_go(self, env):
        """Loslassen: walkie.py setzt fx/fy danach aus der Fensterposition (reanchor)."""
        self.mode, self.vy, self.moving = "fall", 0.0, False
        self.fell_from = None
