#!/usr/bin/env python3
"""Web UI for embed-image-metadata-llm: bulk-upload images, run them through the same
processing pipeline as update-images.py, and download the tagged files.

Run with: flask --app webapp run
"""

import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

from caption import load_models
from image_processor import (
    DEFAULT_MODEL,
    DELAY_BETWEEN_REQUESTS,
    DESCRIPTION_STYLES,
    EXTENSIONS,
    FIELDS,
    TITLE_STYLES,
    process_single_image,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB per upload batch

JOBS_ROOT = Path(tempfile.gettempdir()) / "image-caption-jobs"
JOBS_ROOT.mkdir(exist_ok=True)

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _run_job(
    job_id: str,
    model: str,
    context: str,
    fields: tuple,
    overwrite: tuple,
    title_style: str,
    description_style: str,
) -> None:
    with _jobs_lock:
        job = _jobs[job_id]
        image_paths = sorted(job["dir"].iterdir())

    for idx, image_path in enumerate(image_paths):
        if idx > 0:
            time.sleep(DELAY_BETWEEN_REQUESTS)
        try:
            result = process_single_image(
                image_path,
                model,
                context,
                fields,
                overwrite,
                title_style,
                description_style,
            )
        except Exception as e:  # e.g. a corrupt image; don't let it stall the whole job
            result = {
                "status": "error",
                "message": f"Unexpected error: {str(e).replace(str(image_path), image_path.name)}",
                "alt": None,
                "title": None,
                "description": None,
                "keywords": None,
                "written": [],
                "skipped": [],
                "failed": {f: "unexpected error" for f in fields},
                "existing": {},
            }
        with _jobs_lock:
            job["results"].append(
                {
                    "filename": image_path.name,
                    **result,
                    "styles": {"title": title_style, "description": description_style},
                }
            )
            job["done"] += 1

    with _jobs_lock:
        job["state"] = "done"


@app.route("/")
def index():
    models = load_models()
    model_list = sorted(
        (
            {"name": name, "installed": config["installed"], "description": config["description"]}
            for name, config in models.items()
        ),
        key=lambda m: (not m["installed"], m["name"]),
    )
    default_model = DEFAULT_MODEL if models.get(DEFAULT_MODEL, {}).get("installed") else next(
        (m["name"] for m in model_list if m["installed"]), None
    )
    return render_template("index.html", models=model_list, default_model=default_model)


@app.route("/jobs", methods=["POST"])
def create_job():
    files = [f for f in request.files.getlist("images") if f.filename]
    if not files:
        return jsonify({"error": "No images uploaded."}), 400

    model = request.form.get("model", DEFAULT_MODEL)
    context = request.form.get("context", "").strip() or None
    fields = tuple(f for f in FIELDS if request.form.get(f) == "on")
    if not fields:
        return jsonify({"error": "Select at least one field to generate."}), 400
    if request.form.get("overwrite_all") == "on":
        overwrite = fields
    else:
        overwrite = tuple(f for f in fields if request.form.get(f"overwrite_{f}") == "on")
    # A style only applies to a selected field; otherwise it is ignored.
    title_style = request.form.get("title_style", "standard") if "title" in fields else "standard"
    description_style = (
        request.form.get("description_style", "standard") if "description" in fields else "standard"
    )
    if title_style not in TITLE_STYLES or description_style not in DESCRIPTION_STYLES:
        return jsonify({"error": "Unknown title or description style."}), 400

    job_id = uuid.uuid4().hex
    job_dir = JOBS_ROOT / job_id
    job_dir.mkdir(parents=True)

    saved_files = {}  # saved name -> original upload name
    for f in files:
        name = secure_filename(f.filename)
        if not name or Path(name).suffix.lower() not in EXTENSIONS:
            continue
        f.save(job_dir / name)
        saved_files[name] = f.filename
    saved = len(saved_files)

    if saved == 0:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"error": "No supported image files in upload."}), 400

    with _jobs_lock:
        _jobs[job_id] = {
            "dir": job_dir,
            "total": saved,
            "done": 0,
            "results": [],
            "state": "running",
        }

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, model, context, fields, overwrite, title_style, description_style),
        daemon=True,
    )
    thread.start()

    # Listed in processing order (sorted by saved name) so the UI can show rows up front.
    return jsonify(
        {
            "job_id": job_id,
            "files": [{"saved": n, "original": saved_files[n]} for n in sorted(saved_files)],
        }
    )


@app.route("/jobs/<job_id>/status")
def job_status(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job."}), 404
        return jsonify(
            {
                "total": job["total"],
                "done": job["done"],
                "state": job["state"],
                "results": list(job["results"]),
            }
        )


@app.route("/jobs/<job_id>/download")
def job_download(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job."}), 404
        job_dir = job["dir"]

    zip_base = JOBS_ROOT / f"{job_id}-download"
    zip_path = Path(shutil.make_archive(str(zip_base), "zip", root_dir=job_dir))
    return send_file(zip_path, as_attachment=True, download_name="tagged-images.zip")


if __name__ == "__main__":
    app.run(debug=True)
