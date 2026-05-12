let currentJobId = null;
let pollInterval = null;

const urlInput = document.getElementById("urlInput");
const processBtn = document.getElementById("processBtn");
const pasteBtn = document.getElementById("pasteBtn");
const thresholdInput = document.getElementById("thresholdInput");
const thresholdValue = document.getElementById("thresholdValue");
const minSceneInput = document.getElementById("minSceneInput");
const minSceneValue = document.getElementById("minSceneValue");

const progressCard = document.getElementById("progressCard");
const progressBar = document.getElementById("progressBar");
const progressMessage = document.getElementById("progressMessage");
const progressPercent = document.getElementById("progressPercent");
const progressClips = document.getElementById("progressClips");

const resultsSection = document.getElementById("resultsSection");
const clipsGrid = document.getElementById("clipsGrid");
const clipCount = document.getElementById("clipCount");
const downloadAllBtn = document.getElementById("downloadAllBtn");
const clearAllBtn = document.getElementById("clearAllBtn");

const errorCard = document.getElementById("errorCard");
const errorMessage = document.getElementById("errorMessage");

// Range inputs live update
thresholdInput.addEventListener("input", () => {
    thresholdValue.textContent = thresholdInput.value;
});

minSceneInput.addEventListener("input", () => {
    minSceneValue.textContent = minSceneInput.value;
});

// Paste button
pasteBtn.addEventListener("click", async () => {
    try {
        const text = await navigator.clipboard.readText();
        urlInput.value = text.trim();
        urlInput.focus();
    } catch {
        urlInput.focus();
    }
});

// Process button
processBtn.addEventListener("click", startProcessing);

urlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") startProcessing();
});

async function startProcessing() {
    const url = urlInput.value.trim();
    if (!url) {
        urlInput.focus();
        urlInput.style.borderColor = "var(--error)";
        setTimeout(() => urlInput.style.borderColor = "", 1500);
        return;
    }

    resetResults();
    processBtn.disabled = true;
    processBtn.innerHTML = '<span class="btn-icon-left">⏳</span> Memproses...';
    progressCard.style.display = "block";
    progressCard.scrollIntoView({ behavior: "smooth", block: "nearest" });

    try {
        const res = await fetch("/api/process", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                url,
                threshold: parseFloat(thresholdInput.value),
                min_scene_len: parseInt(minSceneInput.value),
            }),
        });

        if (!res.ok) {
            const data = await res.json();
            showError(data.error || "Gagal memulai pemrosesan.");
            return;
        }

        const data = await res.json();
        currentJobId = data.job_id;
        startPolling();
    } catch (e) {
        showError("Tidak dapat terhubung ke server. Pastikan server berjalan.");
    }
}

function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(pollStatus, 1500);
}

async function pollStatus() {
    if (!currentJobId) return;
    try {
        const res = await fetch(`/api/status/${currentJobId}`);
        const job = await res.json();
        updateProgress(job);

        if (job.status === "done") {
            clearInterval(pollInterval);
            showResults(job.clips);
        } else if (job.status === "error") {
            clearInterval(pollInterval);
            showError(job.message);
        }
    } catch {
        // silently retry
    }
}

function updateProgress(job) {
    progressBar.style.width = job.progress + "%";
    progressPercent.textContent = job.progress + "%";
    progressMessage.textContent = job.message || "";

    if (job.clips_done && job.total_scenes) {
        progressClips.textContent = `${job.clips_done} / ${job.total_scenes} adegan`;
    } else {
        progressClips.textContent = "";
    }
}

function showResults(clips) {
    progressCard.style.display = "none";
    processBtn.disabled = false;
    processBtn.innerHTML = '<span class="btn-icon-left">⚡</span> Proses Video';

    if (!clips || clips.length === 0) {
        showError("Tidak ada klip yang dihasilkan. Coba turunkan nilai sensitivitas deteksi.");
        return;
    }

    resultsSection.style.display = "block";
    clipCount.textContent = `${clips.length} klip`;
    clipsGrid.innerHTML = "";

    clips.forEach((clip) => {
        const card = createClipCard(clip);
        clipsGrid.appendChild(card);
    });

    resultsSection.scrollIntoView({ behavior: "smooth", block: "nearest" });

    downloadAllBtn.onclick = () => downloadAll(clips);
    clearAllBtn.onclick = () => clearAll(clips);
}

function createClipCard(clip) {
    const card = document.createElement("div");
    card.className = "clip-card";
    card.dataset.filename = clip.filename;

    const duration = formatDuration(clip.duration);
    const size = formatSize(clip.size_bytes);
    const timeRange = `${formatTime(clip.start)} → ${formatTime(clip.end)}`;

    card.innerHTML = `
        <div class="clip-video-wrap">
            <video
                src="/api/clips/${clip.filename}"
                preload="metadata"
                controls
                muted
                playsinline
            ></video>
        </div>
        <div class="clip-info">
            <div class="clip-title">Klip ${clip.index}</div>
            <div class="clip-meta">
                <span>🕐 ${duration}</span>
                <span>📦 ${size}</span>
                <br/>
                <span style="font-size:11px;opacity:0.7">${timeRange}</span>
            </div>
            <div class="clip-actions">
                <a
                    href="/api/clips/${clip.filename}"
                    download="${clip.filename}"
                    class="clip-btn clip-btn-download"
                >⬇️ Unduh</a>
                <button
                    class="clip-btn clip-btn-delete"
                    onclick="deleteClip('${clip.filename}', this)"
                >🗑️ Hapus</button>
            </div>
        </div>
    `;

    return card;
}

async function deleteClip(filename, btn) {
    btn.disabled = true;
    btn.textContent = "...";
    try {
        await fetch(`/api/clips/${filename}`, { method: "DELETE" });
        const card = document.querySelector(`.clip-card[data-filename="${filename}"]`);
        if (card) card.remove();

        const remaining = clipsGrid.querySelectorAll(".clip-card").length;
        clipCount.textContent = `${remaining} klip`;

        if (remaining === 0) {
            resultsSection.style.display = "none";
        }
    } catch {
        btn.disabled = false;
        btn.textContent = "🗑️ Hapus";
    }
}

function downloadAll(clips) {
    clips.forEach((clip, i) => {
        setTimeout(() => {
            const a = document.createElement("a");
            a.href = `/api/clips/${clip.filename}`;
            a.download = clip.filename;
            a.click();
        }, i * 300);
    });
}

async function clearAll(clips) {
    if (!confirm(`Hapus semua ${clips.length} klip? Tindakan ini tidak dapat dibatalkan.`)) return;
    for (const clip of clips) {
        await fetch(`/api/clips/${clip.filename}`, { method: "DELETE" });
    }
    resultsSection.style.display = "none";
    clipsGrid.innerHTML = "";
}

function showError(msg) {
    progressCard.style.display = "none";
    processBtn.disabled = false;
    processBtn.innerHTML = '<span class="btn-icon-left">⚡</span> Proses Video';
    errorCard.style.display = "block";
    errorMessage.textContent = msg;
    errorCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function resetResults() {
    errorCard.style.display = "none";
    resultsSection.style.display = "none";
    clipsGrid.innerHTML = "";
    progressBar.style.width = "0%";
    progressPercent.textContent = "0%";
    progressClips.textContent = "";
    progressMessage.textContent = "Memulai proses...";
}

function resetForm() {
    resetResults();
    processBtn.disabled = false;
    processBtn.innerHTML = '<span class="btn-icon-left">⚡</span> Proses Video';
    urlInput.focus();
}

function formatDuration(sec) {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function formatTime(sec) {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
}

function formatSize(bytes) {
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}
