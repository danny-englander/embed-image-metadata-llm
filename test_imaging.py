import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import imaging
from imaging import llm_executable, resize_for_llm

try:
    import pillow_heif
except ImportError:  # pragma: no cover
    pillow_heif = None


def make_image(directory: Path, name: str, size=(200, 100), mode="RGB") -> Path:
    path = directory / name
    Image.new(mode, size, (200, 40, 40)[: len(mode)] if mode != "L" else 128).save(path)
    return path


class TestResizeForLlm(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)

    def test_small_image_is_returned_unchanged(self):
        path = make_image(self.dir, "small.jpg", (200, 100))
        self.assertEqual(resize_for_llm(path, "test-resize"), path)

    def test_large_image_is_downscaled_into_a_temp_file(self):
        path = make_image(self.dir, "big.png", (3000, 1500))
        out = resize_for_llm(path, "test-resize-big", max_dimension=1024)
        self.assertNotEqual(out, path)
        self.assertEqual(out.suffix, ".png")
        with Image.open(out) as img:
            self.assertEqual(max(img.size), 1024)

    @unittest.skipIf(pillow_heif is None, "pillow-heif not installed")
    def test_small_heic_is_still_converted_to_jpeg(self):
        path = self.dir / "small.heic"
        Image.new("RGB", (200, 100), (10, 120, 200)).save(path, format="HEIF")
        out = resize_for_llm(path, "test-resize-heic")
        self.assertEqual(out.suffix, ".jpg")
        with Image.open(out) as img:
            self.assertEqual(img.format, "JPEG")
            self.assertEqual(img.size, (200, 100))

    @unittest.skipIf(pillow_heif is None, "pillow-heif not installed")
    def test_large_heif_is_downscaled_and_converted(self):
        path = self.dir / "big.heif"
        Image.new("RGB", (2400, 1200), (10, 120, 200)).save(path, format="HEIF")
        out = resize_for_llm(path, "test-resize-heif", max_dimension=1024)
        self.assertEqual(out.suffix, ".jpg")
        with Image.open(out) as img:
            self.assertEqual(max(img.size), 1024)

    def test_heic_without_pillow_heif_gives_a_clear_error(self):
        path = self.dir / "photo.heic"
        path.write_bytes(b"not a real heic")
        with patch.object(imaging, "HEIF_SUPPORTED", False):
            with self.assertRaises(RuntimeError) as ctx:
                resize_for_llm(path, "test-resize-missing")
        self.assertIn("pillow-heif", str(ctx.exception))


class TestLlmExecutable(unittest.TestCase):
    def test_prefers_the_llm_next_to_the_running_python(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "llm").write_text("#!/bin/sh\n")
            with patch.object(sys, "executable", str(Path(d) / "python")):
                self.assertEqual(llm_executable(), str(Path(d) / "llm"))

    def test_falls_back_to_path_lookup(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(sys, "executable", str(Path(d) / "python")):
                self.assertEqual(llm_executable(), "llm")


if __name__ == "__main__":
    unittest.main()
