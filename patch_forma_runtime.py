#!/usr/bin/env python3
"""Patch FORMA's Perchance plugin contracts in both mirrored Code-panel files."""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

FILES = (Path("src/01-code-panel.txt"), Path("main.pjs"))

TOAST_REPLACEMENT = '''studioToast(message, tone) =>
  let toast = document.getElementById("studioToast");
  if(!toast) return;

  let runtime = getFormaRuntime();
  if(runtime.toastTimer) clearTimeout(runtime.toastTimer);

  toast.textContent = String(message || "");
  toast.className = "studio-toast is-visible " + (tone || "");
  runtime.toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 3200);
'''

IMAGE_CALL_OLD = '''        let result = await image(options);
        let imageUrl = result && typeof result.dataUrl === "string" ? result.dataUrl : "";
'''

IMAGE_CALL_NEW = '''        // The Perchance image plugin returns a task object, not the final image data.
        let imageTask = image(options);
        if(!imageTask || !imageTask.onFinishPromise ||
          typeof imageTask.onFinishPromise.then !== "function") {
          throw new Error("The image plugin returned an unexpected task object.");
        }

        let result;
        let pluginFrame = null;
        try {
          // Keep the plugin iframe mounted while it runs; it may be needed for verification.
          if(typeof imageTask.iframeHtml === "string" && imageTask.iframeHtml.trim()) {
            let frameHost = document.createElement("div");
            frameHost.innerHTML = imageTask.iframeHtml;
            pluginFrame = frameHost.firstElementChild;
            if(pluginFrame) document.body.appendChild(pluginFrame);
          }
          result = await imageTask.onFinishPromise;
        } finally {
          if(pluginFrame) pluginFrame.remove();
        }

        let imageUrl = result && typeof result.dataUrl === "string" ? result.dataUrl : "";
'''


def fail(message: str) -> None:
    raise RuntimeError(message)


def replace_section(source: str, start: str, end: str, replacement: str, label: str) -> str:
    if source.count(start) != 1:
        fail(f"{label}: expected one start marker, found {source.count(start)}")
    start_at = source.index(start)
    end_at = source.find(end, start_at + len(start))
    if end_at < 0:
        fail(f"{label}: end marker not found after start marker")
    return source[:start_at] + replacement + source[end_at:]


def patch_source(source: str, path: Path) -> str:
    original = source

    source = replace_section(
        source,
        "studioToast(message, tone) =>\n",
        "\nupdatePromptMetrics() =>",
        TOAST_REPLACEMENT,
        f"{path}: studioToast",
    )

    ai_pattern = re.compile(
        r'    let task = aiText\(\{\n(?P<body>.*?)\n    \}\);\n\n'
        r'    let result = await task\.onFinishPromise;',
        re.DOTALL,
    )
    matches = list(ai_pattern.finditer(source))
    if len(matches) != 1:
        fail(f"{path}: expected one aiText task block, found {len(matches)}")

    body = matches[0].group("body")
    if "onChunk:" in body:
        fail(f"{path}: aiText block already has onChunk; refusing to double-patch")
    hide_line = '      hideStartWith: true'
    if body.count(hide_line) != 1:
        fail(f"{path}: hideStartWith anchor missing or duplicated")
    body = body.replace(
        hide_line,
        hide_line + ''',
      onChunk: (data) => {
        if(data && typeof data.textChunk === "string") {
          streamedText += data.textChunk;
        } else if(data && typeof data.fullTextSoFar === "string") {
          streamedText = data.fullTextSoFar;
        }
      }''',
        1,
    )
    ai_replacement = (
        '    let streamedText = "";\n'
        '    let result = await aiText({\n'
        + body
        + '\n    });'
    )
    source = ai_pattern.sub(lambda _match: ai_replacement, source, count=1)

    old_text = '    let enhancedText = String(result && result.generatedText || "").trim();'
    new_text = '''    let enhancedText = String(
      (typeof result === "string" ? result : "") ||
      (result && (result.generatedText || result.text)) ||
      streamedText ||
      ""
    ).trim();'''
    if source.count(old_text) != 1:
        fail(f"{path}: expected one enhancedText extraction, found {source.count(old_text)}")
    source = source.replace(old_text, new_text, 1)

    if source.count(IMAGE_CALL_OLD) != 1:
        fail(f"{path}: expected one direct image(options) await block")
    source = source.replace(IMAGE_CALL_OLD, IMAGE_CALL_NEW, 1)

    old_download = '        download.download = "forma-image-" + Date.now() + "-" + (index + 1) + ".png";'
    new_download = '''        let mimeType = (imageUrl.match(/^data:image\\/([a-z0-9.+-]+);base64,/i) || [null, "png"])[1].toLowerCase();
        let fileExtension = mimeType === "jpeg" ? "jpg" : mimeType;
        download.download = "forma-image-" + Date.now() + "-" + (index + 1) + "." + fileExtension;'''
    if source.count(old_download) != 1:
        fail(f"{path}: expected one PNG-only download filename")
    source = source.replace(old_download, new_download, 1)

    # Fail closed if any targeted defect remains or mirrored source changed unexpectedly.
    if source.count('let toast = document.getElementById("studioToast");') != 1:
        fail(f"{path}: duplicate toast declaration remains")
    if "task.onFinishPromise" in source:
        fail(f"{path}: stale aiText task.onFinishPromise access remains")
    if "await image(options)" in source:
        fail(f"{path}: stale direct image(options) await remains")
    if "let result = await aiText({" not in source:
        fail(f"{path}: direct awaited aiText call missing")
    if source == original:
        fail(f"{path}: no changes were made")
    return source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate and show planned changes without writing files")
    args = parser.parse_args()

    missing = [str(path) for path in FILES if not path.is_file()]
    if missing:
        print("Missing expected files: " + ", ".join(missing), file=sys.stderr)
        return 2

    current = {path: path.read_text(encoding="utf-8") for path in FILES}
    if current[FILES[0]] != current[FILES[1]]:
        print("Refusing to patch: src/01-code-panel.txt and main.pjs are not identical mirrors.", file=sys.stderr)
        return 3

    patched = {path: patch_source(current[path], path) for path in FILES}
    if patched[FILES[0]] != patched[FILES[1]]:
        print("Refusing to write: patched mirror files differ.", file=sys.stderr)
        return 4

    if args.dry_run:
        print("PASS: both mirrored Code-panel files match and all replacement anchors are unique.")
        print("Planned updates: toast syntax, aiText await/stream handling, image task iframe lifecycle, MIME-aware downloads.")
        return 0

    for path in FILES:
        backup = path.with_suffix(path.suffix + ".bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(patched[path], encoding="utf-8", newline="\n")
        temp.replace(path)

    print("PASS: patched both mirrored Code-panel files.")
    print("Backups created with .bak suffix where no backup already existed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
