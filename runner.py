#!/usr/bin/env python3
"""
Terminal Infinite Runner
========================

ASCII sonsuz koşu oyunu (Linux / macOS / Windows).

Kontroller
----------
  SPACE / UP   : Zıpla (sadece zemindeyken; çift zıplama yok)
  DOWN         : Zeminde eğil / havada hızlı düşüş (fast-drop)
  R            : Yeniden başla
  Q            : Çıkış

Çalıştırma
----------
  Linux/macOS : python3 runner.py           (stdlib curses)
  Windows     : python runner.py            (stdlib msvcrt + ANSI VT)
"""

import os
import random
import sys
import time
from collections import deque

IS_WINDOWS = os.name == "nt"
if IS_WINDOWS:
    import msvcrt
else:
    import curses

# --------------------------------------------------------------------------
# Ayarlar
# --------------------------------------------------------------------------
PLAY_ROWS = 18            # Oyun alanı yüksekliği (satır)
MIN_COLS = 50             # Oyun alanı için en az genişlik
MAX_COLS = 110            # Oyun alanının en fazla genişliği
GROUND_ROW = 15           # Zemin çizgisinin satırı (dinozorun ayakları bunun üstünde)
DINO_X = 4                # Dinozorun sabit X koordinatı

GRAVITY = 0.16            # g: her tick'te Vy'ye eklenir
JUMP_VELOCITY = -1.7      # Vy: negatif = yukarı
FAST_DROP_MULT = 3.5      # Havada DOWN basılıyken yerçekimi çarpanı

BASE_TICK = 1 / 22        # Başlangıç tick süresi (saniye)
MIN_TICK = 1 / 55         # En kısa tick süresi
BASE_SPEED = 1.0          # Kayma hızı (sütun / tick)
MAX_SPEED = 1.6

SCORE_PER_COL = 0.4       # Kat edilen her sütun için puan
BIRD_MIN_SCORE = 150      # Kuşların görünmeye başladığı skor
BIRD_CHANCE = 0.3
REACTION_SECONDS = 0.30   # Engeller arası boşluğa eklenen tepki payı

RUN_ANIM_TICKS = 3        # Koşu karesi kaç tick'te bir değişir (N)
BIRD_ANIM_TICKS = 6

DUCK_HOLD_FIRST = 0.50    # İlk DOWN basışı: tuş tekrarı gecikmesini kapsar
DUCK_HOLD_REPEAT = 0.15   # Tekrarlanan DOWN olayları eğilmeyi bu kadar uzatır

HISCORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".hiscore")

# Girdi olayları
JUMP, DUCK, QUIT, RESTART, RESIZE = "jump", "duck", "quit", "restart", "resize"

# --------------------------------------------------------------------------
# Sprite'lar (boşluk = saydam, çarpışmaya dahil değil)
# --------------------------------------------------------------------------
DINO_RUN_A = [
    "   __",
    "  /o_)",
    "_/ |",
    "  / \\",
]
DINO_RUN_B = [
    "   __",
    "  /o_)",
    "_/ |",
    "   |\\",
]
DINO_JUMP = [
    "   __",
    "  /o_)",
    "_/ |",
    "  | |",
]
DINO_DUCK = [            # Yükseklik yarıya iner, yalnızca kafa görünür
    "  ____",
    "_/__o_)",
]

BIRD_A = [
    "  \\\\",
    "<o==-",
]
BIRD_B = [
    "  __",
    "<o==-",
]

# Kuş irtifaları: sprite'ın alt satırının zeminden yüksekliği
#   LOW  (1): ayakta ve eğilmiş dinozora çarpar  -> zıpla
#   MID  (2): ayaktakine çarpar, eğilmişin üstünden geçer -> eğil
#   HIGH (4): ayaktaki dinozorun (yükseklik 4) üstünden geçer -> hiçbir şey yapma
BIRD_LEVELS = (1, 2, 4)


def make_cactus(width, height):
    return ["#" * width] * height


def sprite_width(sprite):
    return max(len(line) for line in sprite)


def jump_air_ticks():
    """Standart bir zıplamanın havada kaldığı tick sayısı (fizikten türetilir)."""
    y, vy, t = 0.0, JUMP_VELOCITY, 0
    while True:
        vy += GRAVITY
        y += vy
        t += 1
        if y >= 0:
            return t


AIR_TICKS = jump_air_ticks()
DINO_W = max(sprite_width(s) for s in (DINO_RUN_A, DINO_RUN_B, DINO_JUMP, DINO_DUCK))


# --------------------------------------------------------------------------
# Yüksek skor kalıcılığı
# --------------------------------------------------------------------------
def load_hiscore():
    try:
        with open(HISCORE_FILE, "r", encoding="utf-8") as f:
            return max(0, int(f.read().strip() or 0))
    except (OSError, ValueError):
        return 0


