import os
import uuid
import threading
import subprocess
import math
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
CLIPS_FOLDER = "clips"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CLIPS_FOLDER, exist_ok=True)

jobs = {}


def get_video_duration(video_path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return float(result.stdout.strip())


def run_job(job_id, url, clip_duration, overlap):
    try:
        jobs[job_id]["status"] = "downloading"
        jobs[job_id]["progress"] = 5
        jobs[job_id]["message"] = "Mengunduh video..."

        video_path = os.path.join(UPLOAD_FOLDER, f"{job_id}.mp4")

        dl_result = subprocess.run(
            [
                "yt-dlp",
                "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "--merge-output-format", "mp4",
                "-o", video_path,
                "--no-playlist",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )

        if dl_result.returncode != 0:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["message"] = f"Gagal mengunduh video: {dl_result.stderr[-300:]}"
            return

        jobs[job_id]["progress"] = 45
        jobs[job_id]["status"] = "analyzing"
        jobs[job_id]["message"] = "Menganalisis durasi video..."

        total_duration = get_video_duration(video_path)
        step = clip_duration - overlap
        if step <= 0:
            step = clip_duration

        starts = []
        t = 0.0
        while t < total_duration:
            starts.append(t)
            t += step

        total_clips = len(starts)
        jobs[job_id]["total_scenes"] = total_clips
        jobs[job_id]["progress"] = 55
        jobs[job_id]["status"] = "clipping"
        jobs[job_id]["message"] = f"Memotong menjadi {total_clips} klip..."

        clips = []
        for i, start in enumerate(starts):
            actual_duration = min(clip_duration, total_duration - start)
            if actual_duration < 1.0:
                break

            clip_filename = f"{job_id}_clip_{i+1:03d}.mp4"
            clip_path = os.path.join(CLIPS_FOLDER, clip_filename)

            cut_result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(start),
                    "-i", video_path,
                    "-t", str(actual_duration),
                    "-c:v", "libx264",
                    "-c:a", "aac",
                    "-movflags", "+faststart",
                    clip_path,
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )

            if cut_result.returncode == 0 and os.path.exists(clip_path):
                size_bytes = os.path.getsize(clip_path)
                clips.append({
                    "filename": clip_filename,
                    "index": i + 1,
                    "start": round(start, 2),
                    "end": round(start + actual_duration, 2),
                    "duration": round(actual_duration, 2),
                    "size_bytes": size_bytes,
                })

            progress = 55 + int((i + 1) / total_clips * 40)
            jobs[job_id]["progress"] = progress
            jobs[job_id]["clips_done"] = i + 1

        if os.path.exists(video_path):
            os.remove(video_path)

        jobs[job_id]["status"] = "done"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["message"] = f"Selesai! {len(clips)} klip berhasil dibuat."
        jobs[job_id]["clips"] = clips

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["message"] = str(e)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/process", methods=["POST"])
def process_video():
    data = request.get_json()
    url = data.get("url", "").strip()
    clip_duration = float(data.get("clip_duration", 30))
    overlap = float(data.get("overlap", 0))

    if not url:
        return jsonify({"error": "URL tidak boleh kosong"}), 400
    if clip_duration < 1:
        return jsonify({"error": "Durasi klip minimal 1 detik"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "message": "Memulai proses...",
        "clips": [],
        "url": url,
    }

    thread = threading.Thread(target=run_job, args=(job_id, url, clip_duration, overlap))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job tidak ditemukan"}), 404
    return jsonify(job)


@app.route("/api/clips/<filename>")
def serve_clip(filename):
    return send_from_directory(CLIPS_FOLDER, filename)


@app.route("/api/clips/<filename>", methods=["DELETE"])
def delete_clip(filename):
    clip_path = os.path.join(CLIPS_FOLDER, filename)
    if os.path.exists(clip_path):
        os.remove(clip_path)
        return jsonify({"success": True})
    return jsonify({"error": "File tidak ditemukan"}), 404


@app.route("/api/clips")
def list_clips():
    clips = []
    for fname in os.listdir(CLIPS_FOLDER):
        if fname.endswith(".mp4"):
            fpath = os.path.join(CLIPS_FOLDER, fname)
            clips.append({
                "filename": fname,
                "size_bytes": os.path.getsize(fpath),
                "modified": os.path.getmtime(fpath),
            })
    clips.sort(key=lambda x: x["modified"], reverse=True)
    return jsonify(clips)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
