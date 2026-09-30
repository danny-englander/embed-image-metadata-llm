"""Core image-processing logic shared by the CLI (update-images.py) and the web app (webapp.py).

No printing, no argparse — callers decide how to present progress and results.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import gettempdir
from typing import Optional

import yaml
from PIL import Image

from imaging import llm_executable, resize_for_llm
from replacements import apply_replacements, replacement_prompt_notes
from term import BOLD, DIM, RED, paint


def _print_error(message: str) -> None:
    print(paint(message, BOLD, RED))


def _print_detail(message: str) -> None:
    print(paint(message, DIM))


# IPTC limit for AltTextAccessibility
ALT_TEXT_MAX_LEN = 250
KEYWORDS_TARGET_LEN = 500
# IPTC ObjectName max is 64; stay under that so titles don't truncate mid-word.
TITLE_MAX_LEN = 59
# Creative short-story descriptions stay well under typical IPTC Caption-Abstract limits.
DESCRIPTION_STORY_MAX_LEN = 375
# Caption descriptions are a single sentence.
DESCRIPTION_CAPTION_MAX_LEN = 200

TITLE_STYLES = ("standard", "creative", "editorial", "poetic", "literal")
DESCRIPTION_STYLES = ("standard", "creative", "caption", "photographic")

DEFAULT_MODEL = "claude-sonnet-5-5"
DELAY_BETWEEN_REQUESTS = 2  # seconds
SCRIPT_DIR = Path(__file__).resolve().parent
CAPTION_SCRIPT = SCRIPT_DIR / "caption.py"
MODELS_CONFIG = SCRIPT_DIR / "models.yaml"

EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".heic", ".heif", ".webp")

TITLE_INSTRUCTION_DEFAULT = (
    "a concise marketplace-style title for the artwork. Use as much of {title_len} characters "
    "as possible without exceeding {title_len}. Prefer subject, place/year if visible in the image, "
    "and style. Title Case. No Midjourney prompts, job IDs, or file names."
)

TITLE_INSTRUCTION_CREATIVE = (
    "an evocative, artistic title for the artwork. Use as much of {title_len} characters as possible "
    "without exceeding {title_len}. Favor mood, metaphor, and distinctive phrasing over a literal "
    "catalog of subject and setting (not \"Astronaut in Red Spacesuit Under Radiant Desert Sky\"; "
    "prefer something like \"Wanderer Beneath a Burning Sky\"). Stay recognizably about this image. "
    "Title Case. No quotation marks, Midjourney prompts, job IDs, or file names."
)

DESCRIPTION_INSTRUCTION_DEFAULT = (
    "3-4 complete sentences describing the image (building on the alt text when one is given). Describe subject, setting, style, and notable "
    "details in clear prose. Do not include Midjourney prompts, job IDs, or technical generation parameters."
)

DESCRIPTION_INSTRUCTION_CREATIVE = (
    "a brief, highly creative short-story vignette inspired by the image. Use as much of {desc_len} "
    "characters as possible without exceeding {desc_len}. Invent a small narrative moment (mood, "
    "incident, or atmosphere) rather than a literal catalog of what is visible, while remaining "
    "recognizably about this image. Vary how the story opens: often start with setting, light, "
    "material, an object, or an action. Gendered pronouns (She, He, Her) are fine when they "
    "clearly fit this particular image, but do not default to them and do not open every story "
    "that way. If gender is unclear, prefer the figure, they, or a concrete noun. Complete "
    "sentences. Do not wrap the whole story in quotation marks. No Midjourney prompts, job IDs, "
    "or technical generation parameters."
)

TITLE_INSTRUCTION_EDITORIAL = (
    "a concise editorial, photo-caption-style title in the form \"Subject, Place\" (for example "
    "\"Koi Pond, Japanese Friendship Garden\"). Use a short noun phrase for the subject, with no verbs "
    "or adjectives that are not plainly observable. Whenever the image or the additional context names "
    "a place, the title must end with that place; shorten the subject to make room rather than dropping "
    "the place. Omit the place only when neither the image nor the context identifies one, and never "
    "guess a place. Use no more than {title_len} characters. Title Case. No quotation marks, "
    "Midjourney prompts, job IDs, or file names."
)

TITLE_INSTRUCTION_POETIC = (
    "a lyrical, poetic title with rhythm and concrete sensory imagery, like a line of verse or a haiku "
    "fragment (for example \"Amber Light Folding into Still Water\"). Use no more than {title_len} characters. "
    "Favor cadence and image over literal description, but stay recognizably about this image. "
    "Title Case. No quotation marks, Midjourney prompts, job IDs, or file names."
)

TITLE_INSTRUCTION_LITERAL = (
    "a plain, literal title that names only the main subject in as few words as possible (typically 2-5 "
    "words, for example \"Red Door\" or \"Three Koi in a Pond\"). Do not pad it: no mood, metaphor, or "
    "decoration, and mention the setting only when it is essential. Never exceed {title_len} characters. "
    "Title Case. No quotation marks, Midjourney prompts, job IDs, or file names."
)

DESCRIPTION_INSTRUCTION_CAPTION = (
    "a single factual, journalistic photo-caption sentence of at most {desc_len} characters that says "
    "what or who is shown, what is happening, and where when that is identifiable. Present tense, plain "
    "language, no interpretation or mood, and no adjectives that are not plainly observable. "
    "No Midjourney prompts, job IDs, or technical generation parameters."
)

DESCRIPTION_INSTRUCTION_PHOTOGRAPHIC = (
    "2-4 sentences in the voice of a photographer's artist statement, describing the photographic "
    "qualities of the image: the light and its direction, color palette, composition and framing, depth "
    "of field, texture, and the mood they create. Describe only what can be seen; do not invent camera "
    "settings, lenses, or gear. No Midjourney prompts, job IDs, or technical generation parameters."
)

TITLE_INSTRUCTIONS = {
    "standard": TITLE_INSTRUCTION_DEFAULT,
    "creative": TITLE_INSTRUCTION_CREATIVE,
    "editorial": TITLE_INSTRUCTION_EDITORIAL,
    "poetic": TITLE_INSTRUCTION_POETIC,
    "literal": TITLE_INSTRUCTION_LITERAL,
}

DESCRIPTION_INSTRUCTIONS = {
    "standard": DESCRIPTION_INSTRUCTION_DEFAULT,
    "creative": DESCRIPTION_INSTRUCTION_CREATIVE,
    "caption": DESCRIPTION_INSTRUCTION_CAPTION,
    "photographic": DESCRIPTION_INSTRUCTION_PHOTOGRAPHIC,
}

# Hard cap applied to the written description for styles that define one (others are uncapped).
DESCRIPTION_MAX_LENS = {
    "creative": DESCRIPTION_STORY_MAX_LEN,
    "caption": DESCRIPTION_CAPTION_MAX_LEN,
}

FIELDS = ("alt", "title", "description", "keywords")
IPTC_FIELDS = ("title", "description", "keywords")
# exiftool tag checked to decide whether a field already has a value.
# A field counts as set if any of its tags has a value (HEIC has no IPTC, so keywords live in XMP Subject).
EXISTING_TAGS = {
    "alt": ("AltTextAccessibility",),
    "title": ("Title",),
    "description": ("Description",),
    "keywords": ("Keywords", "Subject"),
}
FIELD_LABELS = {
    "alt": "alt text",
    "title": "title",
    "description": "description",
    "keywords": "keywords",
}

KEYWORDS_INSTRUCTION = (
    "a single comma-separated string of relevant search keywords/tags. Aim for approximately "
    "{keywords_len} characters total. Prefer concrete nouns, styles, subjects, and themes. No duplicates."
)

IPTC_META_PROMPT = """You are helping tag a photograph for Adobe Bridge IPTC Core metadata.
Look at the image{hint_clause}.

