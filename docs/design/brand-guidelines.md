# ResolveAI brand guidelines

Version 1.0 · 24 Nov 2026 · Direction: **Concept 03, Breakout** (final; no further exploration).

Tagline: **Support that remembers.**

## 1. The logo

**Symbol.** A circle with one sharp lower-left corner. A check mark is cut out of it and breaks through the outline at the upper right. The cut is a real hole in the path, not a mask or a background-colored fill, so it shows whatever sits behind it.

**Lockup.** Symbol + "ResolveAI" in Inter: "Resolve" SemiBold, "AI" Medium in the accent color, tracking −2.5%. The wordmark is outlined to paths, so the SVGs need no font and no network.

**Geometry (48-unit grid, do not redraw; use the files).** Circle r20 at (24,24), lower-left quadrant replaced by a corner at (4,44). Check stroke 5.5 through (14,25.5) → (21,32.5) → (42,9), round caps and join. Symbol-to-wordmark gap: 14 units.

| File | Use |
|---|---|
| `resolveai-logo-light.svg` | Lockup for light surfaces (off-white, white) |
| `resolveai-logo-dark.svg` | Lockup for dark surfaces (dark slate) |
| `resolveai-symbol.svg` | Symbol, indigo, for light surfaces |
| `resolveai-symbol-dark.svg` | Symbol, light indigo, for dark surfaces |
| `resolveai-symbol-monochrome.svg` | One-color uses; fill is `currentColor` |
| `favicon.svg` | Browser tab icon; switches color with the browser's light/dark scheme |
| `favicon.ico` | Fallback tab icon, frames at 16, 24, 32, 48 px |
| `app-icon-192.png`, `app-icon-512.png` | PWA / home-screen icons |
| `social-preview.png` | 1200 × 630, GitHub social preview and `og:image` |
| `github-readme-logo.md` | Paste-ready README header |

All SVGs have transparent backgrounds. The app icons are opaque, full-bleed squares on purpose (see section 5).

**Clear space.** One quarter of the symbol's height on every side.
**Minimum size.** Symbol 16 px. Lockup 24 px tall; below that, use the symbol alone.

**Don't:** recolor outside the palette · fill the cutout · stretch, rotate, outline or add shadows · retype the wordmark in live text · put indigo `#4F46E5` on dark slate or light indigo `#8B93FF` on light surfaces (both fail contrast, see below).

## 2. Color

| Name | Hex | Role |
|---|---|---|
| Resolve Indigo | `#4F46E5` | Primary. Symbol and "AI" on light surfaces; actions |
| Indigo Light | `#8B93FF` | Dark-mode accent. Symbol and "AI" on dark surfaces |
| Dark Slate | `#0F172A` | Dark surface; "Resolve" and body text on light |
| Off-white | `#F7F6F2` | Light surface; "Resolve" on dark; symbol on the indigo app icon |

Contrast (WCAG 2.x; text needs 4.5:1, graphics and large text 3:1):

| Pair | Ratio | Verdict |
|---|---|---|
| Indigo on off-white | 5.81:1 | Pass |
| Indigo on white | 6.29:1 | Pass |
| Indigo Light on dark slate | 6.56:1 | Pass |
| Dark slate on off-white | 16.51:1 | Pass |
| Off-white on indigo (app icon) | 5.81:1 | Pass |
| Indigo on dark slate | 2.84:1 | **Fail. Use Indigo Light.** |
| Indigo Light on off-white | 2.52:1 | **Fail. Use Indigo.** |

## 3. Typography

Inter throughout. UI and body: 400 / 500. Headings: 600 with about −2% tracking. The tagline is set in Inter Medium, sentence case, with the final period. Fallback stack: `Inter, system-ui, -apple-system, "Segoe UI", sans-serif`.

## 4. One symbol everywhere

The same symbol file family is used in every placement. Don't make per-surface variants.

| Placement | Asset | Notes |
|---|---|---|
| Website navigation | Lockup light/dark, 28–32 px tall | Collapse to the symbol alone on narrow screens |
| Chatbot avatar | Symbol (`-dark` on dark UIs), 24–40 px | If the UI needs a filled container, use `app-icon-192.png`; it holds up under square, rounded and circular masks |
| Documentation | Lockup in the header, symbol inline | Same files as the product |
| Browser tab | `favicon.svg`, then `favicon.ico` | See section 5 |
| README | `github-readme-logo.md` | Switches light/dark on GitHub |

## 5. Integration

```html
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon.ico" sizes="48x48">
```

```json
{ "icons": [
  { "src": "/app-icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable" },
  { "src": "/app-icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable" } ] }
```

The app icons are an indigo square with the off-white symbol, sized so the whole symbol sits within the 40% maskable safe zone (measured: 38.5%). The check shows the indigo behind it, because it is a hole.

Inline symbol (inherits `color`, so it follows your theme tokens):

```html
<svg viewBox="4 4 40 40" width="32" height="32" role="img" aria-label="ResolveAI">
  <path fill="currentColor" d="M4 24A20 20 0 0 1 24 4A20 20 0 0 1 37.824 9.546L20.888 28.499L15.945 23.555A2.75 2.75 0 0 0 12.055 27.445L19.055 34.445A2.75 2.75 0 0 0 23.051 34.332L41.281 13.932A20 20 0 0 1 44 24A20 20 0 0 1 24 44H4Z"/>
</svg>
```

Loaded as an `<img>`, `resolveai-symbol-monochrome.svg` renders black. Inline it and set `color` for brand colors, or use the indigo files.

## 6. Verification record

- **Geometry.** The single-path symbol matches the original masked Breakout construction in both librsvg and Chromium. The check walls, caps and corner are identical; the only differences are on circular arcs, at most about 0.2 px at 30 px per unit.
- **Transparency.** Check channel and notch exit are alpha 0; composited over magenta, magenta shows through the check.
- **Self-contained.** No `<text>`, fonts, images, scripts, masks, filters, or external references in any SVG.
- **Renderers.** The lockup renders the same in Chromium and librsvg (1 of 457k pixels differs).
- **Favicon legibility.** At 16, 24, 32 and 48 px the check channel stays open (coverage ≤ 0.02) while the body is solid.
- **Favicon theming.** `favicon.svg` renders `#4F46E5` under a light scheme and `#8B93FF` under a dark scheme.

**Known limitation.** `favicon.ico` has no theme switch, so it is indigo only. Against typical browser tab colors, indigo is 4.80:1 on a light tab (`#DEE1E6`), but 2.56:1 on a deep dark tab (`#202124`) and 1.92:1 on a lighter dark tab (`#35363A`). Browsers that use `favicon.svg` are unaffected (Indigo Light is 5.91:1 and 4.43:1 on those same dark tabs). Only a browser that falls back to the `.ico` shows the dim version on dark. A dark-safe `.ico` would have to be a deliberate exception (for example an off-white tile); none was generated. Tab colors vary by browser and OS, so treat these as representative.
