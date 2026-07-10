let currentJobId = null;
let pollInterval = null;
let currentUser = null;

const urlInput = document.getElementById("urlInput");
const processBtn = document.getElementById("processBtn");
const pasteBtn = document.getElementById("pasteBtn");
const clipDurationInput = document.getElementById("clipDurationInput");
const overlapInput = document.getElementById("overlapInput");
const overlapValue = document.getElementById("overlapValue");

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

const authBar = document.getElementById("authBar");
const userBar = document.getElementById("userBar");
const loginBtn = document.getElementById("loginBtn");
const registerBtn = document.getElementById("registerBtn");
const logoutBtn = document.getElementById("logoutBtn");
const userName = document.getElementById("userName");
const userAvatar = document.getElementById("userAvatar");

const authModal = document.getElementById("authModal");
const authModalClose = document.getElementById("authModalClose");
const modalTabs = document.querySelectorAll(".modal-tab");
const loginForm = document.getElementById("loginForm");
const registerForm = document.getElementById("registerForm");
const loginError = document.getElementById("loginError");
const registerError = document.getElementById("registerError");
const loginUsername = document.getElementById("loginUsername");
const loginPassword = document.getElementById("loginPassword");
const registerUsername = document.getElementById("registerUsername");
const registerPassword = document.getElementById("registerPassword");

const toast = document.getElementById("toast");
const toastMessage = document.getElementById("toastMessage");

// Preset buttons
const presetButtons = document.querySelectorAll(".preset-btn");
presetButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
        presetButtons.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        clipDurationInput.value = btn.dataset.val;
    });
});

clipDurationInput.addEventListener("input", () => {
    presetButtons.forEach((b) => b.classList.remove("active"));
    const val = parseInt(clipDurationInput.value);
    presetButtons.forEach((b) => {
        if (parseInt(b.dataset.val) === val) b.classList.add("active");
    });
});