Produce ONLY a JSON object (no markdown fences, no other text) with exactly {key_phrase}:
{field_lines}

{spelling_notes}{context_block}"""


def _check_style(style: str, allowed: tuple, kind: str) -> str:
    if style not in allowed:
        raise ValueError(f"Unknown {kind} style {style!r}; choose from: {', '.join(allowed)}")
    return style


def title_instruction(style: str = "standard") -> str:
    """Title-generation instruction for the given style (see TITLE_STYLES)."""
    _check_style(style, TITLE_STYLES, "title")
    return TITLE_INSTRUCTIONS[style].format(title_len=TITLE_MAX_LEN)


def description_instruction(style: str = "standard") -> str:
    """Description-generation instruction for the given style (see DESCRIPTION_STYLES)."""
    _check_style(style, DESCRIPTION_STYLES, "description")
    template = DESCRIPTION_INSTRUCTIONS[style]
    return template.format(desc_len=DESCRIPTION_MAX_LENS.get(style))


def description_max_len(style: str = "standard") -> Optional[int]:
    """Maximum length enforced on a written description of this style, or None for no cap."""
    _check_style(style, DESCRIPTION_STYLES, "description")
    return DESCRIPTION_MAX_LENS.get(style)


def build_metadata_prompt(
    fields,
    hints=(),
    context: Optional[str] = None,
    title_style: str = "standard",
    description_style: str = "standard",
) -> str:
    """Prompt asking for exactly the requested IPTC fields (title, description, keywords)."""
    instructions = {
        "title": title_instruction(title_style),
        "description": description_instruction(description_style),
        "keywords": KEYWORDS_INSTRUCTION.format(keywords_len=KEYWORDS_TARGET_LEN),
    }
    wanted = [f for f in IPTC_FIELDS if f in fields]
    return IPTC_META_PROMPT.format(
        hint_clause=f" ({'; '.join(hints)})" if hints else "",
        key_phrase="this key" if len(wanted) == 1 else "these keys",
        field_lines="\n".join(f'- "{f}": {instructions[f]}' for f in wanted),
        spelling_notes=replacement_prompt_notes(),
        context_block=f"Additional context: {context}\n" if context else "",
    )


def get_existing_alt_text(image_path: Path) -> Optional[str]:
    """Read current AltTextAccessibility from image via exiftool. Returns None if not set or exiftool missing."""
    return read_exif_field(image_path, "AltTextAccessibility")


def read_exif_field(image_path: Path, tag: str) -> Optional[str]:
    """Read a single tag from image via exiftool. Returns None if not set or exiftool missing."""
    exiftool = shutil.which("exiftool")
    if not exiftool:
        return None
    try:
        result = subprocess.run(
            [exiftool, f"-{tag}", "-s3", "-n", str(image_path)],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0 or not result.stdout:
            return None
        value = result.stdout.strip()
        return value if value else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def write_alt_text(image_path: Path, alt_text: str) -> bool:
    """Write AltTextAccessibility to image via exiftool. Truncates to 250 chars. Returns True on success."""
    exiftool = shutil.which("exiftool")
    if not exiftool:
        _print_error("❌ exiftool not found. Install with: brew install exiftool")
        return False
    # IPTC limit; replace newlines with space
    text = apply_replacements(alt_text.replace("\n", " ").strip())
    text = text[:ALT_TEXT_MAX_LEN].strip()
    if not text:
        return False
    try:
        # -overwrite_original to avoid leaving _original backups in the gallery
        result = subprocess.run(
            [
                exiftool,
                "-overwrite_original",
                f"-AltTextAccessibility={text}",
                str(image_path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            _print_error(f"  ❌ exiftool error: {result.stderr or result.stdout}")
            return False
        return True
    except subprocess.TimeoutExpired:
        _print_error("  ❌ exiftool timed out")
        return False


def truncate_keywords(keywords: str, max_len: int = KEYWORDS_TARGET_LEN) -> str:
    """Apply replacements, then trim to max_len at the last complete keyword."""
    text = apply_replacements(re.sub(r"\s+", " ", keywords.replace("\n", " ")).strip().strip(","))
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    if "," in cut:
        cut = cut.rsplit(",", 1)[0]
    return cut.strip().rstrip(",")


def truncate_title(title: str, max_len: int = TITLE_MAX_LEN) -> str:
    """Apply replacements, then trim to max_len at the last complete word."""
    text = apply_replacements(re.sub(r"\s+", " ", title.replace("\n", " ")).strip())
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.strip()


def truncate_description(description: str, max_len: Optional[int] = None) -> str:
    """Apply replacements, collapse whitespace, and optionally trim at a sentence or word."""
    text = apply_replacements(re.sub(r"\s+", " ", description.replace("\n", " ")).strip())
    if max_len is None or len(text) <= max_len:
        return text
    cut = text[:max_len].rstrip()
    sentence_end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if sentence_end >= max_len // 2:
        return cut[: sentence_end + 1].strip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.strip()


def write_iptc_fields(
    image_path: Path,
    title: Optional[str] = None,
    description: Optional[str] = None,
    keywords: Optional[str] = None,
    description_max_len: Optional[int] = None,
) -> bool:
    """Write only the given IPTC fields via exiftool; fields left as None are untouched.

    Title also sets ObjectName, Description also sets Caption-Abstract, and Keywords also sets
    XMP-dc:Subject.
    """
    exiftool = shutil.which("exiftool")
    if not exiftool:
        _print_error("❌ exiftool not found. Install with: brew install exiftool")
        return False
    sets = []
    if title is not None:
        title = truncate_title(title)
        if not title:
            return False
        sets += [f"-Title={title}", f"-ObjectName={title}"]
    if description is not None:
        description = truncate_description(description, description_max_len)
        if not description:
            return False
        sets += [f"-Description={description}", f"-Caption-Abstract={description}"]
    if keywords is not None:
        keywords = truncate_keywords(keywords)
        if not keywords:
            return False
        sets += [f"-Keywords={keywords}", f"-XMP-dc:Subject={keywords}"]
    if not sets:
        return False
    # Clear Keywords/Subject first so Bridge shows a full replace, not append.
    clear = ["-Keywords=", "-XMP-dc:Subject="] if keywords is not None else []
    try:
        result = subprocess.run(
            [exiftool, "-overwrite_original", *clear, "-sep", ", ", *sets, str(image_path)],
            capture_output=True,
            text=True,
            timeout=20,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            _print_error(f"  ❌ exiftool IPTC error: {result.stderr or result.stdout}")
            return False
        return True
    except subprocess.TimeoutExpired:
        _print_error("  ❌ exiftool timed out writing IPTC")
        return False


def resolve_llm_model_id(model_name: str) -> Optional[str]:
    """Map models.yaml key (e.g. claude-sonnet-5-5) to llm -m id."""
    try:
        with open(MODELS_CONFIG) as f:
            models = yaml.safe_load(f)
        config = models.get(model_name)
        if not config:
            _print_error(f"  ❌ Unknown model in models.yaml: {model_name}")
            return None
        return config.get("model")
    except (OSError, yaml.YAMLError) as e:
        _print_error(f"  ❌ Failed to load models.yaml: {e}")
        return None


def llm_option_args(model_name: str) -> list:
    """Return llm -o arguments from the model's `settings` in models.yaml."""
    try:
        with open(MODELS_CONFIG) as f:
            models = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return []
    settings = (models.get(model_name) or {}).get("settings") or {}
    args = []
    for key, value in settings.items():
        args.extend(["-o", key, str(value)])
    return args


