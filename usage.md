# Usage: update-images.py vs update-images.py

This document describes what each script does, how they differ, and whether they depend on each other.

---

## Summary

| | **update-images.py** | **update-images.py** |
|---|---|---|
| **Purpose** | Generate alt text and **write it into image files** (XMP metadata) | Generate alt text and titles and **push them to a website API** |
| **Where output goes** | Local image files (exiftool / XMP AltTextAccessibility) | Remote API (HTTP PATCH to dri.es album) |
| **Auth / API** | None (fully local) | Requires `AUTH_TOKEN` (env or `.env`) |
| **Directory** | Any folder path you pass as argument | Subdirectory **under a fixed `BASE_DIR`** (hardcoded) |
| **Shared dependency** | Uses `caption.py` | Uses `caption.py` |

**They are not reliant on each other.** Both use `caption.py` to generate alt text, but they are independent workflows: one is local/file-based, the other is remote/API-based.

---

## update-images.py

**What it does**

- Scans a **directory you specify** for images (`.jpg`, `.jpeg`, `.png`, `.gif`, `.heic`, `.webp`).
- You choose which fields to generate, independently: **`--alt`**, **`--title`**, **`--description`**, **`--keywords`** (at least one is required).
- For each selected field that is empty (or whose `--overwrite-*` flag is given):
  - **Alt text** – calls **caption.py** (Anthropic/LLM via `llm` + `llm-anthropic`) and writes the **XMP Alt Text (Accessibility)** field using **exiftool** (limit 250 chars).
  - **Title / Description / Keywords** – one LLM call for whichever of the three are needed: a Title (up to 59 chars), Description (3–4 sentences, or a ≤375-character short story with `--creative-description`), and ~500-character Keywords. Written to IPTC Core `Title`/`ObjectName`, `Description`/`Caption-Abstract`, and `Keywords`/`Subject` (full replace, not append).
- A selected field that already has a value is skipped unless its overwrite flag is given; other selected fields still run.
- No remote API and no `AUTH_TOKEN`. Requires:
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
- `--creative-title` – with `--title`, generate evocative titles instead of descriptive marketplace-style ones.
- `--creative-description` – with `--description`, write the Description as a creative short story of at most 375 characters.
---

## update-images.py

**What it does**

- Works with a **fixed base path** (`BASE_DIR`) and **website API** (`BASE_URL`). Out of the box it’s set up for `https://dri.es/album/` and a Dropbox images path.
- For a given **subdirectory name** (relative to `BASE_DIR`):
  - Finds images (`.jpg`, `.png`, `.gif` only).
  - For each image:
    - **GET**s existing metadata (title, caption, alt, verified) from the website API.
    - Skips the image if it’s marked **verified** (unless `--force`).
    - Calls **caption.py** to generate new alt text (with rich context: album, title, caption, existing alt, notes).
    - Optionally **formats the title** via `llm` (sentence case, etc.).
    - **PATCH**es new alt and/or title back to the website (and sets `verified: 0`).
- Requires **AUTH_TOKEN** (environment variable or `.env`). No exiftool; metadata lives on the server, not in the file.

**Typical use**

- Batch-update alt text and titles **on the live website** for a specific album directory, with server-stored metadata and a “verified” flag.

**Example**

```bash
export AUTH_TOKEN=your_token   # or use .env
python update-images.py my-album-folder
python update-images.py my-album-folder --context "Trip to Japan" --force
```

**Options**

- `directory` – subdirectory under `BASE_DIR` to process.
- `--model` – model for caption.py and for title formatting (default: `claude-sonnet-5-5`).
- `--context` – extra notes included when generating alt text.
- `--force` – process images even if they are marked verified.

---

## How they relate to each other

- **No direct dependency between the two scripts.** You never run one script from the other.
- **Shared dependency:** both call **caption.py** as a subprocess to generate alt text. So:
  - **caption.py** is the common piece (and may rely on `llm`, `models.yaml`, etc.).
  - **update-images.py** and **update-images.py** are two separate **workflows** that both use that common caption generator.

**When to use which**

- Use **update-images.py** when you want alt text **stored in the image files** (XMP), with no server or token (e.g. local galleries, static sites).
- Use **update-images.py** when you want to **update alt text and titles on the website** via its API, with server-side metadata and verification.

You can use one, the other, or both in different parts of your pipeline; they do not rely on each other.
