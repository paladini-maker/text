#!/usr/bin/env python3
"""Apply FORMA v2.0 fixes to an extracted paladini-maker/text repository."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HELPERS = r'''getFormaRuntime() =>
  if(!window.__FORMA_RUNTIME) {
    window.__FORMA_RUNTIME = {
      generationRunning: false,
      enhancementRunning: false,
      cancelRequested: false,
      toastTimer: null
    };
  }
  return window.__FORMA_RUNTIME;

setButtonLabel(button, selector, value) =>
  if(!button) return;
  let label = button.querySelector(selector);
  if(label) label.textContent = value;

setGenerationUi(running) =>
  let runtime = getFormaRuntime();
  let ids = ["prompt", "negativePrompt", "style", "resolution", "guidance", "batch", "seed", "resetBtn", "clearGalleryBtn"];
  for(let id of ids) {
    let field = document.getElementById(id);
    if(field) field.disabled = running;
  }
  let generateButton = document.getElementById("generateBtn");
  if(generateButton) {
    generateButton.disabled = running;
    setButtonLabel(generateButton, ".generate-label", running ? "Generating…" : "Generate images");
  }
  let enhanceButton = document.getElementById("enhanceBtn");
  if(enhanceButton) enhanceButton.disabled = running || runtime.enhancementRunning;
  let cancelButton = document.getElementById("cancelBtn");
  if(cancelButton) {
    cancelButton.hidden = !running;
    cancelButton.disabled = !running;
  }
  let studio = document.getElementById("formaStudio");
  if(studio) studio.setAttribute("aria-busy", String(running));
  let gallery = document.getElementById("gallery");
  if(gallery) gallery.setAttribute("aria-busy", String(running));

updateGalleryCount() =>
  let gallery = document.getElementById("gallery");
  let countEl = document.getElementById("resultCount");
  if(!gallery || !countEl) return;
  let total = gallery.querySelectorAll(".result-card.is-complete").length;
  countEl.textContent = total + (total === 1 ? " image" : " images");

studioToast(message, tone) =>
  let toast = document.getElementById("studioToast");
  if(!toast) return;
  let runtime = getFormaRuntime();
  if(runtime.toastTimer) clearTimeout(runtime.toastTimer);
  toast.textContent = String(message || "");
  toast.className = "studio-toast is-visible " + (tone || "");
  runtime.toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 3200);

'''

ENHANCE_FUNCTION = r'''async enhancePrompt() =>
  let runtime = getFormaRuntime();
  if(runtime.enhancementRunning || runtime.generationRunning) return;

  let promptEl = document.getElementById("prompt");
  let button = document.getElementById("enhanceBtn");
  let original = promptEl ? promptEl.value.trim() : "";
  if(!original) {
    studioToast("Write a prompt before enhancing it.", "warning");
    return;
  }

  let styleEl = document.getElementById("style");
  let styleName = styleEl && styleEl.selectedOptions.length
    ? styleEl.selectedOptions[0].textContent
    : "Natural";

  runtime.enhancementRunning = true;
  if(button) button.disabled = true;
  setButtonLabel(button, ".enhance-label", "Refining…");

  try {
    let task = aiText({
      instruction: "You are an expert visual art director and text-to-image prompt engineer. Rewrite the user's idea into one polished, specific, visually coherent image prompt. Preserve the subject, intent, and important details. Improve composition, camera or rendering language, lighting, materials, environment, color relationships, and visual hierarchy only where relevant. Avoid contradictions, filler, quality-token spam, artist-name imitation, policy evasion, and instructions to render readable text unless the user requested typography. The selected direction is: " + styleName + ". Return only the final prompt, with no heading or explanation.\n\nUser idea:\n" + original,
      startWith: "",
      hideStartWith: true
    });

    let result = await task.onFinishPromise;
    if(result && result.stopReason === "error") {
      throw new Error("AI Text Plugin reported a generation error.");
    }

    let enhancedText = String(result && result.generatedText || "").trim();
    if(!enhancedText) {
      throw new Error("AI returned an empty prompt.");
    }

    if(!promptEl || promptEl.value.trim() !== original) {
      studioToast("The prompt changed while refinement was running. Your edits were preserved.", "warning");
      return;
    }

    promptEl.value = enhancedText;
    updatePromptMetrics();
    saveStudioState();
    studioToast("Prompt refined.", "success");

  } catch(error) {
    console.error("FORMA prompt enhancement failed:", error);
    studioToast("Prompt enhancement failed. Your original text was preserved.", "error");
  } finally {
    runtime.enhancementRunning = false;
    if(button) button.disabled = runtime.generationRunning;
    setButtonLabel(button, ".enhance-label", "Enhance prompt");
  }

'''

GENERATE_FUNCTION = r'''async generateImages() =>
  let runtime = getFormaRuntime();
  if(runtime.generationRunning) return;
  if(runtime.enhancementRunning) {
    studioToast("Wait for prompt refinement to finish before generating.", "warning");
    return;
  }

  let promptEl = document.getElementById("prompt");
  let negativeEl = document.getElementById("negativePrompt");
  let styleEl = document.getElementById("style");
  let resolutionEl = document.getElementById("resolution");
  let guidanceEl = document.getElementById("guidance");
  let batchEl = document.getElementById("batch");
  let seedEl = document.getElementById("seed");
  let generateButton = document.getElementById("generateBtn");
  let gallery = document.getElementById("gallery");
  let status = document.getElementById("batchStatus");
  let progress = document.getElementById("batchProgress");

  if(!promptEl || !gallery || !generateButton) {
    console.error("FORMA: required generation elements are missing.");
    return;
  }

  let basePrompt = promptEl.value.trim();
  if(!basePrompt) {
    studioToast("Add an image description before generating.", "warning");
    promptEl.focus();
    return;
  }
  if(basePrompt.length > 4000) {
    studioToast("The prompt exceeds the 4,000 character limit.", "warning");
    promptEl.focus();
    return;
  }

  let styleName = styleEl ? styleEl.value : "natural";
  let styleDirections = {
    natural: "natural visual language, coherent lighting, intentional composition",
    editorial: "high-end fashion editorial photography, confident art direction, elegant composition, tactile materials, refined color grading",
    cinematic: "cinematic lighting, atmospheric depth, filmic color science, deliberate camera framing, production-design detail",
    photoreal: "photorealistic image, physically plausible materials, natural skin and surface detail, accurate perspective, realistic light transport",
    anime: "polished anime illustration, expressive shape language, intentional linework, nuanced cel shading, rich but controlled colors",
    illustration: "contemporary editorial illustration, distinctive shapes, layered texture, sophisticated palette, clean visual hierarchy",
    threeD: "premium 3D render, physically based materials, nuanced reflections, refined studio lighting, carefully composed depth",
    product: "premium commercial product photography, precise studio lighting, clean material definition, controlled reflections, luxury advertising composition",
    watercolor: "traditional watercolor painting, transparent pigment layers, subtle paper grain, expressive edges, delicate color transitions"
  };
  if(!Object.prototype.hasOwnProperty.call(styleDirections, styleName)) {
    studioToast("The selected visual direction is not valid.", "warning");
    return;
  }

  let finalPrompt = basePrompt + ", " + styleDirections[styleName];
  let negativePrompt = negativeEl ? negativeEl.value.trim() : "";
  let resolution = resolutionEl ? resolutionEl.value : "512x512";
  let validResolutions = ["512x512", "512x768", "768x512", "768x768"];
  if(!validResolutions.includes(resolution)) {
    studioToast("The selected image dimensions are not supported.", "warning");
    return;
  }

  let guidance = guidanceEl ? Number(guidanceEl.value) : 7;
  if(!Number.isInteger(guidance) || guidance < 1 || guidance > 30) {
    studioToast("Prompt guidance must be a whole number from 1 to 30.", "warning");
    return;
  }

  let rawCount = batchEl ? Number(batchEl.value) : 1;
  let count = Number.isFinite(rawCount)
    ? Math.max(1, Math.min(4, Math.floor(rawCount)))
    : 1;

  let seedText = seedEl ? seedEl.value.trim() : "";
  let seedBase = seedText === "" ? null : Number(seedText);
  if(seedBase !== null && (
    !Number.isSafeInteger(seedBase) ||
    seedBase < 1 ||
    seedBase + count - 1 > Number.MAX_SAFE_INTEGER
  )) {
    studioToast("Seed must be a positive safe whole number.", "warning");
    if(seedEl) seedEl.focus();
    return;
  }

  let emptyState = document.getElementById("emptyState");
  if(emptyState) emptyState.remove();
  gallery.classList.add("has-results");
  runtime.generationRunning = true;
  runtime.cancelRequested = false;
  setGenerationUi(true);

  let completed = 0;
  let failed = 0;
  let cancelled = false;
  let startedAt = Date.now();
  if(status) status.textContent = "Preparing " + count + (count === 1 ? " image" : " images");
  if(progress) progress.style.width = "0%";

  try {
    for(let index = 0; index < count; index++) {
      if(runtime.cancelRequested) {
        cancelled = true;
        break;
      }

      let card = document.createElement("article");
      card.className = "result-card is-loading";
      let media = document.createElement("div");
      media.className = "result-media";
      let loader = document.createElement("div");
      loader.className = "result-loading";
      loader.textContent = "Creating frame " + (index + 1) + " / " + count;
      media.appendChild(loader);

      let details = document.createElement("div");
      details.className = "result-details";
      let label = document.createElement("span");
      label.className = "result-index";
      label.textContent = "FRAME " + String(index + 1).padStart(2, "0");
      let promptSummary = document.createElement("p");
      promptSummary.className = "result-prompt";
      promptSummary.textContent = finalPrompt;
      details.append(label, promptSummary);
      card.append(media, details);
      gallery.appendChild(card);

      try {
        let options = {
          prompt: finalPrompt,
          negativePrompt: negativePrompt,
          resolution: resolution,
          guidanceScale: guidance
        };
        if(seedBase !== null) options.seed = seedBase + index;

        let result = await image(options);
        let imageUrl = result && typeof result.dataUrl === "string" ? result.dataUrl : "";
        if(!imageUrl || !/^data:image\/[a-z0-9.+-]+;base64,/i.test(imageUrl)) {
          let pluginMessage = String(result || "Empty plugin response")
            .replace(/<[^>]*>/g, "")
            .slice(0, 240);
          throw new Error(pluginMessage || "The image plugin did not return a valid image.");
        }

        let imageElement = document.createElement("img");
        imageElement.src = imageUrl;
        imageElement.alt = finalPrompt;
        imageElement.loading = "lazy";
        imageElement.decoding = "async";
        if(typeof imageElement.decode === "function") await imageElement.decode();

        media.replaceChildren(imageElement);
        card.classList.remove("is-loading");
        card.classList.add("is-complete");

        let actions = document.createElement("div");
        actions.className = "result-actions";
        let download = document.createElement("a");
        download.className = "result-download";
        download.href = imageUrl;
        download.download = "forma-image-" + Date.now() + "-" + (index + 1) + ".png";
        download.textContent = "Download image";
        download.setAttribute("aria-label", "Download generated image " + (index + 1));
        actions.appendChild(download);
        details.appendChild(actions);
        completed++;

      } catch(error) {
        failed++;
        card.classList.remove("is-loading");
        card.classList.add("has-error");
        loader.className = "result-error";
        let message = error && error.message ? error.message : "Unknown error";
        loader.textContent = "Generation failed: " + String(message).slice(0, 240);
        console.error("FORMA image generation failed:", error);
      }

      if(progress) progress.style.width = Math.round(((index + 1) / count) * 100) + "%";
      if(status) status.textContent = "Completed " + (index + 1) + " of " + count;
      if(runtime.cancelRequested) {
        cancelled = true;
        break;
      }
    }
  } catch(error) {
    console.error("FORMA batch generation failed:", error);
    if(status) status.textContent = "Generation stopped unexpectedly.";
    studioToast("Generation stopped because of an unexpected error.", "error");
  } finally {
    runtime.generationRunning = false;
    runtime.cancelRequested = false;
    setGenerationUi(false);
    saveStudioState();
    updateGalleryCount();
  }

  let elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);
  if(status) {
    status.textContent = (cancelled ? "Stopped · " : "") +
      completed + " ready · " + failed + " failed · " + elapsed + "s";
  }
  if(completed) {
    studioToast(
      completed + (completed === 1 ? " image generated." : " images generated.") +
      (cancelled ? " Remaining images were skipped." : ""),
      "success"
    );
  } else if(failed) {
    studioToast("No valid image was generated. Check the error details and try again.", "error");
  } else if(cancelled) {
    studioToast("Batch cancelled.", "warning");
  }
'''

CANCEL_FUNCTION = r'''cancelGeneration() =>
  let runtime = getFormaRuntime();
  if(!runtime.generationRunning) return;
  runtime.cancelRequested = true;
  let cancelButton = document.getElementById("cancelBtn");
  if(cancelButton) cancelButton.disabled = true;
  let status = document.getElementById("batchStatus");
  if(status) status.textContent = "Stopping after the current image…";
'''

CANCEL_CSS = r'''
.cancel-button {
  display: block;
  width: 100%;
  min-height: 39px;
  margin-top: 9px;
  padding: 8px 12px;
  border: 1px solid #e3c9c2;
  border-radius: 10px;
  background: #fff8f6;
  color: #8e4439;
  font-size: 10px;
  font-weight: 800;
  transition: background .15s ease, border-color .15s ease;
}
.cancel-button:hover:not(:disabled) { background: #fbe9e5; border-color: #d7a79d; }
#formaStudio .cancel-button[hidden] { display: none !important; }
#formaStudio button:focus-visible,
#formaStudio a:focus-visible,
#formaStudio input:focus-visible,
#formaStudio textarea:focus-visible,
#formaStudio select:focus-visible {
  outline: 2px solid #8eae43;
  outline-offset: 3px;
}
#formaStudio .generate-button:disabled { transform: none; }
#formaStudio .result-card.has-error { border-color: #d8b8b1; }
#formaStudio [aria-busy="true"] { cursor: progress; }
'''

README = '''# FORMA — AI Image Studio

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
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"Expected exactly one {label} anchor, found {count}.")
    return text.replace(old, new, 1)


def update_main(original: str) -> str:
    if "getFormaRuntime() =>" in original:
        raise ValueError("FORMA v2 helpers already exist; refusing to apply the patch twice.")
    text = replace_once(original, "studioToast(message, tone) =>\n", HELPERS, "toast helper")
    text = replace_once(
        text,
        'if(seedEl) seedEl.value = String(Math.floor(Math.random() * 900000000) + 100000000);',
        'if(seedEl) seedEl.value = String(Math.floor(Math.random() * 900000000) + 1);',
        "seed randomizer"
    )
    text = replace_once(
        text,
        '  if(charEl) charEl.textContent = value.length.toLocaleString();',
        '  if(charEl) charEl.textContent = Array.from(value).length.toLocaleString();',
        "character counter"
    )
    text, n = re.subn(
        r"async enhancePrompt\(\) =>[\s\S]*?(?=\nasync generateImages\(\) =>)",
        lambda _: ENHANCE_FUNCTION.rstrip("\n"), text, count=1
    )
    if n != 1:
        raise ValueError("Could not replace enhancePrompt().")
    text, n = re.subn(
        r"async generateImages\(\) =>[\s\S]*?(?=\nclearGallery\(\) =>)",
        lambda _: GENERATE_FUNCTION.rstrip("\n"), text, count=1
    )
    if n != 1:
        raise ValueError("Could not replace generateImages().")
    text = replace_once(text, "\nclearGallery() =>", "\n" + CANCEL_FUNCTION + "\nclearGallery() =>", "gallery cancel hook")
    text = replace_once(
        text,
        'clearGallery() =>\n  let gallery = document.getElementById("gallery");',
        'clearGallery() =>\n  let runtime = getFormaRuntime();\n  if(runtime.generationRunning) {\n    studioToast("Stop the current batch before clearing the gallery.", "warning");\n    return;\n  }\n  let gallery = document.getElementById("gallery");',
        "clear-gallery lock"
    )
    text = replace_once(
        text,
        'resetStudio() =>\n  let defaults = {',
        'resetStudio() =>\n  let runtime = getFormaRuntime();\n  if(runtime.generationRunning) {\n    studioToast("Stop the current batch before resetting the studio.", "warning");\n    return;\n  }\n  let defaults = {',
        "reset lock"
    )
    return text


def update_html(original: str) -> str:
    text = replace_once(
        original,
        '<button id="enhanceBtn" class="secondary-button" type="button" onclick="enhancePrompt()">Enhance prompt <span>↗</span></button>',
        '<button id="enhanceBtn" class="secondary-button" type="button" onclick="enhancePrompt()"><span class="enhance-label">Enhance prompt</span><span>↗</span></button>',
        "enhance button"
    )
    text = replace_once(
        text,
        '<input id="seed" class="seed-input" type="number" min="0" step="1" placeholder="Random" onchange="saveStudioState();">',
        '<input id="seed" class="seed-input" type="number" min="1" step="1" placeholder="Random" aria-label="Generation seed; leave empty for random" onchange="saveStudioState();">',
        "seed input"
    )
    text = replace_once(
        text,
        '<button id="generateBtn" class="generate-button" type="button" onclick="generateImages()"><span class="generate-mark">✳</span><span>Generate images</span><span class="generate-arrow">↗</span></button>\n        <button class="reset-button" type="button" onclick="resetStudio()">Reset controls</button>',
        '<button id="generateBtn" class="generate-button" type="button" onclick="generateImages()"><span class="generate-mark">✳</span><span class="generate-label">Generate images</span><span class="generate-arrow">↗</span></button>\n        <button id="cancelBtn" class="cancel-button" type="button" onclick="cancelGeneration()" hidden>Stop after current image</button>\n        <button id="resetBtn" class="reset-button" type="button" onclick="resetStudio()">Reset controls</button>',
        "generate, cancel and reset controls"
    )
    text = replace_once(
        text,
        '<button class="clear-gallery-button" type="button" onclick="clearGallery()">Clear gallery <span>×</span></button>',
        '<button id="clearGalleryBtn" class="clear-gallery-button" type="button" onclick="clearGallery()">Clear gallery <span>×</span></button>',
        "clear-gallery button"
    )
    text = replace_once(
        text,
        '<div id="gallery" class="results-grid">',
        '<div id="gallery" class="results-grid" aria-busy="false">',
        "gallery busy state"
    )
    return text


def update_css(original: str) -> str:
    if "cancel-button" in original:
        raise ValueError("FORMA cancel styles already exist; refusing to apply the patch twice.")
    text, n = re.subn(r"^:root\s*\{", ".forma-studio {", original, count=1, flags=re.M)
    if n != 1:
        raise ValueError("Could not scope the CSS custom properties to .forma-studio.")
    text, n = re.subn(
        r"html,\s*body\s*\{[\s\S]*?\n\}\n\nbody > \* \{ box-sizing: border-box; \}\n",
        "", text, count=1
    )
    if n != 1:
        raise ValueError("Could not locate global html/body CSS rules.")
    text = replace_once(
        text,
        '  color: var(--forma-ink);\n  font-size: 14px;',
        '  color: var(--forma-ink);\n  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;\n  text-align: left;\n  background: var(--forma-paper);\n  min-height: 100vh;\n  font-size: 14px;',
        "studio background"
    )
    text = replace_once(text, ".reset-button {", CANCEL_CSS + "\n.reset-button {", "cancel button styles")
    text = replace_once(
        text,
        '  .results-grid { grid-template-columns: 1fr; }\n  .result-media { aspect-ratio: 1 / 1; }',
        '  .results-grid { grid-template-columns: 1fr; }\n  .result-media { aspect-ratio: 1 / 1; }\n  .cancel-button { min-height: 42px; }',
        "mobile cancel button style"
    )
    return text


def validate(main: str, html: str, css: str) -> None:
    required = [
        "getFormaRuntime() =>", "setGenerationUi(running) =>", "cancelGeneration() =>",
        "await task.onFinishPromise", "result.generatedText", 'result.stopReason === "error"',
        "promptEl.value.trim() !== original", "gallery.appendChild(card)", "seedBase < 1",
        "data:image", "updateGalleryCount()"
    ]
    for token in required:
        if token not in main:
            raise ValueError(f"Post-patch validation failed: missing {token!r}.")
    ids = re.findall(r'\bid=["\']([^"\']+)["\']', html)
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate HTML IDs detected.")
    missing = [x for x in set(re.findall(r'getElementById\(["\']([^"\']+)["\']\)', main)) if x not in ids]
    if missing:
        raise ValueError("Missing DOM elements: " + ", ".join(sorted(missing)))
    handlers = set(re.findall(r'onclick=["\']\s*([A-Za-z_$][\w$]*)\s*\(', html))
    undefined = [x for x in handlers if not re.search(rf'(?:async\s+)?{re.escape(x)}\(\)\s*=>', main)]
    if undefined:
        raise ValueError("Undefined HTML event handlers: " + ", ".join(sorted(undefined)))
    if re.search(r'html,\s*body\s*\{|body > \*', css):
        raise ValueError("Unscoped global body CSS remains.")


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def main_cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Extracted repository directory (default: current directory).")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without writing files.")
    args = parser.parse_args()
    root = args.root.resolve()
    paths = {
        "main": root / "main.pjs",
        "pjs": root / "src" / "01-code-panel.txt",
        "html": root / "src" / "02-html-panel.html",
        "css": root / "src" / "03-css-panel.css",
    }
    for path in paths.values():
        if not path.is_file():
            print(f"ERROR: required source file not found: {path}", file=sys.stderr)
            return 2
    try:
        original_pjs = paths["pjs"].read_text(encoding="utf-8")
        original_main = paths["main"].read_text(encoding="utf-8")
        if original_main != original_pjs:
            raise ValueError("main.pjs and src/01-code-panel.txt differ. Reconcile them before patching.")
        updated_main = update_main(original_pjs)
        updated_html = update_html(paths["html"].read_text(encoding="utf-8"))
        updated_css = update_css(paths["css"].read_text(encoding="utf-8"))
        validate(updated_main, updated_html, updated_css)
        preview = updated_html + "\n<style>\n" + updated_css + "\n</style>\n"
        outputs = {
            paths["main"]: updated_main,
            paths["pjs"]: updated_main,
            paths["html"]: updated_html,
            paths["css"]: updated_css,
            root / "index.html": preview,
            root / "README.md": README,
        }
        if args.dry_run:
            print("DRY RUN OK")
            for path, content in outputs.items():
                print(f"{path.relative_to(root)}: {len(content)} characters")
            return 0
        backup = root / ".forma-v1-backup"
        backup.mkdir(exist_ok=True)
        for path in outputs:
            if path.exists():
                backup_path = backup / path.relative_to(root)
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                backup_path.write_bytes(path.read_bytes())
        for path, content in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, content)
        print("FORMA v2.0 patch applied.")
        print("Updated: main.pjs, src/01-code-panel.txt, src/02-html-panel.html, src/03-css-panel.css, index.html, README.md")
        print("Original files backed up under .forma-v1-backup/")
        print("Validation: DOM IDs, event handlers, cancellation flow, image output checks, positive seeds and CSS scoping passed.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main_cli())
