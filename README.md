# FORMA — AI Image Studio

FORMA is a Perchance text-to-image generator with an editorial-style interface.

## Install in Perchance

1. Open your generator's **Code** panel and paste `src/01-code-panel.txt`.
2. Open the **HTML** panel and paste `src/02-html-panel.html`.
3. Open the **CSS** panel and paste `src/03-css-panel.css`.
4. Save and reload the generator.

The same Code panel source is mirrored in `main.pjs`. `index.html` is the combined preview artifact.

## Runtime dependencies

- Official Perchance `text-to-image-plugin`.
- Official Perchance `ai-text-plugin`.

FORMA does not require a user-supplied API key. Image and text generation are handled by Perchance's own plugin services and remain subject to their availability and usage rules.

## Features

- Text-to-image generation with negative prompts.
- Editorial, photographic, cinematic, anime, illustration, 3D, product and watercolor prompt directions.
- Supported canvas ratios, guidance scale, batch generation and reproducible positive seeds.
- AI prompt refinement with protection against overwriting edits made while refinement is running.
- Sequential batches, progress status, per-image errors and stop-after-current-image cancellation.
- Local browser preference persistence.
- Responsive layout, keyboard focus indicators and reduced-motion support.

## Files

| File | Purpose |
|---|---|
| `main.pjs` | Code panel source |
| `src/01-code-panel.txt` | Copy-ready Code panel |
| `src/02-html-panel.html` | Copy-ready HTML panel |
| `src/03-css-panel.css` | Copy-ready CSS panel |
| `index.html` | Combined preview |

## Notes

The image plugin input normalization treats a seed value of zero as unset. FORMA therefore accepts positive integer seeds; leaving the field empty requests a random seed. Cancelling a batch stops subsequent images after the currently running request settles; it does not interrupt an image request already in progress.
