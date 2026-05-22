// ── Config ──────────────────────────────────────────────────────────────────
const API = 'http://localhost:8000'

// ── State ───────────────────────────────────────────────────────────────────
let urls = [];
let pendingReviews = [];
let runHistory = [];
let totalRuns = 0;
let totalChanges = 0;
let pollInterval = null;

// ── Navigation ──────────────────────────────────────────────────────────────
function navigate(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.getElementById('page-' + page).classList.add('active');
    document.querySelectorAll('.nav-item').forEach(n => {
        if (n.textContent.toLowerCase().includes(page)) n.classList.add('active');
    });
    if (page === 'review') loadPending();
    if (page === 'history') renderHistory();
}

// ── Logging ─────────────────────────────────────────────────────────────────
function log(msg, type = '') {
    const stream = document.getElementById('log-stream');
    const mlog = document.getElementById('monitor-log');
    const line = `<div class="log-line ${type}">${new Date().toLocaleTimeString('en', { hour12: false })} ${msg}</div>`;
    [stream, mlog].forEach(el => {
        if (el) { el.innerHTML += line; el.scrollTop = el.scrollHeight; }
    });
}

function clearLogs() {
    document.getElementById('log-stream').innerHTML = '';
    document.getElementById('monitor-log').innerHTML = '';
}

// ── Toast ────────────────────────────────────────────────────────────────────
function toast(msg, type = 'info') {
    const icons = { success: '✓', error: '✗', info: '◈' };
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `<span>${icons[type]}</span> ${msg}`;
    document.getElementById('toasts').appendChild(el);
    setTimeout(() => el.remove(), 3500);
}

// ── Health Check ─────────────────────────────────────────────────────────────
async function checkHealth() {
    try {
        const res = await fetch(`${API}/health`);
        const data = await res.json();
        document.getElementById('server-status').innerHTML =
            `<span class="status-badge completed">● online</span>`;
        document.getElementById('server-env').textContent = `env: ${data.env}`;
        log('// server health OK', 'success');
    } catch {
        document.getElementById('server-status').innerHTML =
            `<span class="status-badge" style="background:#ff6a6a1a;color:var(--accent2);border:1px solid #ff6a6a30">● offline</span>`;
        log('// server unreachable', 'error');
    }
}

// ── URL Management ───────────────────────────────────────────────────────────
function addUrl() {
    const input = document.getElementById('url-input');
    const url = input.value.trim();
    if (!url || urls.includes(url)) { input.value = ''; return; }
    if (!url.startsWith('http')) { toast('URL must start with http/https', 'error'); return; }
    urls.push(url);
    localStorage.setItem('monitored_urls', JSON.stringify(urls));
    input.value = '';
    renderUrls();
    saveUrlsToServer();
    log(`// added url: ${url}`, 'info');
}

async function saveUrlsToServer() {
    try {
        await fetch(`${API}/urls`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ urls })
        });
    } catch (e) {
        log('// failed to save urls to server', 'error');
    }
}

function removeUrl(url) {
    urls = urls.filter(u => u !== url);
    localStorage.setItem('monitored_urls', JSON.stringify(urls));
    renderUrls();
    saveUrlsToServer();
}

function renderUrls() {
    const container = document.getElementById('url-tags');
    document.getElementById('url-count').textContent = `${urls.length} url${urls.length !== 1 ? 's' : ''}`;
    container.innerHTML = urls.map(url =>
        `<span class="url-tag">
      <span style="color:var(--accent)">◈</span> ${url}
      <span class="url-tag-remove" onclick="removeUrl('${url}')">×</span>
    </span>`
    ).join('');
}

// ── Run Agent ────────────────────────────────────────────────────────────────
async function triggerRun() {
    if (urls.length === 0) {
        toast('Add at least one URL first', 'error');
        navigate('monitor');
        return;
    }

    const btn = document.querySelector('.btn-primary');
    const spinner = document.getElementById('run-spinner');
    const statusBar = document.getElementById('run-status-bar');
    const statusBadge = document.getElementById('run-status-badge');

    btn.disabled = true;
    if (spinner) spinner.style.display = 'inline';
    if (statusBar) statusBar.style.display = 'flex';
    statusBadge.className = 'status-badge running';
    statusBadge.textContent = 'running';

    log('// triggering run...', 'info');
    document.getElementById('run-status-text').textContent = 'Scraping and analyzing...';

    try {
        const res = await fetch(`${API}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ urls })
        });
        const data = await res.json();

        totalRuns++;
        document.getElementById('stat-runs').textContent = totalRuns;
        document.getElementById('run-thread-id').textContent = `thread: ${data.thread_id?.slice(0, 8)}...`;

        if (data.status === 'paused_for_review') {
            totalChanges += data.deltas?.length || 0;
            document.getElementById('stat-changes').textContent = totalChanges;
            statusBadge.className = 'status-badge paused';
            statusBadge.textContent = 'paused — review needed';
            log(`// ${data.deltas?.length} change(s) detected — review required`, 'warn');
            toast(`${data.deltas?.length} change(s) detected! Go to Review.`, 'info');
            runHistory.push({ thread_id: data.thread_id, status: 'paused', urls, deltas: data.deltas?.length, time: new Date() });
            setTimeout(loadPending, 2000);
        } else {
            statusBadge.className = 'status-badge completed';
            statusBadge.textContent = 'completed — no changes';
            log('// no significant changes detected', 'success');
            toast('Run complete — no changes found', 'success');
            runHistory.push({ thread_id: data.thread_id, status: 'no_changes', urls, deltas: 0, time: new Date() });
        }

    } catch (e) {
        log(`// run failed: ${e.message}`, 'error');
        toast('Run failed — is FastAPI running?', 'error');
        statusBadge.className = 'status-badge idle';
        statusBadge.textContent = 'failed';
    }

    btn.disabled = false;
    if (spinner) spinner.style.display = 'none';
}

