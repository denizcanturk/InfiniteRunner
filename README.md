# Terminal Infinite Runner

An endless runner that plays entirely in your terminal, drawn in plain ASCII. Jump over cacti, duck under birds, and see how far you can get as the game speeds up.

```
                                              HI 00412  00187

        __
       /o_)                     <o==-
     _/ |
       / \           ##                     #
_______________-_______________##___________#___________
   .        ,             `          '        .
```

## Requirements

- Python 3.8 or newer
- No third-party packages: the game uses only the standard library
  - **Linux / macOS:** `curses`
  - **Windows:** `msvcrt` with ANSI escape codes (Windows 10 or newer)
- A terminal of at least **51 × 18** characters

## Running

```bash
python3 runner.py      # Linux / macOS
python runner.py       # Windows
```

If the terminal is too small, the game shows a warning and waits until you resize the window.

## Controls

| Key | Action |
|---|---|
| `Space` / `↑` / `W` | Jump (only from the ground) |
| `↓` / `S` | Duck while on the ground; fast-drop while in the air |
| `R` | Restart |
| `Q` | Quit |

Terminals report repeated key presses, not held keys, so one press of Down keeps the character ducked for about half a second. Holding the key extends it.

## Gameplay

- **Cacti** (`#`, `##`, `###`) stand on the ground and must be jumped over.
- **Birds** appear once your score reaches 150 and fly at three heights:
  - **Low:** jump over it.
  - **Middle:** duck under it.
  - **High:** it passes over you, so do nothing.
- The game speeds up as your score rises: ticks get shorter and obstacles scroll faster.
- Obstacles are always spaced far enough apart that you can land and act again, so every situation can be survived.
- Touching any obstacle ends the run. The screen freezes on the moment of impact.

## High score

Your best score is saved to a `.hiscore` file next to `runner.py` and is loaded each time you start the game. Delete that file to reset it.

## Tuning

All gameplay constants are at the top of `runner.py` under **Ayarlar** (settings). For example:

| Constant | Meaning |
|---|---|
| `GRAVITY`, `JUMP_VELOCITY` | Jump height and air time |
| `FAST_DROP_MULT` | Gravity multiplier while pressing Down in the air |
| `BASE_TICK`, `MIN_TICK` | Starting and fastest tick length (seconds) |
| `BASE_SPEED`, `MAX_SPEED` | Scroll speed in columns per tick |
| `BIRD_MIN_SCORE`, `BIRD_CHANCE` | When birds start appearing and how often |
| `REACTION_SECONDS` | Extra reaction time added to the minimum obstacle gap |

The minimum gap between obstacles is calculated from `GRAVITY` and `JUMP_VELOCITY`, so changing the jump keeps every obstacle clearable.

## How it works

- **No screen clearing:** each frame is compared with the previous one, and only the changed characters are redrawn. This prevents flicker.
- **Fixed character, moving world:** the runner stays at a fixed column while the ground and obstacles scroll from right to left.
- **Physics:** a jump sets an upward velocity, and gravity is added to it every tick until the character lands.
- **Collisions:** the game checks the drawn characters of the runner against those of each obstacle. Blank spaces in a sprite never count as a hit.
- **Non-blocking input:** the game reads key presses without waiting, so obstacles keep moving whether or not you press anything.