overlapInput.addEventListener("input", () => {
    overlapValue.textContent = overlapInput.value + " dtk";
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

    const clipDuration = parseFloat(clipDurationInput.value);
    if (!clipDuration || clipDuration < 1) {
        clipDurationInput.focus();
        clipDurationInput.style.borderColor = "var(--error)";
        setTimeout(() => clipDurationInput.style.borderColor = "", 1500);
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
                clip_duration: clipDuration,
                overlap: parseFloat(overlapInput.value),
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
        progressClips.textContent = `${job.clips_done} / ${job.total_scenes} klip`;
    } else {
        progressClips.textContent = "";
    }
}

function showResults(clips) {
    progressCard.style.display = "none";
    processBtn.disabled = false;
    processBtn.innerHTML = '<span class="btn-icon-left">⚡</span> Proses Video';

    if (!clips || clips.length === 0) {
        showError("Tidak ada klip yang dihasilkan. Pastikan URL valid dan coba lagi.");
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
    const shareUrl = `${location.origin}/api/clips/${encodeURIComponent(clip.filename)}`;

    const videoWrap = document.createElement("div");
    videoWrap.className = "clip-video-wrap";
    const video = document.createElement("video");
    video.src = `/api/clips/${encodeURIComponent(clip.filename)}`;
    video.preload = "metadata";
    video.controls = true;
    video.muted = true;
    video.playsInline = true;
    videoWrap.appendChild(video);

    const info = document.createElement("div");
    info.className = "clip-info";

    const title = document.createElement("div");
    title.className = "clip-title";
    title.textContent = `Klip ${clip.index}`;

    const meta = document.createElement("div");
    meta.className = "clip-meta";
    const durSpan = document.createElement("span");
    durSpan.textContent = `🕐 ${duration}`;
    const sizeSpan = document.createElement("span");
    sizeSpan.textContent = `📦 ${size}`;
    const timeSpan = document.createElement("span");
    timeSpan.className = "clip-time";
    timeSpan.textContent = timeRange;
    meta.append(durSpan, sizeSpan, timeSpan);

    const actions = document.createElement("div");
    actions.className = "clip-actions";

    const downloadLink = document.createElement("a");
    downloadLink.href = `/api/clips/${encodeURIComponent(clip.filename)}`;
    downloadLink.download = clip.filename;
    downloadLink.className = "clip-btn clip-btn-download";
    downloadLink.textContent = "⬇️ Unduh";

    const shareBtn = document.createElement("button");
    shareBtn.className = "clip-btn clip-btn-share";
    shareBtn.textContent = "🔗 Bagikan";
    shareBtn.addEventListener("click", () => shareClip(clip.filename, shareUrl));

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "clip-btn clip-btn-delete";
    deleteBtn.textContent = "🗑️ Hapus";
    deleteBtn.addEventListener("click", () => deleteClip(clip.filename, deleteBtn));

    actions.append(downloadLink, shareBtn, deleteBtn);
    info.append(title, meta, actions);
    card.append(videoWrap, info);

    return card;
}

async function shareClip(filename, url) {
    try {
        if (navigator.share) {
            await navigator.share({
                title: `Klip video — ${filename}`,
                text: "Lihat klip hasil pemotongan dari AutoClip",
                url,
            });
        } else {
            await navigator.clipboard.writeText(url);
            showToast("Link klip disalin ke clipboard");
        }
    } catch (e) {
        if (e.name !== "AbortError") {
            showToast("Gagal membagikan klip");
        }
    }
}

async function deleteClip(filename, btn) {
    btn.disabled = true;
    btn.textContent = "...";
    try {
        await fetch(`/api/clips/${filename}`, { method: "DELETE" });
        const card = document.querySelector(`.clip-card[data-filename="${filename}"]`);
        if (card) {
            card.style.transform = "scale(0.92) opacity(0)";
            setTimeout(() => card.remove(), 200);
        }

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

function showToast(message) {
    toastMessage.textContent = message;
    toast.style.display = "block";
    setTimeout(() => {
        toast.style.display = "none";
    }, 2500);
}

// Auth modal
function openAuthModal(tab = "login") {
    authModal.style.display = "flex";
    switchAuthTab(tab);
}

function closeAuthModal() {
    authModal.style.display = "none";
    loginError.classList.remove("visible");
    registerError.classList.remove("visible");
    loginForm.reset();
    registerForm.reset();
}

function switchAuthTab(tab) {
    modalTabs.forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
    if (tab === "login") {
        loginForm.style.display = "block";
        registerForm.style.display = "none";
        loginUsername.focus();
    } else {
        loginForm.style.display = "none";
        registerForm.style.display = "block";
        registerUsername.focus();
    }
}

loginBtn.addEventListener("click", () => openAuthModal("login"));
registerBtn.addEventListener("click", () => openAuthModal("register"));
authModalClose.addEventListener("click", closeAuthModal);
authModal.addEventListener("click", (e) => {
    if (e.target === authModal) closeAuthModal();
});
modalTabs.forEach((tab) => {
    tab.addEventListener("click", () => switchAuthTab(tab.dataset.tab));
});

loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginError.classList.remove("visible");
    const username = loginUsername.value.trim();
    const password = loginPassword.value;

    try {
        const res = await fetch("/api/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
        });
        const data = await res.json();
        if (!res.ok) {
            loginError.textContent = data.error || "Gagal masuk";
            loginError.classList.add("visible");
            return;
        }
        currentUser = data.user;
        updateAuthUI();
        closeAuthModal();
        showToast(`Selamat datang, ${currentUser.username}!`);
    } catch {
        loginError.textContent = "Tidak dapat terhubung ke server";
        loginError.classList.add("visible");
    }
});

registerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    registerError.classList.remove("visible");
    const username = registerUsername.value.trim();
    const password = registerPassword.value;

    try {
        const res = await fetch("/api/register", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
        });
        const data = await res.json();
        if (!res.ok) {
            registerError.textContent = data.error || "Gagal daftar";
            registerError.classList.add("visible");
            return;
        }
        currentUser = data.user;
        updateAuthUI();
        closeAuthModal();
        showToast(`Akun ${currentUser.username} berhasil dibuat!`);
    } catch {
        registerError.textContent = "Tidak dapat terhubung ke server";
        registerError.classList.add("visible");
    }
});

logoutBtn.addEventListener("click", async () => {
    await fetch("/api/logout", { method: "POST" });
    currentUser = null;
    updateAuthUI();
    showToast("Anda telah keluar");
});

function updateAuthUI() {
    if (currentUser) {
        authBar.style.display = "none";
        userBar.style.display = "flex";
        userName.textContent = currentUser.username;
        userAvatar.textContent = currentUser.username.charAt(0).toUpperCase();
    } else {
        authBar.style.display = "flex";
        userBar.style.display = "none";
    }
}

async function checkAuth() {
    try {
        const res = await fetch("/api/me");
        const data = await res.json();
        if (data.user) {
            currentUser = data.user;
            updateAuthUI();
        }
    } catch {
        // ignore
    }
}

checkAuth();