def resize_image_for_llm(image_path: Path, max_dimension: int = 1024) -> Path:
    """Return path to an LLM-acceptable image (temp file if resized or converted from HEIC/HEIF)."""
    return resize_for_llm(image_path, "resized-llm-iptc", max_dimension)


def parse_iptc_json(raw: str) -> Optional[dict]:
    """Parse the JSON object from model output, stripping markdown fences if present.

    If the model emitted several objects (e.g. a draft followed by a corrected "final" one),
    the last one wins. Surrounding prose is ignored.
    """
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence:
        text = fence.group(1).strip()
    decoder = json.JSONDecoder()
    found = None
    start = text.find("{")
    while start != -1:
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(obj, dict):
            found = obj
        start = text.find("{", end)
    return found


def generate_iptc_fields(
    image_path: Path,
    model: str,
    fields,
    alt: Optional[str] = None,
    context: Optional[str] = None,
    title_style: str = "standard",
    description_style: str = "standard",
) -> Optional[dict]:
    """One llm vision call for the requested IPTC fields (title, description, keywords).

    Returns {field: value} for exactly the requested fields, or None on failure.
    """
    wanted = [f for f in IPTC_FIELDS if f in fields]
    llm_model = resolve_llm_model_id(model)
    if not llm_model:
        return None

    hints = []
    if alt:
        hints.append(f"alt text: {alt}")
    if "description" not in wanted:
        existing_description = read_exif_field(image_path, "Description")
        if existing_description:
            hints.append(f"existing description: {existing_description}")

    prompt = build_metadata_prompt(wanted, hints, context, title_style, description_style)
    small_image = resize_image_for_llm(image_path)
    cmd = [llm_executable(), "-m", llm_model, "-a", str(small_image), prompt, *llm_option_args(model)]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=SCRIPT_DIR, stdin=subprocess.DEVNULL
        )
        if result.returncode != 0:
            _print_error(f"  ❌ llm error: exit {result.returncode}.")
            if result.stderr:
                _print_detail(f"  stderr: {result.stderr.strip()}")
            return None
        data = parse_iptc_json(result.stdout)
        if not data:
            _print_error("  ❌ Could not parse JSON from model output.")
            if result.stdout:
                _print_detail(f"  stdout: {result.stdout.strip()[:200]}...")
            return None
        values = {}
        for field in wanted:
            value = data.get(field) or ""
            if isinstance(value, list):
                value = ", ".join(str(v).strip() for v in value if str(v).strip())
            value = str(value).strip()
            if not value:
                _print_error(f"  ❌ Model JSON missing {field}.")
                return None
            values[field] = value
        if "title" in values:
            values["title"] = truncate_title(values["title"])
        if "description" in values:
            values["description"] = truncate_description(
                values["description"], description_max_len(description_style)
            )
        if "keywords" in values:
            values["keywords"] = truncate_keywords(values["keywords"])
        return values
    except subprocess.TimeoutExpired:
        _print_error("  ❌ llm timed out generating metadata.")
        return None


