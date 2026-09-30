#!/usr/bin/env python3
"""
Generate alt text for images using caption.py (Anthropic/LLM) and write to the
XMP Alt Text (Accessibility) field in each image. Optionally (--iptc) also
generate and overwrite IPTC Title, Description, and Keywords for Adobe Bridge.
Requires: exiftool (brew install exiftool), llm + llm-anthropic, API key via llm keys set anthropic.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

from image_processor import DEFAULT_MODEL, DELAY_BETWEEN_REQUESTS, EXTENSIONS, process_single_image
from term import (
    BLUE,
    BOLD,
    BRIGHT_CYAN,
    BRIGHT_GREEN,
    BRIGHT_YELLOW,
    CYAN,
    DIM,
    GREEN,
    MAGENTA,
    RED,
    YELLOW,
    paint,
)


def _print_labeled_field(label: str, color: str, value: str, char_count: Optional[int] = None) -> None:
    """Print a metadata field with a colored label and dim character count."""
    count = len(value) if char_count is None else char_count
    print(
        f"  {paint(label, color)} {paint(f'({count} chars)', DIM)}: "
        f"{paint(value, BOLD)}"
    )


def process_directory(
    directory: Path,
    model: str = DEFAULT_MODEL,
    context: Optional[str] = None,
    force: bool = False,
    iptc: bool = False,
    title_only: bool = False,
    creative_title: bool = False,
    creative_description: bool = False,
) -> None:
    """Process all images in directory: generate alt text and write to XMP AltTextAccessibility."""
    if not directory.is_dir():
        print(paint(f"❌ Not a directory: {directory}", BOLD, RED))
        sys.exit(1)

    image_paths = sorted(
        p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS
    )
    total = len(image_paths)
    if total == 0:
        print(paint(f"No images found in {directory}", YELLOW))
        return

    print(
        f"{paint('Found', DIM)} {paint(str(total), BOLD, BRIGHT_CYAN)} "
        f"{paint('images in', DIM)} {paint(str(directory), CYAN)}"
    )
    print(f"{paint('Model:', DIM)} {paint(model, BRIGHT_CYAN)}")
    if context:
        print(f"{paint('Context:', DIM)} {paint(context, BRIGHT_YELLOW)}")
    if title_only:
        print(
            paint(
                "Title only: will overwrite Title/ObjectName; leave alt, description, keywords alone",
                YELLOW,
            )
        )
    elif iptc:
        print(paint("IPTC: will overwrite Title, Description, and Keywords", YELLOW))
    if (title_only or iptc) and creative_title:
        print(
            f"{paint('Title style:', DIM)} "
            f"{paint('creative (evocative) instead of descriptive marketplace-style', MAGENTA)}"
        )
    if iptc and creative_description:
        print(
            f"{paint('Description style:', DIM)} "
            f"{paint('creative short story (max 375 characters)', BLUE)}"
        )
    print()

    for idx, image_path in enumerate(image_paths, 1):
        time.sleep(DELAY_BETWEEN_REQUESTS)
        print(
            f"{paint('[', DIM)}{paint(str(idx), BOLD, BRIGHT_CYAN)}"
            f"{paint('/', DIM)}{paint(str(total), DIM)}{paint(']', DIM)} "
            f"{paint(image_path.name, BOLD)}"
        )

        result = process_single_image(
            image_path,
            model,
            context,
            force,
            iptc,
            title_only,
            creative_title,
            creative_description,
        )

        if result["status"] == "skipped":
            print(paint(f"  💠 Skipped ({result['message']})", YELLOW))
            continue

        if result["status"] == "error":
            print(paint(f"  ❌ {result['message']}", BOLD, RED))
            continue

        if title_only:
            _print_labeled_field("📌 Title", MAGENTA, result["title"])
            print(paint("  ✓ Written IPTC Title only", BRIGHT_GREEN))
            continue

        print(f"  {paint('🟢 📸 🟢', GREEN)}  {paint(result['alt'], BRIGHT_CYAN)}")
        print(paint("  ✓ Written to XMP AltTextAccessibility", BRIGHT_GREEN))

        if iptc:
            if not result["title"]:
                print(paint(f"  ❌ {result['message']}", BOLD, RED))
                continue
            preview_desc = (
                result["description"][:120] + "..."
                if len(result["description"]) > 120
                else result["description"]
            )
            preview_kw = (
                result["keywords"][:120] + "..."
                if len(result["keywords"]) > 120
                else result["keywords"]
            )
            _print_labeled_field("📌 Title", MAGENTA, result["title"])
            _print_labeled_field("📝 Description", BLUE, preview_desc, len(result["description"]))
            _print_labeled_field("🏷️  Keywords", BRIGHT_YELLOW, preview_kw, len(result["keywords"]))
            print(paint("  ✓ Written IPTC Title, Description, and Keywords", BRIGHT_GREEN))

    print(f"\n{paint('Done.', BOLD, BRIGHT_GREEN)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate alt text with LLM (e.g. Anthropic) and write to XMP Alt Text (Accessibility) in images."
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Folder containing images (e.g. path/to/image/folder)",
    )
    parser.add_argument(
        "context",
        nargs="?",
        default=None,
        help="Brief description of the images (optional; can also use -c/--context)",
    )
    parser.add_argument(
        "-c",
        "--context",
        dest="context",
        help="Context for better captions (e.g. 'Cherry blossoms at Japanese Friendship Garden')",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model for caption.py (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing AltTextAccessibility",
    )
    parser.add_argument(
        "--iptc",
        action="store_true",
        help="Also generate and overwrite IPTC Title, Description, and Keywords (Adobe Bridge IPTC Core)",
    )
    parser.add_argument(
        "--title-only",
        action="store_true",
        help="Only generate and overwrite Title/ObjectName; leave alt, description, and keywords unchanged",
    )
    parser.add_argument(
        "--creative-title",
        action="store_true",
        help="Use evocative, artistic titles instead of descriptive marketplace-style titles (with --iptc or --title-only)",
    )
    parser.add_argument(
        "--creative-description",
        action="store_true",
        help="Write the IPTC Description as a creative short story of at most 375 characters (with --iptc)",
    )
    args = parser.parse_args()
    if args.title_only and args.iptc:
        parser.error("Use either --title-only or --iptc, not both")
    if args.creative_title and not (args.iptc or args.title_only):
        parser.error("--creative-title requires --iptc or --title-only")
    if args.creative_description and not args.iptc:
        parser.error("--creative-description requires --iptc")
    process_directory(
        args.directory,
        args.model,
        args.context,
        args.force,
        args.iptc,
        args.title_only,
        args.creative_title,
        args.creative_description,
    )


if __name__ == "__main__":
    main()
