# GitHub README logo

The finalized asset set currently includes the dark-surface lockup below. The
light lockup and social preview listed in the broader brand guidelines were not
supplied in this workspace, so this snippet uses only an asset that exists.

Paste this at the top of the repository's root `README.md`. GitHub swaps the light and dark lockups to match the viewer's theme. Both are outlined SVGs, so they render without fonts.

```html
<p align="center">
  <img alt="ResolveAI" src="docs/design/resolveai-logo-dark.svg" height="48">
</p>

<p align="center"><strong>Support that remembers.</strong></p>
```

Notes

- The path is relative to the repository root. If the README lives elsewhere,
  adjust it.
- Height 48 px suits a README header; the lockup is vector and scales cleanly. Keep it at 24 px or taller.
- A social preview is not included until the finalized image asset is supplied.
- Social preview: upload `social-preview.png` under Repository → Settings → General → Social preview. It is 1200 × 630 and about 30 KB, well under GitHub's 1 MB limit.