// ── Load Pending Reviews ──────────────────────────────────────────────────────
async function loadPending() {
    try {
        const res = await fetch(`${API}/pending`);
        const data = await res.json();
        pendingReviews = data.pending_reviews || [];

        const count = pendingReviews.length;
        document.getElementById('stat-pending').textContent = count;

        const badge = document.getElementById('review-badge');
        if (count > 0) {
            badge.style.display = 'inline';
            badge.textContent = count;
        } else {
            badge.style.display = 'none';
        }

        renderReviewCards();
    } catch (e) {
        log('// failed to load pending reviews', 'error');
    }
}

// ── Render Review Cards ───────────────────────────────────────────────────────
function renderReviewCards() {
    const container = document.getElementById('review-cards');
    const empty = document.getElementById('review-empty');

    if (pendingReviews.length === 0) {
        empty.style.display = 'block';
        container.innerHTML = '';
        return;
    }

    empty.style.display = 'none';
    container.innerHTML = pendingReviews.map(review => `
    <div class="section" id="review-${review.thread_id}">
      <div class="section-header">
        <span class="section-title">Pending Review</span>
        <span class="status-badge paused">● awaiting decision</span>
      </div>
      <div class="section-body">
        ${review.deltas.map((delta, i) => `
          <div class="delta-card ${delta.confidence}">
            <div class="delta-header">
              <a href="${delta.url}" target="_blank" class="delta-url">⊕ ${delta.url}</a>
              <span class="confidence-badge ${delta.confidence}">${delta.confidence.toUpperCase()}</span>
            </div>
            <div class="delta-analysis">${delta.analysis}</div>
          </div>
        `).join('')}
        <div class="divider"></div>
        <div class="delta-actions">
          <button class="btn btn-success" onclick="submitReview('${review.thread_id}', '${review.resume_url}', true)">
            ✓ Approve — Send to Slack
          </button>
          <button class="btn btn-danger" onclick="submitReview('${review.thread_id}', '${review.resume_url}', false)">
            ✗ Reject
          </button>
          <span class="thread-id">id: ${review.thread_id?.slice(0, 12)}...</span>
        </div>
      </div>
    </div>
  `).join('');
}

// ── Submit Review ─────────────────────────────────────────────────────────────
async function submitReview(threadId, resumeUrl, approved) {
    const card = document.getElementById(`review-${threadId}`);
    const btns = card.querySelectorAll('button');
    btns.forEach(b => b.disabled = true);

    log(`// submitting review: ${approved ? 'APPROVED' : 'REJECTED'} for ${threadId.slice(0, 8)}...`, approved ? 'success' : 'warn');

    try {
        const res = await fetch(`${API}/complete-review`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ thread_id: threadId, approved, resume_url: resumeUrl })
        });
        const data = await res.json();

        if (approved) {
            toast('✓ Approved — Slack notification sent via n8n', 'success');
            log('// ✓ approved — n8n sending Slack alert', 'success');
            card.style.borderColor = '#6affa030';
            card.innerHTML = `
        <div class="section-header">
          <span class="section-title">Review Complete</span>
          <span class="status-badge completed">● approved</span>
        </div>
        <div class="section-body">
          <div style="font-family:var(--mono); font-size:12px; color:var(--success)">
            ✓ Changes approved — Slack notification sent via n8n
          </div>
        </div>`;
        } else {
            toast('✗ Rejected — no action taken', 'info');
            log('// ✗ rejected — no action taken', 'warn');
            card.remove();
        }

        pendingReviews = pendingReviews.filter(r => r.thread_id !== threadId);
        const count = pendingReviews.length;
        document.getElementById('stat-pending').textContent = count;
        const badge = document.getElementById('review-badge');
        badge.style.display = count > 0 ? 'inline' : 'none';
        if (count > 0) badge.textContent = count;

        for (const run of runHistory) {
            if (run.thread_id === threadId) {
                run.status = approved ? 'approved' : 'rejected';
            }
        }

    } catch (e) {
        log(`// review submission failed: ${e.message}`, 'error');
        toast('Submission failed', 'error');
        btns.forEach(b => b.disabled = false);
    }
}

// ── History ───────────────────────────────────────────────────────────────────
function renderHistory() {
    const body = document.getElementById('history-body');
    if (runHistory.length === 0) {
        body.innerHTML = `<div class="empty" style="padding:30px"><div class="empty-icon">≡</div><div>No runs yet this session</div></div>`;
        return;
    }

    body.innerHTML = `<table class="table">
    <thead>
      <tr>
        <th>Thread ID</th>
        <th>Time</th>
        <th>URLs</th>
        <th>Changes</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>
      ${runHistory.map(r => `
        <tr>
          <td>${r.thread_id?.slice(0, 12)}...</td>
          <td>${r.time.toLocaleTimeString()}</td>
          <td>${r.urls.length} url(s)</td>
          <td>${r.deltas}</td>
          <td><span class="status-badge ${r.status === 'approved' ? 'completed' : r.status === 'rejected' ? '' : r.status === 'no_changes' ? 'completed' : 'paused'}">${r.status}</span></td>
        </tr>
      `).join('')}
    </tbody>
  </table>`;
}

// ── Init ──────────────────────────────────────────────────────────────────────
checkHealth();
loadPending();
pollInterval = setInterval(loadPending, 30000);


// Load saved URLs from localStorage
const saved = localStorage.getItem('monitored_urls');
urls = saved ? JSON.parse(saved) : [];
renderUrls();
