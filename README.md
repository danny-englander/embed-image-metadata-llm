## Overview

This project generates image alt text using a LLM and writes it into image files as XMP Alt Text for accessibility as the image's `XMP-iptcCore:AltTextAccessibility` key.

These instructions assume macOS or Linux. Windows should work with equivalent tools, but commands may differ.

Inspired by [Dries Buytaert's "Image Caption"](https://github.com/dbuytaert/image-caption), the key difference being how the generated alt text is stored. Dries' script sends a PATCH request to a remote API, where the alt text is stored server-side and matched to the image by album name and filename. This script instead writes the alt text directly into the image file itself, using `exiftool` to set the `AltTextAccessibility` XMP metadata field, so the alt text is embedded in the image itself.

---

## 1. Prerequisites

- **Python**: 3.10+ (3.11/3.12 recommended)
- **Git**
- **System tools**:
  - `exiftool` (for writing XMP Alt Text into images)
- **LLM CLI tooling**:
  - [`llm`](https://llm.datasette.io/) (CLI wrapper)
  - The `llm-anthropic` plugin (installed via `requirements.txt`) and an Anthropic API key

### Install system dependencies (macOS)

```bash
# exiftool
brew install exiftool
```

If you don’t have Homebrew installed, you can install it by following the instructions at the [Homebrew website](https://brew.sh/).

The `llm` CLI is installed later via `pip install -r requirements.txt`, so you don’t need to install it separately.

### Configure Anthropic

This project uses Anthropic models (`claude-sonnet-5-5` and `claude-sonnet-4-6`).

1. **Install the plugin**:

   ```bash
   llm install llm-anthropic
   ```

2. **Set your API key**:

   ```bash
   llm keys set anthropic
   # Paste your Anthropic API key when prompted
   ```

The default model used by `update-images.py` is `claude-sonnet-5-5`, which is preconfigured in `models.yaml`.

---

## 2. Clone the repository

```bash
git clone https://github.com/danny-englander/embed-image-metadata-llm.git
cd embed-image-metadata-llm
```

---

## 3. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

---

## 4. Install Python dependencies

From the project root:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt` includes:

- `llm`
- `pillow`
- `pyyaml`
- `requests`
- `python-dotenv`

---

## 5. Models configuration (`models.yaml`)

The file `models.yaml` (already in the repo) defines the available models and prompts for image captioning.

- It defines two models: `claude-sonnet-5-5` (default) and `claude-sonnet-4-6`.
- `update-images.py` will automatically set the `IMAGE_CAPTION_CONFIG` environment variable to point to this file, so you normally do **not** need to configure it manually.

If you create your own config file elsewhere, you can override the default by setting:

```bash
export IMAGE_CAPTION_CONFIG=/absolute/path/to/your-models.yaml
```

### Word replacements (`replacements.yaml`)

`replacements.yaml` is a dictionary of phrases that are always rewritten in generated alt text, titles, descriptions, and keywords. Matching is case-insensitive; capitalization of the source is preserved (`mid-century` → `midcentury`, `Mid-Century` → `Midcentury`).

```yaml
mid-century: midcentury
```

Add more `find: replace` lines as needed. The model is also told to use these spellings in the prompt.

These rules are always applied in every generated field (alt text, title, description, and keywords), whether or not they appear in `replacements.yaml`. The model is also told to follow them:

- Em dashes (`—`) become a hyphen (`-`)
- `mid-century` / `mid century` become `midcentury` (`Mid-Century` → `Midcentury`)

---

## 6. Basic usage (local XMP alt text workflow)

The primary script in this repo is `update-images.py`, which:

- Scans a folder of images.
- Uses an LLM (via `llm`) to generate the fields you select: **alt text**, **IPTC Title**, **IPTC Description**, and **IPTC Keywords**. Each field is chosen independently.
- Writes them into the image with `exiftool`: alt text to **XMP Alt Text (Accessibility)**, and the IPTC fields to Adobe Bridge **IPTC Core** (`Title` / `ObjectName`, `Description` / `Caption-Abstract`, `Keywords` / `Subject`).
- Skips any selected field that already has a value, unless you pass that field's `--overwrite-*` flag. Title and description each have a default marketplace style and an optional creative style (`--creative-title`, `--creative-description`).

### Supported image formats

- `.jpg`, `.jpeg`, `.png`, `.gif`, `.heic`, `.webp`

### Run the script

From the project root:

```bash
# Activate your virtualenv if not already active
source .venv/bin/activate

# Generate alt text (uses default model from models.yaml: claude-sonnet-5-5)
python update-images.py /path/to/image/folder --alt
```

You must select at least one field (see [Choosing fields](#choosing-fields)).

You can provide optional context to improve captions:

```bash
python update-images.py /path/to/image/folder --alt \
  --context "Cherry blossoms at Japanese Friendship Garden"
```

Or using the positional context argument:

```bash
python update-images.py /path/to/image/folder --alt \
  "Cherry blossoms at Japanese Friendship Garden"
```

To choose a specific model defined in `models.yaml`:

```bash
python update-images.py /path/to/image/folder --alt \
  --model claude-sonnet-5-5
```

### Choosing fields

Select any combination of fields. Each has its own flag, and each has a companion overwrite flag:

| Field | Flag | Overwrite flag | Written to |
|---|---|---|---|
| Alt text | `--alt` | `--overwrite-alt` | XMP `AltTextAccessibility` (max 250 characters) |
| Title | `--title` | `--overwrite-title` | `Title` and `ObjectName` (max 59 characters, under the IPTC 64-char limit) |
| Description | `--description` | `--overwrite-description` | `Description` and `Caption-Abstract` (3–4 sentences, or a short story with `--creative-description`) |
| Keywords | `--keywords` | `--overwrite-keywords` | `Keywords` and XMP `Subject` (~500 characters, replaced rather than appended) |

You must select at least one field. Fields you don't select are never touched.

A selected field that **already has a value is skipped** unless its overwrite flag is given; the other selected fields still run. An overwrite flag only applies to its own field and requires that field's flag (for example `--overwrite-title` requires `--title`).

```bash
# Alt text only
python update-images.py /path/to/image/folder --alt

# Everything, filling only what is missing
python update-images.py /path/to/image/folder --alt --title --description --keywords

# Regenerate just the keywords, leaving everything else alone
python update-images.py /path/to/image/folder --keywords --overwrite-keywords

# Replace alt text and title, but only fill in description and keywords where empty
python update-images.py /path/to/image/folder --alt --title --description --keywords \
  --overwrite-alt --overwrite-title
```

Title, description, and keywords are generated together in one model call (only for the ones that need it), so selecting more of them does not cost extra calls. They use the alt text as context: the one just generated, or the existing one if you didn't select `--alt`.

### Creative titles (`--creative-title`)

The default title is a literal marketplace-style line, for example:

> Astronaut in Red Spacesuit Under Radiant Desert Sky

Pass `--creative-title` for a more evocative, artistic title instead, for example:

> Wanderer Beneath a Burning Sky

`--creative-title` requires `--title`.

```bash
python update-images.py /path/to/image/folder --title --creative-title
```

### Creative descriptions (`--creative-description`)

The default description is 3–4 literal sentences describing the image (building on the alt text when there is one).

Pass `--creative-description` to write the Description as a short-story vignette (mood, incident, or inner life) instead of a catalog of what is visible. Stories are capped at **375 characters**; if the model runs long, the text is trimmed at a sentence boundary when possible.

`--creative-description` requires `--description`. It can be combined with `--creative-title`:

```bash
python update-images.py /path/to/image/folder --description --creative-description
python update-images.py /path/to/image/folder --title --description --creative-title --creative-description
```

---

## 7. Verifying the installation

### 7.1. Dry run on a small folder

1. Create a test folder with a few images, or use `test-images` if included in the repo.
2. Run:

   ```bash
   python update-images.py test-images --alt
   ```

3. Check output:
   - You should see logs like `🟢 <caption…>` and `✓ Written: alt text`.

### 7.2. Run unit tests

There are unit tests for caption cleaning, word replacements, prompt building, per-field selection and overwrite logic, and CLI flag validation:

```bash
python -m unittest test_caption.py test_replacements.py test_image_processor.py test_update_images.py
```

All tests should pass.

---

## 8. Troubleshooting

- **`exiftool not found`**
  Install it with:

  ```bash
  brew install exiftool  # macOS
  ```

- **`caption.py error` or JSON decode errors**
  Often means `llm` is misconfigured or your LLM provider is not accessible. Check:

  ```bash
  llm models
  ```

  Confirm that the model you are using (e.g. `claude-sonnet-5-5`) is listed and working.

- **LLM API key issues**
  Re-run:

  ```bash
  llm keys list
  llm keys set anthropic
  ```

  And verify on your provider’s dashboard that the key is valid.

---

## 9. Web interface (optional)

A small Flask app (`webapp.py`) wraps the same pipeline for bulk uploads through a browser
instead of the CLI:

```bash
source .venv/bin/activate
flask --app webapp run
```

Then open http://127.0.0.1:5000. Upload one or more images, pick a model, add optional context,
and tick the fields to generate. They are the same controls as `update-images.py`'s flags:

- **Alt text**, **IPTC Title**, **IPTC Description**, **IPTC Keywords** — each is its own checkbox
  (nothing is selected by default; at least one is required).
- Each field has an **Overwrite existing** checkbox beside it, enabled once the field is ticked. A ticked
  field that already has a value is skipped unless its Overwrite box is checked.
- **Creative titles** appears under Title and **Creative descriptions** under Description when those are ticked.

Thumbnails of the images you choose appear immediately, before anything is uploaded. After you click
**Upload & Process**, each image becomes an expandable row as its result arrives, with a table of what
was written, skipped, or failed for every field. When the batch finishes, **Run again** reprocesses the
same images using whatever options are currently ticked, so you can change a checkbox and compare
results without re-selecting files. Each run starts from your original images, not the previously tagged copies.

Progress and results are shown live; when done, download a zip of the tagged images
(metadata embedded exactly as the CLI would write it, since the web app calls the same
`image_processor.py` logic in-process).

Notes:
- Single-user local tool: no auth, in-memory job tracking, one job processed at a time.
- Uploaded/processed files live in a temp directory per job and aren't cleaned up automatically.

## 10. Summary

1. Install `exiftool`, `llm`, and configure your Anthropic API key.
2. Create and activate a Python virtualenv.
3. `pip install -r requirements.txt`.
4. Run:

   ```bash
   python update-images.py /path/to/images --alt --title --description --keywords [--overwrite-alt] [--overwrite-title] [--overwrite-description] [--overwrite-keywords] [--context ...] [--model ...] [--creative-title] [--creative-description]
   ```

   to generate and embed the fields you select (use any combination of the four field flags; at least one is required), with optional creative title and short-story description styles.

