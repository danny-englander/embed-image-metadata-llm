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

DEFAULT_MODEL = "claude-sonnet-5-5"
DELAY_BETWEEN_REQUESTS = 2  # seconds
SCRIPT_DIR = Path(__file__).resolve().parent
CAPTION_SCRIPT = SCRIPT_DIR / "caption.py"
MODELS_CONFIG = SCRIPT_DIR / "models.yaml"

EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".heic", ".webp")

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
    "3-4 complete sentences expanding on the alt text. Describe subject, setting, style, and notable "
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

IPTC_META_PROMPT = """You are helping tag a photograph for Adobe Bridge IPTC Core metadata.
Given the image and this short alt text: {alt}

Produce ONLY a JSON object (no markdown fences, no other text) with exactly these keys:
- "title": {title_instruction}
- "description": {description_instruction}
- "keywords": a single comma-separated string of relevant search keywords/tags. Aim for approximately {keywords_len} characters total. Prefer concrete nouns, styles, subjects, and themes. No duplicates.

{spelling_notes}{context_block}"""

TITLE_ONLY_PROMPT = """You are helping tag a photograph for Adobe Bridge IPTC Core metadata.
Look at the image{hint_clause}.

Produce ONLY a JSON object (no markdown fences, no other text) with exactly this key:
- "title": {title_instruction}

{spelling_notes}{context_block}"""


def title_instruction(creative: bool = False) -> str:
    """Title-generation instruction for the default (descriptive) or creative style."""
    template = TITLE_INSTRUCTION_CREATIVE if creative else TITLE_INSTRUCTION_DEFAULT
    return template.format(title_len=TITLE_MAX_LEN)


def description_instruction(creative: bool = False) -> str:
    """Description-generation instruction for the default prose or creative short story."""
    if not creative:
        return DESCRIPTION_INSTRUCTION_DEFAULT
    return DESCRIPTION_INSTRUCTION_CREATIVE.format(desc_len=DESCRIPTION_STORY_MAX_LEN)


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


