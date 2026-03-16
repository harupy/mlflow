"""Convert trace-perf-analysis.md to a version with base64-embedded images.

Replaces all Markdown image references (![alt](path)) with inline base64
data URIs so the document is self-contained and can be pasted into Google Docs
via a Markdown-to-Google-Docs converter.
"""

import base64
import mimetypes
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "trace-perf-analysis.md"
DEFAULT_OUTPUT = SCRIPT_DIR / "trace-perf-analysis-embedded.md"

IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def embed_image(match: re.Match, base_dir: Path) -> str:
    alt_text = match.group(1)
    image_path = base_dir / match.group(2)

    if not image_path.exists():
        print(
            f"WARNING: image not found, keeping original reference: {image_path}",
            file=sys.stderr,
        )
        return match.group(0)

    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
    data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"![{alt_text}](data:{mime_type};base64,{data})"


def convert(input_path: Path, output_path: Path) -> None:
    md = input_path.read_text(encoding="utf-8")
    base_dir = input_path.parent

    converted = IMAGE_RE.sub(lambda m: embed_image(m, base_dir), md)

    output_path.write_text(converted, encoding="utf-8")

    original_count = len(IMAGE_RE.findall(md))
    embedded_count = converted.count("data:image/")
    print(f"Embedded {embedded_count}/{original_count} images")
    print(f"Output: {output_path}")


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    convert(input_path, output_path)


if __name__ == "__main__":
    main()
