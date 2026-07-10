import os
import uuid
import threading
import subprocess
import math
import sqlite3
import secrets
from datetime import datetime, timezone
from urllib.parse import quote
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, request, jsonify, send_from_directory, render_template, session, g

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")
if not app.secret_key:
    app.secret_key = secrets.token_hex(32)
    print("WARNING: SESSION_SECRET not set. Using a random session secret. Sessions will not survive restarts.")

is_production = os.environ.get("FLASK_ENV") == "production"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=is_production,
    SESSION_COOKIE_SAMESITE="Lax",
)

UPLOAD_FOLDER = "uploads"
CLIPS_FOLDER = "clips"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.db")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CLIPS_FOLDER, exist_ok=True)

jobs = {}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            clip_duration REAL,
            overlap REAL,
            status TEXT,
            progress INTEGER DEFAULT 0,
            message TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            clip_index INTEGER,
            start REAL,
            end REAL,
            duration REAL,
            size_bytes INTEGER,
            deleted INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(job_id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    db.commit()
    db.close()


init_db()


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


def run_job(job_id, user_id, url, clip_duration, overlap):
    db = sqlite3.connect(DB_PATH)
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "INSERT INTO jobs (job_id, user_id, url, clip_duration, overlap, status, progress, message, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, user_id, url, clip_duration, overlap, "queued", 0, "Memulai proses...", now),
    )
    db.commit()
    db.close()

    def update_job(status, progress, message, completed=False):
        jobs[job_id]["status"] = status
        jobs[job_id]["progress"] = progress
        jobs[job_id]["message"] = message
        db = sqlite3.connect(DB_PATH)
        completed_at = datetime.now(timezone.utc).isoformat() if completed else None
        db.execute(
            "UPDATE jobs SET status = ?, progress = ?, message = ?, completed_at = ? WHERE job_id = ?",
            (status, progress, message, completed_at, job_id),
        )
        db.commit()
        db.close()

    try:
        update_job("downloading", 5, "Mengunduh video...")

        video_path = os.path.join(UPLOAD_FOLDER, f"{job_id}.mp4")

        dl_result = subprocess.run(
            [
                "yt-dlp",
                "-f", "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
                "--merge-output-format", "mp4",
                "-o", video_path,
                "--no-playlist",
                "--concurrent-fragments", "4",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )

        if dl_result.returncode != 0:
            update_job("error", 5, f"Gagal mengunduh video: {dl_result.stderr[-300:]}")
            return

        update_job("analyzing", 45, "Menganalisis durasi video...")

        total_duration = get_video_duration(video_path)
        step = clip_duration - overlap
        if step <= 0:
            step = clip_duration

        estimated_clips = max(1, int(total_duration / step))
        jobs[job_id]["total_scenes"] = estimated_clips
        update_job("clipping", 55, f"Memotong menjadi ~{estimated_clips} klip (stream copy)...")

        clip_pattern = os.path.join(CLIPS_FOLDER, f"{job_id}_clip_%03d.mp4")

        cut_result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", video_path,
                "-c", "copy",
                "-f", "segment",
                "-segment_time", str(step),
                "-reset_timestamps", "1",
                "-movflags", "+faststart",
                clip_pattern,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )

        if cut_result.returncode != 0:
            update_job("error", 55, f"Gagal memotong video: {cut_result.stderr[-300:]}")
            return

        if os.path.exists(video_path):
            os.remove(video_path)

        clips = []
        i = 0
        t = 0.0
        while True:
            clip_filename = f"{job_id}_clip_{i:03d}.mp4"
            clip_path = os.path.join(CLIPS_FOLDER, clip_filename)
            if not os.path.exists(clip_path):
                break
            size_bytes = os.path.getsize(clip_path)
            actual_duration = min(clip_duration, max(0, total_duration - t))
            clips.append({
                "filename": clip_filename,
                "index": i + 1,
                "start": round(t, 2),
                "end": round(min(t + clip_duration, total_duration), 2),
                "duration": round(actual_duration, 2),
                "size_bytes": size_bytes,
            })
            t += step
            i += 1

        jobs[job_id]["clips_done"] = len(clips)

        now = datetime.now(timezone.utc).isoformat()
        db = sqlite3.connect(DB_PATH)
        for clip in clips:
            db.execute(
                """
                INSERT INTO clips (job_id, user_id, filename, clip_index, start, end, duration, size_bytes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, user_id, clip["filename"], clip["index"], clip["start"], clip["end"], clip["duration"], clip["size_bytes"], now),
            )
        db.commit()
        db.close()

        update_job("done", 100, f"Selesai! {len(clips)} klip berhasil dibuat.", completed=True)
        jobs[job_id]["clips"] = clips

    except Exception as e:
        error_msg = str(e)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["message"] = error_msg
        db = sqlite3.connect(DB_PATH)
        db.execute("UPDATE jobs SET status = ?, message = ? WHERE job_id = ?", ("error", error_msg, job_id))
        db.commit()
        db.close()


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Silakan masuk terlebih dahulu"}), 401
        return f(*args, **kwargs)
    return decorated


def safe_basename(filename):
    """Return a safe basename for a clip file, or None if invalid."""
    base = os.path.basename(filename)
    if base != filename or not base or "/" in base or "\\" in base or ".." in base:
        return None
    return base


# Allowed video platforms. Subdomains are accepted automatically.


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return render_template("index.html")
    return render_template("dashboard.html")


@app.route("/api/me")
def me():
    if "user_id" in session:
        db = get_db()
        user = db.execute("SELECT id, username, created_at FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if user:
            return jsonify({"user": dict(user)})
    return jsonify({"user": None})


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Username dan password wajib diisi"}), 400
    if len(username) < 3 or len(username) > 32:
        return jsonify({"error": "Username harus 3-32 karakter"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password minimal 6 karakter"}), 400

    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        return jsonify({"error": "Username sudah terdaftar"}), 409

    db.execute(
        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, generate_password_hash(password), datetime.now(timezone.utc).isoformat()),
    )
    db.commit()
    user = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    session["user_id"] = user["id"]
    return jsonify({"user": {"id": user["id"], "username": username}}), 201


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")

    db = get_db()
    user = db.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Username atau password salah"}), 401

    session["user_id"] = user["id"]
    return jsonify({"user": {"id": user["id"], "username": user["username"]}})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/api/process", methods=["POST"])
@login_required
def process_video():
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    clip_duration = data.get("clip_duration", 30)
    overlap = data.get("overlap", 0)

    try:
        clip_duration = float(clip_duration)
        overlap = float(overlap)
    except (ValueError, TypeError):
        return jsonify({"error": "Durasi dan overlap harus berupa angka"}), 400

    if not math.isfinite(clip_duration) or not math.isfinite(overlap):
        return jsonify({"error": "Durasi dan overlap harus berupa angka yang valid"}), 400

    if not url:
        return jsonify({"error": "URL tidak boleh kosong"}), 400
    if clip_duration < 1 or clip_duration > 3600:
        return jsonify({"error": "Durasi klip harus antara 1 dan 3600 detik"}), 400
    if overlap < 0 or overlap >= clip_duration:
        return jsonify({"error": "Overlap harus 0 atau lebih kecil dari durasi klip"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "message": "Memulai proses...",
        "clips": [],
        "url": url,
    }

    thread = threading.Thread(target=run_job, args=(job_id, user_id, url, clip_duration, overlap))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
@login_required
def job_status(job_id):
    user_id = session["user_id"]
    db = get_db()
    row = db.execute(
        "SELECT job_id, url, clip_duration, overlap, status, progress, message, created_at, completed_at FROM jobs WHERE job_id = ? AND user_id = ?",
        (job_id, user_id),
    ).fetchone()
    if not row:
        return jsonify({"error": "Job tidak ditemukan"}), 404

    job = dict(row)
    job["clips"] = []

    in_memory = jobs.get(job_id)
    if in_memory:
        job.update({
            "status": in_memory.get("status", job["status"]),
            "progress": in_memory.get("progress", job["progress"]),
            "message": in_memory.get("message", job["message"]),
            "total_scenes": in_memory.get("total_scenes"),
            "clips_done": in_memory.get("clips_done"),
        })
        if in_memory.get("clips"):
            job["clips"] = in_memory["clips"]
        elif job["status"] == "done":
            clips = db.execute(
                "SELECT filename, clip_index, start, end, duration, size_bytes FROM clips WHERE job_id = ? AND user_id = ? AND deleted = 0 ORDER BY clip_index",
                (job_id, user_id),
            ).fetchall()
            job["clips"] = [dict(c) for c in clips]
    elif job["status"] == "done":
        clips = db.execute(
            "SELECT filename, clip_index, start, end, duration, size_bytes FROM clips WHERE job_id = ? AND user_id = ? AND deleted = 0 ORDER BY clip_index",
            (job_id, user_id),
        ).fetchall()
        job["clips"] = [dict(c) for c in clips]

    return jsonify(job)


@app.route("/api/clips/<filename>")
@login_required
def serve_clip(filename):
    user_id = session["user_id"]
    base = safe_basename(filename)
    if not base:
        return jsonify({"error": "Nama file tidak valid"}), 400

    db = get_db()
    row = db.execute(
        "SELECT id FROM clips WHERE filename = ? AND user_id = ? AND deleted = 0",
        (base, user_id),
    ).fetchone()
    if not row:
        return jsonify({"error": "File tidak ditemukan"}), 404

    return send_from_directory(CLIPS_FOLDER, base)


@app.route("/api/clips/<filename>", methods=["DELETE"])
@login_required
def delete_clip(filename):
    user_id = session["user_id"]
    base = safe_basename(filename)
    if not base:
        return jsonify({"error": "Nama file tidak valid"}), 400

    db = get_db()
    row = db.execute(
        "SELECT id FROM clips WHERE filename = ? AND user_id = ? AND deleted = 0",
        (base, user_id),
    ).fetchone()
    if not row:
        return jsonify({"error": "File tidak ditemukan"}), 404

    clip_path = os.path.join(CLIPS_FOLDER, base)
    if os.path.exists(clip_path):
        os.remove(clip_path)
    db.execute(
        "UPDATE clips SET deleted = 1 WHERE filename = ? AND user_id = ?",
        (base, user_id),
    )
    db.commit()
    return jsonify({"success": True})


@app.route("/api/clips")
@login_required
def list_clips():
    user_id = session["user_id"]
    db = get_db()
    rows = db.execute(
        """
        SELECT c.filename, c.size_bytes, c.created_at
        FROM clips c
        JOIN jobs j ON c.job_id = j.job_id
        WHERE c.user_id = ? AND c.deleted = 0 AND j.status = 'done'
        ORDER BY c.created_at DESC
        """,
        (user_id,),
    ).fetchall()
    clips = [dict(row) for row in rows]
    return jsonify(clips)


@app.route("/api/history")
@login_required
def history():
    user_id = session["user_id"]
    db = get_db()
    rows = db.execute(
        """
        SELECT
            j.job_id,
            j.url,
            j.clip_duration,
            j.overlap,
            j.status,
            j.progress,
            j.message,
            j.created_at,
            j.completed_at,
            c.filename,
            c.clip_index,
            c.start,
            c.end,
            c.duration,
            c.size_bytes
        FROM jobs j
        LEFT JOIN clips c ON j.job_id = c.job_id AND c.deleted = 0
        WHERE j.user_id = ?
        ORDER BY j.created_at DESC, c.clip_index ASC
        """,
        (user_id,),
    ).fetchall()

    grouped = {}
    for row in rows:
        job_id = row["job_id"]
        if job_id not in grouped:
            grouped[job_id] = {
                "job_id": job_id,
                "url": row["url"],
                "clip_duration": row["clip_duration"],
                "overlap": row["overlap"],
                "status": row["status"],
                "progress": row["progress"],
                "message": row["message"],
                "created_at": row["created_at"],
                "completed_at": row["completed_at"],
                "clips": [],
            }
        if row["filename"]:
            grouped[job_id]["clips"].append({
                "filename": row["filename"],
                "index": row["clip_index"],
                "start": row["start"],
                "end": row["end"],
                "duration": row["duration"],
                "size_bytes": row["size_bytes"],
            })

    return jsonify({"history": list(grouped.values())})


@app.route("/api/share-urls", methods=["POST"])
@login_required
def share_urls():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    text = data.get("text", "Lihat klip dari AutoClip").strip()
    if not url:
        return jsonify({"error": "URL wajib diisi"}), 400
    if not (url.startswith("http://") or url.startswith("https://")):
        return jsonify({"error": "URL harus menggunakan http atau https"}), 400

    def enc(s):
        return quote(s, safe="")

    return jsonify({
        "facebook": f"https://www.facebook.com/sharer/sharer.php?u={enc(url)}",
        "twitter": f"https://twitter.com/intent/tweet?url={enc(url)}&text={enc(text)}",
        "whatsapp": f"https://wa.me/?text={enc(text + ' ' + url)}",
        "telegram": f"https://t.me/share/url?url={enc(url)}&text={enc(text)}",
        "linkedin": f"https://www.linkedin.com/sharing/share-offsite/?url={enc(url)}",
        "copy": url,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
