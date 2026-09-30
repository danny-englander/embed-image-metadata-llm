#!/usr/bin/env python3
"""
Generate image metadata with an LLM (e.g. Anthropic) and write it into each image:
alt text (XMP AltTextAccessibility) and/or IPTC Title, Description, and Keywords for
Adobe Bridge. Pick fields with --alt/--title/--description/--keywords; a field that is
already set is skipped unless its --overwrite-* flag is given.
Requires: exiftool (brew install exiftool), llm + llm-anthropic, API key via llm keys set anthropic.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

from image_processor import (
    DEFAULT_MODEL,
    DELAY_BETWEEN_REQUESTS,
    EXTENSIONS,
    FIELD_LABELS,
    FIELDS,
    process_single_image,
)
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
    fields: tuple = (),
    overwrite: tuple = (),
    creative_title: bool = False,
    creative_description: bool = False,
) -> None:
    """Process all images in directory: generate and write the selected metadata fields."""
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
    selected = ", ".join(
        FIELD_LABELS[f] + (" (overwrite)" if f in overwrite else "") for f in FIELDS if f in fields
    )
    print(f"{paint('Fields:', DIM)} {paint(selected, YELLOW)}")
    if "title" in fields and creative_title:
        print(
            f"{paint('Title style:', DIM)} "
            f"{paint('creative (evocative) instead of descriptive marketplace-style', MAGENTA)}"
        )
    if "description" in fields and creative_description:
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
            fields,
            overwrite,
            creative_title,
            creative_description,
        )

        if result["alt"]:
            print(f"  {paint('🟢 📸 🟢', GREEN)}  {paint(result['alt'], BRIGHT_CYAN)}")
        if result["title"]:
            _print_labeled_field("📌 Title", MAGENTA, result["title"])
        if result["description"]:
            description = result["description"]
            preview = description[:120] + "..." if len(description) > 120 else description
            _print_labeled_field("📝 Description", BLUE, preview, len(description))
        if result["keywords"]:
            keywords = result["keywords"]
            preview = keywords[:120] + "..." if len(keywords) > 120 else keywords
            _print_labeled_field("🏷️  Keywords", BRIGHT_YELLOW, preview, len(keywords))
        if result["written"]:
            written = ", ".join(FIELD_LABELS[f] for f in result["written"])
            print(paint(f"  ✓ Written: {written}", BRIGHT_GREEN))
        if result["skipped"]:
            skipped = ", ".join(FIELD_LABELS[f] for f in result["skipped"])
            print(paint(f"  💠 Skipped (already set, overwrite off): {skipped}", YELLOW))
        for field, reason in result["failed"].items():
            print(paint(f"  ❌ Failed: {FIELD_LABELS[field]} ({reason})", BOLD, RED))

    print(f"\n{paint('Done.', BOLD, BRIGHT_GREEN)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate image metadata (alt text, IPTC title, description, keywords) with an LLM and write it into the image files.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Folder containing images (e.g. path/to/image/folder)",
    )
    # Separate dest: a positional with the same dest as --context would overwrite the option's value
    # with its own default (None) whenever it is omitted.
    parser.add_argument(
        "context_positional",
        metavar="context",
        nargs="?",
        default=None,
        help="Brief description of the images (optional; can also use -c/--context)",
    )
    parser.add_argument(
        "-c",
        "--context",
        dest="context",
        help="Context for better results (e.g. 'Cherry blossoms at Japanese Friendship Garden')",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model to use (default: {DEFAULT_MODEL})",
    )

    fields = parser.add_argument_group(
        "fields (select at least one)",
        "A field that already has a value is skipped unless its --overwrite-* flag is given.",
    )
    fields.add_argument("--alt", action="store_true", help="Generate alt text (XMP AltTextAccessibility)")
    fields.add_argument("--title", action="store_true", help="Generate IPTC Title (and ObjectName)")
    fields.add_argument(
        "--description", action="store_true", help="Generate IPTC Description (and Caption-Abstract)"
    )
    fields.add_argument("--keywords", action="store_true", help="Generate IPTC Keywords (and Subject)")

    overwrite = parser.add_argument_group("overwrite (each requires its field flag)")
    overwrite.add_argument("--overwrite-alt", action="store_true", help="Replace existing alt text")
    overwrite.add_argument("--overwrite-title", action="store_true", help="Replace existing title")
    overwrite.add_argument(
        "--overwrite-description", action="store_true", help="Replace existing description"
    )
    overwrite.add_argument("--overwrite-keywords", action="store_true", help="Replace existing keywords")

    style = parser.add_argument_group("style")
    style.add_argument(
        "--creative-title",
        action="store_true",
        help="Use evocative, artistic titles instead of descriptive marketplace-style titles (requires --title)",
    )
    style.add_argument(
        "--creative-description",
        action="store_true",
        help="Write the Description as a creative short story of at most 375 characters (requires --description)",
    )
    return parser


def parse_args(argv=None) -> argparse.Namespace:
    """Parse and validate CLI args. Adds args.fields and args.overwrite (tuples, in FIELDS order)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    args.context = args.context or args.context_positional
    args.fields = tuple(f for f in FIELDS if getattr(args, f))
    args.overwrite = tuple(f for f in FIELDS if getattr(args, f"overwrite_{f}"))
    if not args.fields:
        parser.error("select at least one field: --alt, --title, --description, --keywords")
    for field in args.overwrite:
        if field not in args.fields:
            parser.error(f"--overwrite-{field} requires --{field}")
    if args.creative_title and "title" not in args.fields:
        parser.error("--creative-title requires --title")
    if args.creative_description and "description" not in args.fields:
        parser.error("--creative-description requires --description")
    return args


def main() -> None:
    args = parse_args()
    process_directory(
        args.directory,
        args.model,
        args.context,
        args.fields,
        args.overwrite,
        args.creative_title,
        args.creative_description,
    )


if __name__ == "__main__":
    main()