def write_iptc_metadata(
    image_path: Path,
    title: str,
    description: str,
    keywords: str,
    description_max_len: Optional[int] = None,
) -> bool:
    """Overwrite Title, ObjectName, Description, Caption-Abstract, Keywords, and Subject via exiftool."""
    exiftool = shutil.which("exiftool")
    if not exiftool:
        _print_error("❌ exiftool not found. Install with: brew install exiftool")
        return False
    title = truncate_title(title)
    description = truncate_description(description, description_max_len)
    keywords = truncate_keywords(keywords)
    if not title or not description or not keywords:
        return False
    try:
        # Clear Keywords/Subject first so Bridge shows a full replace, not append.
        result = subprocess.run(
            [
                exiftool,
                "-overwrite_original",
                "-Keywords=",
                "-XMP-dc:Subject=",
                "-sep",
                ", ",
                f"-Title={title}",
                f"-ObjectName={title}",
                f"-Keywords={keywords}",
                f"-XMP-dc:Subject={keywords}",
                f"-Description={description}",
                f"-Caption-Abstract={description}",
                str(image_path),
            ],
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


def write_title_only(image_path: Path, title: str) -> bool:
    """Overwrite only Title and ObjectName via exiftool. Leaves other IPTC fields alone."""
    exiftool = shutil.which("exiftool")
    if not exiftool:
        _print_error("❌ exiftool not found. Install with: brew install exiftool")
        return False
    title = truncate_title(title)
    if not title:
        return False
    try:
        result = subprocess.run(
            [
                exiftool,
                "-overwrite_original",
                f"-Title={title}",
                f"-ObjectName={title}",
                str(image_path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            _print_error(f"  ❌ exiftool title error: {result.stderr or result.stdout}")
            return False
        return True
    except subprocess.TimeoutExpired:
        _print_error("  ❌ exiftool timed out writing title")
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


def resize_image_for_llm(image_path: Path, max_dimension: int = 1024) -> Path:
    """Return path to a resized image for LLM processing (temp file if resized)."""
    with Image.open(image_path) as img:
        if max(img.size) <= max_dimension:
            return image_path
        img.thumbnail((max_dimension, max_dimension))
        temp_path = Path(gettempdir()) / f"resized-llm-iptc{image_path.suffix}"
        img.save(temp_path, optimize=True)
        return temp_path


def parse_iptc_json(raw: str) -> Optional[dict]:
    """Parse JSON object from model output, stripping markdown fences if present."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find first {...} block
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    return data


def generate_iptc_metadata(
    image_path: Path,
    model: str,
    alt: str,
    context: Optional[str],
    creative_title: bool = False,
    creative_description: bool = False,
) -> Optional[tuple[str, str, str]]:
    """Run llm vision call for title + description + keywords.

    Returns (title, description, keywords) or None.
    """
    llm_model = resolve_llm_model_id(model)
    if not llm_model:
        return None

    context_block = ""
    if context:
        context_block = f"Additional context: {context}\n"

    description_max_len = DESCRIPTION_STORY_MAX_LEN if creative_description else None
    prompt = IPTC_META_PROMPT.format(
        alt=alt,
        title_instruction=title_instruction(creative_title),
        description_instruction=description_instruction(creative_description),
        keywords_len=KEYWORDS_TARGET_LEN,
        spelling_notes=replacement_prompt_notes(),
        context_block=context_block,
    )
    small_image = resize_image_for_llm(image_path)
    cmd = ["llm", "-m", llm_model, "-a", str(small_image), prompt]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=SCRIPT_DIR, stdin=subprocess.DEVNULL
        )
        if result.returncode != 0:
            _print_error(f"  ❌ llm IPTC error: exit {result.returncode}.")
            if result.stderr:
                _print_detail(f"  stderr: {result.stderr.strip()}")
            return None
        data = parse_iptc_json(result.stdout)
        if not data:
            _print_error("  ❌ Could not parse IPTC JSON from model output.")
            if result.stdout:
                _print_detail(f"  stdout: {result.stdout.strip()[:200]}...")
            return None
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        keywords = (data.get("keywords") or "").strip()
        if isinstance(keywords, list):
            keywords = ", ".join(str(k).strip() for k in keywords if str(k).strip())
        if not title or not description or not keywords:
            _print_error("  ❌ IPTC JSON missing title, description, or keywords.")
            return None
        return (
            truncate_title(title),
            truncate_description(description, description_max_len),
            truncate_keywords(keywords),
        )
    except subprocess.TimeoutExpired:
        _print_error("  ❌ llm timed out generating IPTC metadata.")
        return None


def generate_title_only(
    image_path: Path,
    model: str,
    context: Optional[str],
    creative_title: bool = False,
) -> Optional[str]:
    """Run llm vision call for title only. Uses existing Description/alt as hints when present."""
    llm_model = resolve_llm_model_id(model)
    if not llm_model:
        return None

    description = read_exif_field(image_path, "Description")
    alt = get_existing_alt_text(image_path)
    hints = []
    if description:
        hints.append(f"existing description: {description}")
    if alt:
        hints.append(f"existing alt text: {alt}")
    hint_clause = f" ({'; '.join(hints)})" if hints else ""

    context_block = ""
    if context:
        context_block = f"Additional context: {context}\n"

    prompt = TITLE_ONLY_PROMPT.format(
        hint_clause=hint_clause,
        title_instruction=title_instruction(creative_title),
        spelling_notes=replacement_prompt_notes(),
        context_block=context_block,
    )
    small_image = resize_image_for_llm(image_path)
    cmd = ["llm", "-m", llm_model, "-a", str(small_image), prompt]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=SCRIPT_DIR, stdin=subprocess.DEVNULL
        )
        if result.returncode != 0:
            _print_error(f"  ❌ llm title error: exit {result.returncode}.")
            if result.stderr:
                _print_detail(f"  stderr: {result.stderr.strip()}")
            return None
        data = parse_iptc_json(result.stdout)
        if not data:
            _print_error("  ❌ Could not parse title JSON from model output.")
            if result.stdout:
                _print_detail(f"  stdout: {result.stdout.strip()[:200]}...")
            return None
        title = (data.get("title") or "").strip()
        if not title:
            _print_error("  ❌ Title JSON missing title.")
            return None
        return truncate_title(title)
    except subprocess.TimeoutExpired:
        _print_error("  ❌ llm timed out generating title.")
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


def process_single_image(
    image_path: Path,
    model: str,
    context: Optional[str] = None,
    force: bool = False,
    iptc: bool = False,
    title_only: bool = False,
    creative_title: bool = False,
    creative_description: bool = False,
) -> dict:
    """Generate and write metadata for one image. Pure logic, no printing.

    Returns a dict:
      status: "written" | "skipped" | "error"
      message: human-readable detail
      alt / title / description / keywords: values written (or None)
    """
    result = {
        "status": "error",
        "message": "",
        "alt": None,
        "title": None,
        "description": None,
        "keywords": None,
    }

    if title_only:
        title = generate_title_only(image_path, model, context, creative_title)
        if not title:
            result["message"] = "Failed to generate title."
            return result
        if not write_title_only(image_path, title):
            result["message"] = "Failed to write title."
            return result
        result["status"] = "written"
        result["title"] = title
        result["message"] = f"Written IPTC Title only ({len(title)} chars)"
        return result

    if not force:
        existing = get_existing_alt_text(image_path)
        if existing:
            result["status"] = "skipped"
            result["message"] = "Already has alt text (use force to overwrite)."
            return result

    alt = generate_alt_text(image_path, model, context)
    if not alt:
        result["message"] = "No alt text generated."
        return result
    # Never write error messages into the image metadata
    if alt.strip().lower().startswith("error") or "unknown model" in alt.lower():
        result["message"] = f"Caption failed (not written): {alt[:60]}..."
        return result
    if len(alt) > ALT_TEXT_MAX_LEN:
        alt = alt[: ALT_TEXT_MAX_LEN - 3] + "..."

    if not write_alt_text(image_path, alt):
        result["message"] = "Failed to write metadata."
        return result

    result["status"] = "written"
    result["alt"] = alt
    result["message"] = "Written to XMP AltTextAccessibility"

    if iptc:
        meta = generate_iptc_metadata(
            image_path, model, alt, context, creative_title, creative_description
        )
        if not meta:
            result["message"] += "; failed to generate IPTC title/description/keywords."
            return result
        title, description, keywords = meta
        description_max_len = DESCRIPTION_STORY_MAX_LEN if creative_description else None
        if not write_iptc_metadata(
            image_path, title, description, keywords, description_max_len
        ):
            result["message"] += "; failed to write IPTC metadata."
            return result
        result["title"] = title
        result["description"] = description
        result["keywords"] = keywords
        result["message"] += "; written IPTC Title, Description, and Keywords"

    return result
