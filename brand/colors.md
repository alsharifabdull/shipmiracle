# Shipmiracle colour tokens

Approved by the owner on 26 Oct 2026: S1 Sign-off S + A Twinkle star + porcelain tile, graphite S, deep amber star.
Contrast is WCAG 2.x (relative luminance, flat hex values, computed 26 Oct 2026). Graphics need 3:1, body text 4.5:1.

## Light (default appearance)

| Token | Hex | Use |
|---|---|---|
| Porcelain top | `#F4EFE6` | tile gradient, top |
| Porcelain bottom | `#D9D1C4` | tile gradient, bottom |
| Graphite S top / bottom | `#3C4148` to `#1B1E23` | the S (gradient in the composed icon), flat `#2C3036` in `icon/foreground.svg` |
| Deep amber star top / bottom | `#C55F00` to `#9C4300` | the star (gradient in the composed icon), flat `#B05100` in `icon/accent.svg` |
| Wordmark | `#2C3036` | "Shipmiracle" on light |
| Tagline | `#555B63` | "Ship it with miracles." on light |
| Banner background | `#F7F3EB` to `#ECE5D8` | banner and social preview |
| Favicon S / star | `#23272D` / `#B85800` | 16 px cut (a touch heavier and brighter than the icon so it holds at 16 px) |

## Dark (graphite tile, warm white S, gold star)

| Token | Hex | Use |
|---|---|---|
| Graphite top / bottom | `#40454C` to `#1A1C20` | tile in the dark lockup and dark banner |
| Warm white S | `#FFF9EE` to `#E9E0CF` | the S, the dark wordmark (`#FFF9EE`) |
| Gold star | `#FFD04A` to `#F2A900` | the star |
| Tagline | `#CFC6B4` | tagline on dark |
| Banner background | `#2A2D32` to `#17191C` | dark banner |

The macOS Dark appearance of the app icon (Icon Composer, derived from the light one) uses tile `#3B4046` to `#14161A`, S `#FBF5E9` to `#E5DCCB`, star `#FFB02E` to `#F58F00`. Tinted: tile `#33373C` to `#131518`, S `#EEEEEE` to `#BDBDBD`, star `#D6D6D6` to `#A8A8A8`. Clear has no fill of its own (the system draws the glass).

## Contrast

| Pair | Ratio | Verdict |
|---|---|---|
| Graphite S top `#3C4148` on porcelain top `#F4EFE6` | 8.98 | pass |
| Graphite S top `#3C4148` on porcelain bottom `#D9D1C4` | 6.79 | pass |
| Graphite S bottom `#1B1E23` on porcelain bottom `#D9D1C4` | 11.04 | pass |
| Star top `#C55F00` on porcelain top `#F4EFE6` | 3.66 | pass (graphics 3:1) |
| Star top `#C55F00` on porcelain bottom `#D9D1C4` | 2.77 | below 3:1 in the worst pairing; the star sits in the upper half of the tile where the tile is lighter, and it is an accent, the S carries the legibility |
| Star bottom `#9C4300` on porcelain bottom `#D9D1C4` | 4.31 | pass |
| Star flat `#B05100` (layer file) on `#D9D1C4` | 3.45 | pass |
| Favicon S `#23272D` on `#D9D1C4` | 9.91 | pass |
| Favicon star `#B85800` on `#D9D1C4` / `#F4EFE6` | 3.13 / 4.14 | pass |
| Wordmark `#2C3036` on `#F7F3EB` / `#ECE5D8` | 11.99 / 10.59 | pass (AAA) |
| Tagline `#555B63` on `#ECE5D8` | 5.47 | pass (AA) |
| Dark S `#FFF9EE` on `#40454C` | 9.22 | pass |
| Dark S bottom `#E9E0CF` on `#1A1C20` | 13.02 | pass |
| Gold `#FFD04A` on `#40454C` | 6.61 | pass |
| Gold bottom `#F2A900` on `#1A1C20` | 8.49 | pass |
| Dark wordmark `#FFF9EE` on `#2A2D32` | 13.18 | pass (AAA) |
| Dark tagline `#CFC6B4` on `#17191C` / `#2A2D32` | 10.39 / 8.15 | pass |
| macOS Dark icon: S `#FBF5E9` on `#3B4046`, star `#FFB02E` on `#14161A` | 9.63, 9.92 | pass |

Not measured: the glass-rendered result in Icon Composer (Liquid Glass changes the pixels), and colours on a user's own wallpaper (Clear, Tinted).
