"""Image helpers shared by caption.py and image_processor.py.

Registers HEIF/HEIC decoding with Pillow when pillow-heif is installed, and prepares images for
the LLM APIs (which accept JPEG, PNG, GIF and WebP but not HEIC/HEIF).
"""

import sys
from pathlib import Path
from tempfile import gettempdir

from PIL import Image

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:
    HEIF_SUPPORTED = False

# Formats the LLM APIs do not accept; always converted to JPEG before sending.
CONVERT_SUFFIXES = (".heic", ".heif")


def resize_for_llm(image_path, temp_stem: str, max_dimension: int = 1024) -> Path:
    """Return a path to an image the LLM can accept, at most max_dimension on its long side.

    Small JPEG/PNG/GIF/WebP images are returned unchanged. Larger ones are downscaled into a temp
    file named ``temp_stem`` + the original extension. HEIC/HEIF images are always converted to a
    temp JPEG, whatever their size.
    """
    path = Path(image_path)
    convert = path.suffix.lower() in CONVERT_SUFFIXES
    if convert and not HEIF_SUPPORTED:
        raise RuntimeError(
            f"{path.name} is HEIC/HEIF, which needs the pillow-heif package (pip install pillow-heif)"
        )
    with Image.open(path) as img:
        if not convert and max(img.size) <= max_dimension:
            return path
        img.thumbnail((max_dimension, max_dimension))
        if convert:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            temp_path = Path(gettempdir()) / f"{temp_stem}.jpg"
            img.save(temp_path, quality=90, optimize=True)
        else:
            temp_path = Path(gettempdir()) / f"{temp_stem}{path.suffix}"
            img.save(temp_path, optimize=True)
        return temp_path


def llm_executable() -> str:
    """The `llm` command to run.

    Prefers the one installed next to the running Python, so it is found even when the virtualenv
    has not been activated; otherwise falls back to whatever is on PATH.
    """
    sibling = Path(sys.executable).parent / "llm"
    return str(sibling) if sibling.exists() else "llm"