def save_hiscore(value):
    try:
        with open(HISCORE_FILE, "w", encoding="utf-8") as f:
            f.write(str(int(value)))
    except OSError:
        pass


# --------------------------------------------------------------------------
# Oyun modeli
# --------------------------------------------------------------------------
class Obstacle:
    __slots__ = ("kind", "wx", "h", "frames", "w")

    def __init__(self, kind, wx, h, frames):
        self.kind = kind        # "cactus" | "bird"
        self.wx = wx            # Dünya koordinatında sol kenar
        self.h = h              # Alt satırın zeminden yüksekliği
        self.frames = frames
        self.w = max(sprite_width(f) for f in frames)


class Game:
    def __init__(self, width, hiscore):
        self.w = width
        self.hiscore = hiscore
        self.reset()

    # ---- durum ---------------------------------------------------------
    def reset(self):
        self.y = 0.0              # Dinozor Y (0 = zemin, negatif = yukarı)
        self.vy = 0.0
        self.airborne = False
        self.ducking = False
        self.down_until = 0.0     # DOWN tuşunun "basılı" sayıldığı son an
        self.ticks = 0
        self.distance = 0.0       # Toplam kayma (float)
        self.scrolled = 0         # int(distance): zemin/engeller için tam sütun
        self.speed = BASE_SPEED
        self.tick_dt = BASE_TICK
        self.score = 0
        self.over = False
        self.obstacles = []
        self.spawn_after_wx = self.w + 25   # İlk engelden önce boşluk
        self.ground = deque(self._ground_char() for _ in range(self.w))
        self.texture = deque(self._texture_char() for _ in range(self.w))

    @staticmethod
    def _ground_char():
        r = random.random()
        return "_" if r < 0.93 else random.choice("-.,")

    @staticmethod
    def _texture_char():
        r = random.random()
        return " " if r < 0.85 else random.choice(".,`'-")

    # ---- girdi ---------------------------------------------------------
    def handle(self, event, now):
        if self.over:
            return
        if event == JUMP:
            if not self.airborne:           # Çift zıplama kapalı
                self.vy = JUMP_VELOCITY
                self.airborne = True
                self.ducking = False
                self.down_until = 0.0
        elif event == DUCK:
            if now < self.down_until:       # Tuş tekrarı: basılı tutuluyor
                self.down_until = max(self.down_until, now + DUCK_HOLD_REPEAT)
            else:
                self.down_until = now + DUCK_HOLD_FIRST

    # ---- simülasyon ----------------------------------------------------
    def min_gap(self, speed):
        """Bir engelin sağ kenarı ile sonrakinin sol kenarı arasındaki zorunlu
        en küçük mesafe: tam bir zıplama süresi + tepki süresi boyunca kat
        edilen yol + dinozor genişliği. Böylece oyuncu her zaman yere inip
        bir sonraki engel için tekrar hareket edebilir."""
        reaction_ticks = REACTION_SECONDS / self.tick_dt
        return int((AIR_TICKS + reaction_ticks) * speed + 0.999) + DINO_W

    def _spawn(self):
        wx = self.scrolled + self.w
        if self.score >= BIRD_MIN_SCORE and random.random() < BIRD_CHANCE:
            obs = Obstacle("bird", wx, random.choice(BIRD_LEVELS), [BIRD_A, BIRD_B])
        else:
            width = random.choices((1, 2, 3), weights=(5, 3, 2))[0]
            height = random.choice((2, 3)) if width < 3 else 2
            obs = Obstacle("cactus", wx, 0, [make_cactus(width, height)])
        self.obstacles.append(obs)
        # Hız yükselmeye devam edeceği için küçük bir pay ile hesapla.
        gap = self.min_gap(min(MAX_SPEED, self.speed + 0.1))
        gap += random.randint(0, int(gap * 0.8))
        self.spawn_after_wx = wx + obs.w + gap

    def step(self, now):
        self.ticks += 1
        down_held = now < self.down_until

        # Fizik: Vy += g, Y += Vy
        if self.airborne:
            g = GRAVITY * (FAST_DROP_MULT if down_held else 1.0)
            self.vy += g
            self.y += self.vy
            if self.y >= 0:
                self.y, self.vy, self.airborne = 0.0, 0.0, False
        self.ducking = (not self.airborne) and down_held

        # Dünya kaydırma (dinozor sabit, dünya sağdan sola akar)
        self.distance += self.speed
        shift = int(self.distance) - self.scrolled
        for _ in range(shift):
            self.ground.popleft()
            self.ground.append(self._ground_char())
            self.texture.popleft()
            self.texture.append(self._texture_char())
        self.scrolled += shift

        self.obstacles = [o for o in self.obstacles if o.wx + o.w > self.scrolled]
        if self.scrolled + self.w >= self.spawn_after_wx:
            self._spawn()

        # Skor ve dinamik zorluk
        self.score = int(self.distance * SCORE_PER_COL)
        self.hiscore = max(self.hiscore, self.score)
        self.speed = min(MAX_SPEED, BASE_SPEED + self.score / 2500)
        self.tick_dt = max(MIN_TICK, BASE_TICK / (1 + self.score / 800))

        # Çarpışma
        if self._dino_cells() & self._obstacle_cells():
            self.over = True

    # ---- geometri ------------------------------------------------------
    def _dino_sprite(self):
        if self.ducking:
            return DINO_DUCK
        if self.airborne:
            return DINO_JUMP
        return DINO_RUN_A if (self.ticks // RUN_ANIM_TICKS) % 2 == 0 else DINO_RUN_B

    @staticmethod
    def _sprite_cells(sprite, left, bottom_row):
        """Sprite'ın boş olmayan hücreleri: {(satır, sütun): karakter}."""
        top = bottom_row - len(sprite) + 1
        cells = {}
        for r, line in enumerate(sprite):
            for c, ch in enumerate(line):
                if ch != " ":
                    cells[(top + r, left + c)] = ch
        return cells

    def _dino_map(self):
        bottom = GROUND_ROW - 1 - int(round(-self.y))
        cells = self._sprite_cells(self._dino_sprite(), DINO_X, bottom)
        if self.over:
            cells = {p: ("x" if ch == "o" else ch) for p, ch in cells.items()}
        return cells

    def _obstacle_map(self):
        cells = {}
        for o in self.obstacles:
            frame = o.frames[(self.ticks // BIRD_ANIM_TICKS) % len(o.frames)]
            left = o.wx - self.scrolled
            cells.update(self._sprite_cells(frame, left, GROUND_ROW - 1 - o.h))
        return cells

    def _dino_cells(self):
        return set(self._dino_map())

    def _obstacle_cells(self):
        return set(self._obstacle_map())

    # ---- çizim ---------------------------------------------------------
    def render(self):
        """Tüm sahnenin {(satır, sütun): karakter} haritası."""
        frame = {}

        def text(row, col, s):
            for i, ch in enumerate(s):
                if 0 <= col + i < self.w:
                    frame[(row, col + i)] = ch

        for x in range(self.w):
            frame[(GROUND_ROW, x)] = self.ground[x]
            ch = self.texture[x]
            if ch != " ":
                frame[(GROUND_ROW + 1, x)] = ch

        for (r, c), ch in self._obstacle_map().items():
            if 0 <= c < self.w:
                frame[(r, c)] = ch
        frame.update(self._dino_map())

        hud = f"HI {self.hiscore:05d}  {self.score:05d}"
        text(0, self.w - len(hud), hud)
        help_line = "SPACE/UP jump  DOWN duck  R restart  Q quit"
        if len(help_line) + len(hud) + 2 <= self.w:
            text(0, 0, help_line)

        if self.over:
            msg1 = "G A M E   O V E R"
            msg2 = "[R] restart   [Q] quit"
            text(4, (self.w - len(msg1)) // 2, msg1)
            text(6, (self.w - len(msg2)) // 2, msg2)
        return frame


# --------------------------------------------------------------------------
# Ekran katmanları: yerinde (in-place) diff çizimi, ekran hiç temizlenmez
# --------------------------------------------------------------------------
class Screen:
    def __init__(self):
        self._prev = {}

    def present(self, frame):
        """Önceki karede dolu olup artık boş olan hücrelere boşluk yaz,
        yalnızca değişen hücreleri yeni karakterleriyle çiz."""
        prev = self._prev
        for pos in prev.keys() - frame.keys():
            self._put(pos[0], pos[1], " ")
        for pos, ch in frame.items():
            if prev.get(pos) != ch:
                self._put(pos[0], pos[1], ch)
        self._prev = frame
        self._flush()

    def invalidate(self):
        self._prev = {}
        self._wipe()

    # Alt sınıflar uygular
    def size(self): raise NotImplementedError
    def events(self): raise NotImplementedError
    def _put(self, row, col, ch): raise NotImplementedError
    def _flush(self): raise NotImplementedError
    def _wipe(self): raise NotImplementedError


class CursesScreen(Screen):
    def __init__(self, stdscr):
        super().__init__()
        self.scr = stdscr
        stdscr.nodelay(True)      # getch() bloklamaz
        stdscr.keypad(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def size(self):
        return self.scr.getmaxyx()

    def events(self):
        out = []
        while True:
            k = self.scr.getch()
            if k == -1:
                return out
            if k in (ord(" "), curses.KEY_UP, ord("w"), ord("W")):
                out.append(JUMP)
            elif k in (curses.KEY_DOWN, ord("s"), ord("S")):
                out.append(DUCK)
            elif k in (ord("q"), ord("Q")):
                out.append(QUIT)
            elif k in (ord("r"), ord("R")):
                out.append(RESTART)
            elif k == curses.KEY_RESIZE:
                out.append(RESIZE)

    def _put(self, row, col, ch):
        try:
            self.scr.addstr(row, col, ch)
        except curses.error:
            pass

    def _flush(self):
        self.scr.noutrefresh()
        curses.doupdate()

    def _wipe(self):
        self.scr.erase()
        self.scr.refresh()


class WindowsScreen(Screen):
    """msvcrt ile non-blocking girdi, ANSI imleç konumlandırma ile çizim."""

    def __init__(self):
        super().__init__()
        self._buf = []
        self._enable_vt()
        sys.stdout.write("\x1b[?25l\x1b[2J")   # İmleci gizle, başlangıçta bir kez temizle
        sys.stdout.flush()

    @staticmethod
    def _enable_vt():
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            handle = k32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if k32.GetConsoleMode(handle, ctypes.byref(mode)):
                k32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            os.system("")

    def size(self):
        import shutil
        s = shutil.get_terminal_size((80, 24))
        return s.lines, s.columns

    def events(self):
        out = []
        while msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                code = msvcrt.getwch()
                if code == "H":
                    out.append(JUMP)
                elif code == "P":
                    out.append(DUCK)
            elif ch in (" ", "w", "W"):
                out.append(JUMP)
            elif ch in ("s", "S"):
                out.append(DUCK)
            elif ch in ("q", "Q"):
                out.append(QUIT)
            elif ch in ("r", "R"):
                out.append(RESTART)
        return out

    def _put(self, row, col, ch):
        self._buf.append(f"\x1b[{row + 1};{col + 1}H{ch}")

    def _flush(self):
        if self._buf:
            sys.stdout.write("".join(self._buf))
            sys.stdout.flush()
            self._buf.clear()

    def _wipe(self):
        sys.stdout.write("\x1b[2J")
        sys.stdout.flush()

    def close(self):
        sys.stdout.write(f"\x1b[{PLAY_ROWS + 1};1H\x1b[?25h\n")
        sys.stdout.flush()


# --------------------------------------------------------------------------
# Ana döngü
# --------------------------------------------------------------------------
def wait_for_size(screen):
    """Terminal çok küçükse uyarı göster; yeterli olunca genişliği döndür."""
    warned = False
    while True:
        rows, cols = screen.size()
        if rows >= PLAY_ROWS and cols - 1 >= MIN_COLS:
            if warned:
                screen.invalidate()
            return min(cols - 1, MAX_COLS)
        if not warned:
            screen.invalidate()
            warned = True
        msg = f"Terminal too small: need {MIN_COLS + 1}x{PLAY_ROWS}, have {cols}x{rows}. Q quits."
        screen.present({(0, i): ch for i, ch in enumerate(msg[: max(cols - 1, 0)])})
        if QUIT in screen.events():
            return None
        time.sleep(0.1)


def run(screen):
    width = wait_for_size(screen)
    if width is None:
        return
    game = Game(width, load_hiscore())
    screen.present(game.render())
    next_tick = time.perf_counter()

    while True:
        now = time.perf_counter()

        for ev in screen.events():
            if ev == QUIT:
                save_hiscore(game.hiscore)
                return
            if ev == RESTART:
                save_hiscore(game.hiscore)
                game.reset()
                next_tick = now
                screen.present(game.render())
            elif ev == RESIZE:
                screen.invalidate()
                width = wait_for_size(screen)
                if width is None:
                    save_hiscore(game.hiscore)
                    return
                if width != game.w:
                    hi = game.hiscore
                    game = Game(width, hi)
                next_tick = time.perf_counter()
                screen.present(game.render())
            else:
                game.handle(ev, now)

        if not game.over and now >= next_tick:
            game.step(now)
            screen.present(game.render())       # Çarpışma anı da bu karede donar
            if game.over:
                save_hiscore(game.hiscore)
            next_tick += game.tick_dt
            if next_tick < now:                  # Gecikmede birikmiş tick'leri atla
                next_tick = now + game.tick_dt

        time.sleep(max(0.0, min(next_tick - time.perf_counter(), 0.005)))


def main():
    if IS_WINDOWS:
        screen = WindowsScreen()
        try:
            run(screen)
        except KeyboardInterrupt:
            pass
        finally:
            screen.close()
    else:
        try:
            curses.wrapper(lambda stdscr: run(CursesScreen(stdscr)))
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
