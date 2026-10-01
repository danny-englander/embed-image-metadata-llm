# Usage: update-images.py

`update-images.py` generates image metadata (alt text, IPTC title, description, and keywords) with an LLM and writes it into the image files themselves.

**What it does**

- Scans a **directory you specify** for images (`.jpg`, `.jpeg`, `.png`, `.gif`, `.heic`, `.heif`, `.webp`).
- You choose which fields to generate, independently: **`--alt`**, **`--title`**, **`--description`**, **`--keywords`** (at least one is required).
- For each selected field that is empty (or whose `--overwrite-*` flag is given):
  - **Alt text** – calls **caption.py** (Anthropic/LLM via `llm` + `llm-anthropic`) and writes the **XMP Alt Text (Accessibility)** field using **exiftool** (limit 250 chars).
  - **Title / Description / Keywords** – one LLM call for whichever of the three are needed: a Title (up to 59 chars), Description (3–4 sentences by default; other styles via `--title-style` / `--description-style`), and ~500-character Keywords. Written to IPTC Core `Title`/`ObjectName`, `Description`/`Caption-Abstract`, and `Keywords`/`Subject` (full replace, not append).
- A selected field that already has a value is skipped unless its overwrite flag is given; other selected fields still run.
- Requires:
  - `exiftool` (e.g. `brew install exiftool`)
  - `llm` + `llm-anthropic`, API key via `llm keys set anthropic`
  - Optional: `IMAGE_CAPTION_CONFIG` / `models.yaml` (see caption.py)

**Typical use**

- Add or refresh accessibility alt text **in the image files themselves** (e.g. for a local photo gallery or static site generator that reads XMP).
- Generate or refresh Adobe Bridge IPTC Title, Description, and Keywords with `--title`, `--description`, and `--keywords`.

**Example**

```bash
python update-images.py /path/to/image/folder --alt
python update-images.py /path/to/folder --alt --overwrite-alt --context "Cherry blossoms at Japanese Friendship Garden"
python update-images.py /path/to/folder --alt --title --description --keywords
python update-images.py /path/to/folder --keywords --overwrite-keywords
```

**Options**

- `directory` – folder containing images.
- Optional positional or `-c` / `--context` – short description to improve captions.
- `--model` – model passed to caption.py (default: `claude-sonnet-5-5`).
- `--alt`, `--title`, `--description`, `--keywords` – the fields to generate (select at least one).
- `--overwrite-alt`, `--overwrite-title`, `--overwrite-description`, `--overwrite-keywords` – replace an existing value for that field (requires the matching field flag). Without it, a field that is already set is skipped.
- `--overwrite-all` – replace existing values for every selected field.
- `--title-style` – with `--title`: `standard` (default), `creative`, `editorial`, `poetic`, or `literal`.
- `--description-style` – with `--description`: `standard` (default), `creative` (short story, ≤375 characters), `caption` (one sentence, ≤200 characters), or `photographic`.
- `--creative-title`, `--creative-description` – shortcuts for the `creative` style of each.
