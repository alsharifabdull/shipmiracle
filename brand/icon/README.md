# App icon layers (Icon Composer)

Approved logo, 26 Oct 2026: S1 Sign-off S + A Twinkle star, porcelain tile, graphite S, deep amber star.

| File | Layer | Notes |
|---|---|---|
| `background.svg` | 01-background | full-bleed 1024 square, gradient `#F4EFE6` to `#D9D1C4`, unmasked (the system masks the corners) |
| `foreground.svg` | 02-foreground | the S, flat `#2C3036`, outlined, content centred |
| `accent.svg` | 03-accent | the twinkle star, flat `#B05100`, its own layer so it gets its own glass |
| `monochrome.svg` | glyph | black with alpha (S full, star 78%) for the Mono and Tinted appearances |

These four files are byte-for-byte the approved round 13 set. Previews (not for the app): `AppIcon-preview-1024.png` (default), `-dark-`, `-clear-`, `-tinted-`, the composed icon in the 824-in-1024 body with a top light, rim and shadow imitated by SVG filters. Real Liquid Glass only appears inside Icon Composer.

## Icon Composer steps

1. Open Xcode 26 or later, then Xcode > Open Developer Tool > Icon Composer. Without Xcode, download Icon Composer from developer.apple.com/icon-composer. It opens with a default icon and a solid background.
2. File > Save as AppIcon. The name must match the App Icon field in the Xcode target, without the extension.
3. Drag `background.svg` onto the sidebar, then `foreground.svg`, then `accent.svg`. Each file becomes a layer and the sidebar order is the z-order, bottom to top (three groups, the limit is four).
4. Select the background layer. Keep the gradient from the file, or set Fill to Gradient in the Style inspector with `#F4EFE6` and `#D9D1C4` (Apple prefers the second).
5. Select the foreground and the accent group one at a time. Set Liquid Glass Specular to Automatic, Blur and Translucency low, Shadow on, and use Individual mode so the star catches its own highlight above the S.
6. Click Dark, then Mono in the appearance row. In Dark use tile `#3B4046` to `#14161A`, S `#FBF5E9` to `#E5DCCB`, star `#FFB02E` to `#F58F00`. In Mono set the foreground to white and the star to 78% opacity (the weights in `monochrome.svg`), then check Tinted on and off. Check 16 and 32 px with the preview size menu.
7. Save. Drag the `.icon` file into the Xcode project navigator and set it as the App Icon in the target General tab. Export the 1024 marketing PNG from Icon Composer if needed.

## Colours

Porcelain `#F4EFE6` to `#D9D1C4`; graphite S `#3C4148` to `#1B1E23` (flat `#2C3036` in the layer); deep amber star `#C55F00` to `#9C4300` (flat `#B05100` in the layer). See `../colors.md` for the dark values and contrast numbers.

## Not verified

Nothing here was opened in Icon Composer or Xcode. The `.icon` file does not exist yet; the owner exports it on his Mac.