def generate_alt_text(
    image_path: Path, model: str, context: Optional[str]
) -> Optional[str]:
    """Run caption.py for one image and return the caption for the given model, or None on failure."""
    cmd = [sys.executable, str(CAPTION_SCRIPT), str(image_path), "--model", model]
    if context:
        cmd.extend(["--context", context])
    env = dict(os.environ)
    env["IMAGE_CAPTION_CONFIG"] = str(MODELS_CONFIG)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=SCRIPT_DIR, env=env, stdin=subprocess.DEVNULL
        )
        if result.returncode != 0:
            _print_error(
                f"  ❌ caption.py error: Command {result.args!r} returned exit status {result.returncode}."
            )
            if result.stderr:
                _print_detail(f"  stderr: {result.stderr.strip()}")
            if result.stdout and not result.stderr:
                _print_detail(f"  stdout: {result.stdout.strip()}")
            return None
        data = json.loads(result.stdout)
        captions = data.get("captions", {})
        alt = captions.get(model)
        if isinstance(alt, dict):
            alt = alt.get("caption") or alt.get("alt")
        return (alt or "").strip() or None
    except (json.JSONDecodeError, KeyError) as e:
        _print_error(f"  ❌ caption.py error: {e}")
        return None


def _existing_value(image_path: Path, field: str) -> Optional[str]:
    """Current value of a field in the image, or None if it has none."""
    for tag in EXISTING_TAGS[field]:
        value = read_exif_field(image_path, tag)
        if value:
            return value
    return None


