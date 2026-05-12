import os
import uuid
import threading
import json
import subprocess
import re
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
CLIPS_FOLDER = "clips"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CLIPS_FOLDER, exist_ok=True)

jobs = {}


def sanitize_filename(name):
    return re.sub(r'[^\w\-_.]', '_', name)


def run_job(job_id, url, threshold, min_scene_len):
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

        jobs[job_id]["progress"] = 40
        jobs[job_id]["status"] = "detecting"
        jobs[job_id]["message"] = "Mendeteksi adegan..."

        scene_list_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_scenes.json")

        detect_result = subprocess.run(
            [
                "python", "-c",
                f"""
import json
from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector

video = open_video(r"{video_path}")
scene_manager = SceneManager()
scene_manager.add_detector(ContentDetector(threshold={threshold}, min_scene_len={min_scene_len}))
scene_manager.detect_scenes(video)
scenes = scene_manager.get_scene_list()
result = []
for start, end in scenes:
    result.append({{"start": start.get_seconds(), "end": end.get_seconds()}})
with open(r"{scene_list_path}", "w") as f:
    json.dump(result, f)
print(f"Found {{len(result)}} scenes")
"""
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if detect_result.returncode != 0:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["message"] = f"Gagal deteksi adegan: {detect_result.stderr[-300:]}"
            return

        with open(scene_list_path, "r") as f:
            scenes = json.load(f)

        if not scenes:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["message"] = "Tidak ada adegan yang terdeteksi. Coba turunkan nilai threshold."
            return

        jobs[job_id]["progress"] = 60
        jobs[job_id]["status"] = "clipping"
        jobs[job_id]["message"] = f"Memotong {len(scenes)} adegan..."
        jobs[job_id]["total_scenes"] = len(scenes)

        clips = []
        for i, scene in enumerate(scenes):
            clip_filename = f"{job_id}_clip_{i+1:03d}.mp4"
            clip_path = os.path.join(CLIPS_FOLDER, clip_filename)
            start = scene["start"]
            duration = scene["end"] - scene["start"]

            if duration < 0.5:
                continue

            cut_result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(start),
                    "-i", video_path,
                    "-t", str(duration),
                    "-c:v", "libx264",
                    "-c:a", "aac",
                    "-movflags", "+faststart",
                    clip_path,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if cut_result.returncode == 0 and os.path.exists(clip_path):
                size_bytes = os.path.getsize(clip_path)
                clips.append({
                    "filename": clip_filename,
                    "index": i + 1,
                    "start": round(start, 2),
                    "end": round(scene["end"], 2),
                    "duration": round(duration, 2),
                    "size_bytes": size_bytes,
                })

            progress = 60 + int((i + 1) / len(scenes) * 35)
            jobs[job_id]["progress"] = progress
            jobs[job_id]["clips_done"] = i + 1

        if os.path.exists(video_path):
            os.remove(video_path)
        if os.path.exists(scene_list_path):
            os.remove(scene_list_path)

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
    threshold = float(data.get("threshold", 27.0))
    min_scene_len = int(data.get("min_scene_len", 15))

    if not url:
        return jsonify({"error": "URL tidak boleh kosong"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "message": "Memulai proses...",
        "clips": [],
        "url": url,
    }

    thread = threading.Thread(target=run_job, args=(job_id, url, threshold, min_scene_len))
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
