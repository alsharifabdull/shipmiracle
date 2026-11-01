# Shipmiracle brand assets

Logo approved by the owner on 26 Oct 2026: S1 Sign-off S + A Twinkle star on a porcelain tile, graphite S, deep amber star. Colour values and contrast numbers: `colors.md`.

| File | What | Size |
|---|---|---|
| `icon/background.svg`, `foreground.svg`, `accent.svg`, `monochrome.svg` | layered app icon source for Icon Composer, steps in `icon/README.md` | 1024 x 1024 |
| `icon/AppIcon-preview-1024.png` and `-dark-`, `-clear-`, `-tinted-` | composed previews of the four appearances | 1024 x 1024 |
| `mark-only.svg`, `mark-only-dark.svg` | the icon as a flat tile, no filters | 1024 x 1024 |
| `lockup-light.svg`, `lockup-dark.svg` | mark + "Shipmiracle", horizontal, transparent background | vector |
| `banner-1280x320.png` / `.svg`, `banner-dark-1280x320.png` / `.svg` | brand banner, mark + wordmark + tagline "Ship it with miracles." (the README no longer uses it: its header is the animated `docs/images/header.gif`, light only) | 1280 x 320 |
| `social-preview-1280x640.png` / `.svg` | GitHub social preview, same lock-up, 40 px or more of margin on every side | 1280 x 640 |
| `favicon.svg` | 16 px cut: bolder S with open counters, rounded 4-point star at least 5 px tall at 16 px | 64 unit grid |
| `favicon-16.png`, `favicon-32.png`, `favicon.ico` (16 + 32, PNG inside) | rasters of the favicon cut, transparent corners | 16, 32 |
| `apple-touch-icon-180.png` | full-bleed square, no rounding (iOS masks it) | 180 x 180 |
| `menubar-template.svg`, `menubar-template.png`, `menubar-template@2x.png` | macOS menu bar glyph, black on transparent: set it as a template image so the system tints it | 18, 18, 36 |
| `vscode-icon-128.png` | Marketplace-style extension icon | 128 x 128 |

## Font choice

There is no font. "Shipmiracle" and the tagline "Ship it with miracles." are hand-drawn geometric rounded sans letter shapes (round-capped strokes, one weight per size) turned into filled paths by a script; they are not Inter, Geist or any installed font and nothing is embedded or referenced. The capital S is the logo's own S skeleton at a lighter weight. The banner and social SVGs contain no `<text>` and no `font-family`, so they look the same everywhere. If the name is ever set in running text elsewhere, use any neutral sans (Inter or system UI); the drawn wordmark is the logo.

## How the PNGs were made

Each SVG was drawn in a browser page at the exact pixel size (1x) and captured; transparent PNGs come from two captures on white and black, merged into alpha. `favicon.ico` is a plain ICO header around the two PNGs (no tool needed).

## To do (owner or later)

- Mac app icon: open the four layered SVGs in Icon Composer on the owner's Mac, follow `icon/README.md`, save the `.icon` file for the Mac app.
- GitHub social preview: upload `brand/social-preview-1280x640.png` by hand (Repository Settings > Social preview; web only, no API).
- VS Code extension icon: `vscode-icon-128.png` is ready. `vscode-ext/shipmiracle-panel/package.json` has no top-level `icon` field yet; when wanted, copy the file to `vscode-ext/shipmiracle-panel/media/icon-128.png` and add `"icon": "media/icon-128.png"`.
- Menu bar: `menubar-template*.png` are for the Mac app's status item (`NSImage.isTemplate = true`); not wired anywhere yet.
