import json
import logging
import os
import subprocess
import tempfile
import threading
import urllib.request
import urllib.parse
import zipfile
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from PIL import Image

from upscale.adapters import get_adapter
from upscale.config import AppConfig
from upscale.jobs import JobStore
from upscale.processing import process_image, safe_name, validate_settings

config = AppConfig.from_env()

logging.basicConfig(
    level=getattr(logging, config.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("photo_upscale")

app = Flask(__name__)
app.secret_key = config.app_secret
app.config["MAX_CONTENT_LENGTH"] = config.max_upload_mb * 1024 * 1024

Image.MAX_IMAGE_PIXELS = config.max_image_pixels

ALLOWED_EXTS = {".jpg", ".jpeg"}

JOB_STORE = JobStore()


def _job_dir() -> str:
    base = config.work_dir or None
    return tempfile.mkdtemp(prefix="upscale_", dir=base)


def _unique_output_name(base: str, used: set[str]) -> str:
    if base not in used:
        used.add(base)
        return base
    root, ext = os.path.splitext(base)
    counter = 2
    while True:
        candidate = f"{root}_{counter}{ext}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


def _send_telegram_direct(message: str) -> bool:
    token = config.telegram_bot_token.strip()
    chat_id = config.telegram_chat_id.strip()
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return bool(payload.get("ok"))
    except Exception as exc:
        logger.warning("Direct Telegram notification failed: %s", exc)
        return False


def _send_done_notification(message: str) -> bool:
    if not config.notify_on_done:
        return False

    # Preferred path: direct Telegram API (works on any machine running app).
    if _send_telegram_direct(message):
        return True

    # Fallback path: OpenClaw CLI messaging.
    if not config.notify_target:
        logger.info("Notification skipped: NOTIFY_TARGET is empty.")
        return False
    try:
        result = subprocess.run(
            [
                "openclaw",
                "message",
                "send",
                "--channel",
                config.notify_channel,
                "--target",
                config.notify_target,
                "--message",
                message,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        return result.returncode == 0
    except Exception as exc:
        logger.warning("Fallback notification send failed: %s", exc)
        return False


def _run_job(job_id: str, inputs: list[tuple[str, str]], scale: float, target_mb: float, work_dir: str) -> None:
    adapter = get_adapter(config.upscale_adapter, config.topaz_cli_path, config.ai_model_path)
    job = JOB_STORE.get(job_id)
    if not job:
        return

    JOB_STORE.update(job_id, status="processing", message="Processing images...")

    zip_name = f"upscaled_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    zip_path = str(Path(work_dir) / zip_name)

    report_lines = [
        "source_name\toutput_name\tstatus\tsrc_w\tsrc_h\tout_w\tout_h\tquality\tsize_mb\tnotes"
    ]

    used_names: set[str] = set()
    succeeded = failed = skipped = warnings = 0

    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for idx, (path, original_name) in enumerate(inputs, start=1):
                ext = os.path.splitext(original_name)[1].lower()
                if ext not in ALLOWED_EXTS:
                    skipped += 1
                    report_lines.append(
                        f"{original_name}\t\tfailed_invalid\t\t\t\t\t\t\tUnsupported file type."
                    )
                    JOB_STORE.update(
                        job_id,
                        processed=idx,
                        succeeded=succeeded,
                        failed=failed,
                        skipped=skipped,
                        warnings=warnings,
                    )
                    continue

                output_name = _unique_output_name(f"{safe_name(original_name)}_upscaled.jpg", used_names)
                JOB_STORE.update(job_id, current_item=original_name, message=f"Processing {idx}/{len(inputs)}: {original_name}")
                result = process_image(
                    path=path,
                    source_name=original_name,
                    output_name=output_name,
                    adapter=adapter,
                    scale=scale,
                    target_mb=target_mb,
                    max_size_passes=config.max_size_passes,
                    max_output_pixels=config.max_output_pixels,
                )

                if result.output_bytes:
                    zf.writestr(output_name, result.output_bytes)

                report_lines.append(result.report.as_tsv())

                if result.report.status == "ok":
                    succeeded += 1
                elif result.report.status == "target_not_met":
                    warnings += 1
                elif result.report.status.startswith("failed"):
                    failed += 1
                else:
                    skipped += 1

                JOB_STORE.update(
                    job_id,
                    processed=idx,
                    succeeded=succeeded,
                    failed=failed,
                    skipped=skipped,
                    warnings=warnings,
                )

            zf.writestr("_report.tsv", "\n".join(report_lines))

        summary = f"Processing complete. {succeeded} met target, {warnings} upscaled but below target, {failed} hard failures."
        JOB_STORE.update(
            job_id,
            status="done",
            current_item="",
            message=summary,
            zip_path=zip_path,
            warnings=warnings,
        )
        notify_msg = (
            f"✅ Photo batch complete. {succeeded} met 20MB target, "
            f"{warnings} upscaled <20MB, {failed} hard failures. ZIP is ready to download in the app."
        )
        _send_done_notification(notify_msg)
    except Exception as exc:
        logger.exception("Job %s failed: %s", job_id, exc)
        JOB_STORE.update(
            job_id,
            status="failed",
            current_item="",
            message="Processing failed. See report for details.",
        )
        _send_done_notification("⚠️ Photo batch failed before completion. Open the app to retry and check details.")
    finally:
        for path, _ in inputs:
            try:
                os.remove(path)
            except OSError:
                pass


@app.route("/", methods=["GET"])
def index():
    return render_template(
        "index.html",
        min_scale=config.min_scale,
        min_target=config.min_target_mb,
        max_target=config.max_target_mb,
        max_files=config.max_files,
    )


@app.route("/notify-test", methods=["POST"])
def notify_test():
    sent = _send_done_notification("🧪 Clearform Upscaler test notification: Telegram alerts are working.")
    if sent:
        flash("Test notification sent. Check Telegram.")
    else:
        flash("Test notification could not be sent. Check TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.")
    return redirect(url_for("index"))


@app.route("/process", methods=["POST"])
def process():
    files = request.files.getlist("photos")
    if not files or files[0].filename == "":
        flash("Please upload at least one JPG/JPEG file.")
        return redirect(url_for("index"))

    if len(files) > config.max_files:
        flash(f"Too many files. Max allowed is {config.max_files}.")
        return redirect(url_for("index"))

    try:
        scale = float(request.form.get("scale", str(config.min_scale)))
        target_mb = float(request.form.get("target_mb", str(config.min_target_mb)))
        validate_settings(scale, target_mb, config.min_scale, config.min_target_mb, config.max_target_mb)
    except ValueError:
        flash(
            f"Invalid settings. Scale must be >= {config.min_scale} and target size between "
            f"{config.min_target_mb}MB and {config.max_target_mb}MB."
        )
        return redirect(url_for("index"))

    job = JOB_STORE.create(total=len(files))

    work_dir = _job_dir()
    inputs: list[tuple[str, str]] = []

    seen_inputs: set[str] = set()
    for f in files:
        if not f.filename:
            continue
        original_name = os.path.basename(f.filename)
        base = safe_name(original_name)
        ext = os.path.splitext(original_name)[1] or ".jpg"
        input_name = _unique_output_name(f"{base}{ext}", seen_inputs)
        dest = str(Path(work_dir) / input_name)
        f.save(dest)
        inputs.append((dest, original_name))

    thread = threading.Thread(
        target=_run_job,
        args=(job.job_id, inputs, scale, target_mb, work_dir),
        daemon=True,
    )
    thread.start()

    return redirect(url_for("job_status", job_id=job.job_id))


@app.route("/job/<job_id>", methods=["GET"])
def job_status(job_id: str):
    job = JOB_STORE.get(job_id)
    if not job:
        flash("That job could not be found.")
        return redirect(url_for("index"))
    return render_template("status.html", job_id=job_id)


@app.route("/status/<job_id>", methods=["GET"])
def status(job_id: str):
    job = JOB_STORE.get(job_id)
    if not job:
        return jsonify({"error": "not_found"}), 404

    payload = job.to_dict()
    if job.status == "done" and job.zip_path:
        payload["download_url"] = url_for("download", job_id=job_id)
    return jsonify(payload)


@app.route("/download/<job_id>", methods=["GET"])
def download(job_id: str):
    job = JOB_STORE.get(job_id)
    if not job or not job.zip_path:
        flash("ZIP file not available.")
        return redirect(url_for("index"))
    return send_file(job.zip_path, as_attachment=True, download_name=os.path.basename(job.zip_path))


@app.errorhandler(413)
def too_large(_):
    flash(f"Upload too large. Max total upload is {config.max_upload_mb}MB.")
    return redirect(url_for("index"))


@app.errorhandler(500)
def server_error(_):
    flash("Something went wrong. Please try again or contact support.")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