def _summary(result: dict) -> str:
    """Human-readable one-line summary built from a result's written/skipped/failed lists."""
    parts = []
    if result["written"]:
        parts.append("Written: " + ", ".join(FIELD_LABELS[f] for f in result["written"]))
    if result["skipped"]:
        parts.append(
            "Skipped (already set, overwrite off): "
            + ", ".join(FIELD_LABELS[f] for f in result["skipped"])
        )
    if result["failed"]:
        parts.append(
            "Failed: "
            + "; ".join(f"{FIELD_LABELS[f]} ({reason})" for f, reason in result["failed"].items())
        )
    return ". ".join(parts)


def process_single_image(
    image_path: Path,
    model: str,
    context: Optional[str] = None,
    fields=(),
    overwrite=(),
    title_style: str = "standard",
    description_style: str = "standard",
) -> dict:
    """Generate and write the selected metadata fields for one image. Pure logic, no printing.

    fields: which of "alt", "title", "description", "keywords" to generate.
    title_style / description_style: writing style for those fields (TITLE_STYLES, DESCRIPTION_STYLES).
    overwrite: which selected fields may replace an existing value. A selected field that
      already has a value and is not in overwrite is skipped; the others still run.

    Returns a dict:
      status: "written" | "skipped" | "error"
      message: human-readable summary
      alt / title / description / keywords: values written (or None)
      written / skipped: lists of fields; failed: {field: reason}
      existing: {field: current value} for skipped fields
    """
    fields, overwrite = set(fields), set(overwrite)
    unknown = (fields | overwrite) - set(FIELDS)
    if unknown:
        raise ValueError(f"Unknown field(s): {', '.join(sorted(unknown))}")
    if not fields:
        raise ValueError("Select at least one field to generate.")
    _check_style(title_style, TITLE_STYLES, "title")
    _check_style(description_style, DESCRIPTION_STYLES, "description")

    result = {
        "status": "error",
        "message": "",
        "alt": None,
        "title": None,
        "description": None,
        "keywords": None,
        "written": [],
        "skipped": [],
        "failed": {},
        "existing": {},
    }

    todo = []
    for field in FIELDS:
        if field not in fields:
            continue
        current = None if field in overwrite else _existing_value(image_path, field)
        if current:
            result["skipped"].append(field)
            result["existing"][field] = current
        else:
            todo.append(field)

    if not todo:
        result["status"] = "skipped"
        result["message"] = _summary(result)
        return result

    alt_hint = None
    if "alt" in todo:
        alt = generate_alt_text(image_path, model, context)
        if not alt:
            result["failed"]["alt"] = "none generated"
        # Never write error messages into the image metadata
        elif alt.strip().lower().startswith("error") or "unknown model" in alt.lower():
            result["failed"]["alt"] = f"caption failed: {alt[:60]}..."
        else:
            if len(alt) > ALT_TEXT_MAX_LEN:
                alt = alt[: ALT_TEXT_MAX_LEN - 3] + "..."
            if write_alt_text(image_path, alt):
                result["alt"] = alt
                result["written"].append("alt")
                alt_hint = alt
            else:
                result["failed"]["alt"] = "write failed"
    else:
        alt_hint = get_existing_alt_text(image_path)

    iptc_todo = [f for f in IPTC_FIELDS if f in todo]
    if iptc_todo:
        values = generate_iptc_fields(
            image_path, model, iptc_todo, alt_hint, context, title_style, description_style
        )
        if not values:
            result["failed"].update({f: "none generated" for f in iptc_todo})
        elif not write_iptc_fields(
            image_path,
            **values,
            description_max_len=description_max_len(description_style),
        ):
            result["failed"].update({f: "write failed" for f in iptc_todo})
        else:
            for field, value in values.items():
                result[field] = value
                result["written"].append(field)

    result["status"] = "error" if result["failed"] else "written"
    result["message"] = _summary(result)
    return result
