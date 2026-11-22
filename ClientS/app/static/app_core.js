const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
const wsUrl = `${wsProtocol}://${window.location.host}/ws/epc-live`;
let scanActive = false;
let scanContext = null; // 'masuk' or 'keluar'
let scannedEpcs = new Set();
let masterLinen = [];
let settingScanActive = false;
let settingScannedEpcs = new Set();
let settingCloudItems = new Map();
let settingPackage = null;
let settingSaving = false;
let afkirScanActive = false;
let afkirScannedEpcs = new Map();
let refreshDashboardGlobal = null;

let isServerOffline = false;
let checkHealthInterval = null;
let reconnectOverlayEl = null;
let activeSocket = null;
let heartbeatInterval = null;
let wsConnected = false; // true only after WS onopen fires at least once

function injectReconnectStyles() {
  if (document.getElementById('sys-status-styles')) return;
  const style = document.createElement('style');
  style.id = 'sys-status-styles';
  style.textContent = `
    .sys-status-panel {
      position: fixed !important;
      top: 0 !important;
      left: 0 !important;
      width: 100vw !important;
      height: 100vh !important;
      z-index: 999999 !important;
      display: none !important;
      align-items: center !important;
      justify-content: center !important;
      background: rgba(4, 10, 20, 0.88) !important;
      backdrop-filter: blur(12px) !important;
      -webkit-backdrop-filter: blur(12px) !important;
    }
    .sys-status-panel.active {
      display: flex !important;
    }
    .sys-status-card {
      display: flex !important;
      flex-direction: column !important;
      align-items: center !important;
      text-align: center !important;
      padding: 36px 42px !important;
      max-width: 440px !important;
      width: 90% !important;
      border: 1px solid rgba(103, 154, 198, 0.35) !important;
      border-radius: 24px !important;
      background: linear-gradient(145deg, #10223c, #0a172a) !important;
      box-shadow: 0 30px 70px rgba(0, 0, 0, 0.6) !important;
      font-family: "Inter", "Segoe UI", Roboto, sans-serif !important;
      box-sizing: border-box !important;
    }
    .reconnect-spinner-wrap {
      position: relative !important;
      width: 64px !important;
      height: 64px !important;
      margin-bottom: 20px !important;
    }
    .reconnect-spinner {
      width: 64px !important;
      height: 64px !important;
      border: 4px solid rgba(22, 185, 223, 0.18) !important;
      border-top-color: #16b9df !important;
      border-radius: 50% !important;
      animation: reconnect-spin 1s linear infinite !important;
      box-sizing: border-box !important;
    }
    @keyframes reconnect-spin {
      to { transform: rotate(360deg); }
    }
    .reconnect-pulse-dot {
      position: absolute !important;
      top: 50% !important;
      left: 50% !important;
      transform: translate(-50%, -50%) !important;
      width: 14px !important;
      height: 14px !important;
      border-radius: 50% !important;
      background: #ed5968 !important;
      box-shadow: 0 0 10px rgba(237, 89, 104, 0.8) !important;
      animation: reconnect-pulse-red 1.5s ease-in-out infinite !important;
    }
    @keyframes reconnect-pulse-red {
      0% { transform: translate(-50%, -50%) scale(0.85); box-shadow: 0 0 0 0 rgba(237, 89, 104, 0.7); }
      70% { transform: translate(-50%, -50%) scale(1.1); box-shadow: 0 0 0 12px rgba(237, 89, 104, 0); }
      100% { transform: translate(-50%, -50%) scale(0.85); box-shadow: 0 0 0 0 rgba(237, 89, 104, 0); }
    }
    .sys-status-card h3 {
      margin: 0 0 10px 0 !important;
      font-size: 1.3rem !important;
      color: #ffffff !important;
      font-weight: 700 !important;
    }
    .sys-status-card p {
      margin: 0 0 18px 0 !important;
      color: #91a3ba !important;
      font-size: 0.92rem !important;
      line-height: 1.5 !important;
    }
    .reconnect-status-badge {
      display: inline-flex !important;
      align-items: center !important;
      gap: 8px !important;
      padding: 6px 14px !important;
      border-radius: 20px !important;
      background: rgba(237, 89, 104, 0.15) !important;
      border: 1px solid rgba(237, 89, 104, 0.3) !important;
      color: #ff7884 !important;
      font-size: 0.78rem !important;
      font-weight: 700 !important;
    }
  `;
  document.head.appendChild(style);
}

function createReconnectOverlay() {
  injectReconnectStyles();
  if (document.getElementById('sys-status-panel')) return;
  const overlay = document.createElement('div');
  overlay.id = 'sys-status-panel';
  overlay.className = 'sys-status-panel';
  overlay.innerHTML = `
    <div class="sys-status-card">
      <div class="reconnect-spinner-wrap">
        <div class="reconnect-spinner"></div>
        <div class="reconnect-pulse-dot"></div>
      </div>
      <h3>Koneksi Server Terputus</h3>
      <p>Mencoba menghubungkan ulang ke server...</p>
      <div class="reconnect-status-badge">
        <span class="led-dot" style="background:#ed5968;"></span>
        <span id="reconnect-status-text">Menghubungkan...</span>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  reconnectOverlayEl = overlay;
}

function showReconnectOverlay() {
  createReconnectOverlay();
  const overlay = document.getElementById('sys-status-panel');
  if (overlay) overlay.classList.add('active');

  if (!isServerOffline) {
    isServerOffline = true;
    notify('Koneksi terputus! Server mati.', 'error');
  }
  startServerHealthCheck();
}

function hideReconnectOverlay() {
  if (isServerOffline) {
    isServerOffline = false;
    const overlay = document.getElementById('sys-status-panel');
    if (overlay) overlay.classList.remove('active');
    notify('Koneksi server kembali terhubung!', 'success');

    initWebSocket();
    loadMasterData().catch(() => { });
    loadHistory().catch(() => { });
    if (typeof refreshDashboardGlobal === 'function') refreshDashboardGlobal();
  }
}

async function pingServer() {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 1500);
    const res = await fetch('/api/health', { method: 'GET', cache: 'no-store', signal: controller.signal });
    clearTimeout(timeoutId);
    return res.ok;
  } catch (_) {
    return false;
  }
}

let reconnectAttempts = 0;

function startServerHealthCheck() {
  if (checkHealthInterval) clearInterval(checkHealthInterval);
  reconnectAttempts = 0;
  checkHealthInterval = setInterval(async () => {
    reconnectAttempts++;
    const statusText = document.getElementById('reconnect-status-text');
    if (statusText) {
      statusText.textContent = `Mencoba menghubungkan ulang... (${reconnectAttempts}s)`;
    }
    const online = await pingServer();
    if (online) {
      clearInterval(checkHealthInterval);
      checkHealthInterval = null;
      reconnectAttempts = 0;
      hideReconnectOverlay();
    }
  }, 1000);
}

function startHeartbeatMonitor() {
  if (heartbeatInterval) clearInterval(heartbeatInterval);
  heartbeatInterval = setInterval(async () => {
    // Only trigger overlay from heartbeat if WS was previously connected and is now gone
    if (!isServerOffline && wsConnected) {
      const online = await pingServer();
      if (!online) {
        showReconnectOverlay();
      }
    }
  }, 5000);
}

async function requestJson(url, options = {}) {
  try {
    const defaultHeaders = {
      'Content-Type': 'application/json',
      'X-ClientS-Request': '1',
    };
    const headers = {
      ...defaultHeaders,
      ...(options.headers || {}),
    };
    const response = await fetch(url, {
      cache: 'no-store',
      ...options,
      headers,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || 'Request gagal');
    }
    if (isServerOffline) {
      hideReconnectOverlay();
    }
    return data;
  } catch (err) {
    if (err instanceof TypeError || err.name === 'AbortError' || err.message?.includes('fetch') || err.message?.includes('Failed to fetch')) {
      showReconnectOverlay();
    }
    throw err;
  }
}

function updateConnectionStatus() {
  const el = document.getElementById('connection-status');
  if (!el) return;
  const online = typeof navigator !== 'undefined' ? navigator.onLine : true;
  el.textContent = `Koneksi: ${online ? 'online' : 'offline'}`;
  el.className = online ? 'status-success' : 'status-warning';
}

function setStatusMessage(message, kind = 'info') {
  notify(message, kind);
}

function notificationStack() {
  let stack = document.querySelector('.app-notification-stack');
  if (!stack) {
    stack = document.createElement('div');
    stack.className = 'app-notification-stack';
    document.body.appendChild(stack);
  }
  return stack;
}

function notify(message, kind = 'info', duration = 4500) {
  const stack = notificationStack();
  const item = document.createElement('div');
  const validKind = (kind === 'danger') ? 'error' : (kind || 'info');
  item.className = `app-notification ${validKind}`;

  const content = document.createElement('div');
  content.className = 'notif-content';
  content.textContent = message;

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'notif-close-btn';
  closeBtn.innerHTML = '&times;';
  closeBtn.setAttribute('aria-label', 'Tutup');
  closeBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    item.style.opacity = '0';
    item.style.transform = 'translateX(20px)';
    setTimeout(() => item.remove(), 250);
  });

  item.appendChild(content);
  item.appendChild(closeBtn);
  stack.appendChild(item);

  const timer = setTimeout(() => {
    item.style.opacity = '0';
    item.style.transform = 'translateX(20px)';
    setTimeout(() => item.remove(), 250);
  }, duration);

  item.addEventListener('mouseenter', () => clearTimeout(timer));
}

window.notify = notify;

// Override native window.alert to always display top-right toast notification
window.alert = function(msg) {
  const text = String(msg || '');
  let kind = 'info';
  const lower = text.toLowerCase();
  if (lower.includes('berhasil') || lower.includes('success')) {
    kind = 'success';
  } else if (lower.includes('gagal') || lower.includes('error') || lower.includes('kesalahan') || lower.includes('tidak cocok') || lower.includes('tidak 100% cocok') || lower.includes('unexpected') || lower.includes('ditolak')) {
    kind = 'error';
  } else if (lower.includes('peringatan') || lower.includes('warning') || lower.includes('perhatian') || lower.includes('terlebih dahulu') || lower.includes('wajib') || lower.includes('tertahan')) {
    kind = 'warning';
  }
  const cleanMsg = text.replace(/^[✅⚠️❌ℹ️]\s*/, '');
  notify(cleanMsg, kind, kind === 'error' ? 6500 : 4500);
};

function showConfirm(message) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'app-confirmation-overlay';
    const item = document.createElement('div');
    item.className = 'app-confirmation';
    const text = document.createElement('div');
    text.textContent = message;
    const actions = document.createElement('div');
    actions.className = 'app-confirmation-actions';
    const cancel = document.createElement('button');
    cancel.className = 'secondary'; cancel.textContent = 'Batal';
    const approve = document.createElement('button');
    approve.textContent = 'Lanjutkan';
    const finish = value => { overlay.remove(); resolve(value); };
    cancel.addEventListener('click', () => finish(false));
    approve.addEventListener('click', () => finish(true));
    actions.append(cancel, approve); item.append(text, actions);
    overlay.appendChild(item);
    document.body.appendChild(overlay);
  });
}

function formatCategoryBadge(kategori) {
  if (!kategori) return '<span class="cat-badge cat-lainnya">Lainnya</span>';
  const kat = String(kategori).toLowerCase();
  if (kat.includes('sprei')) return `<span class="cat-badge cat-sprei">${kategori}</span>`;
  if (kat.includes('selimut')) return `<span class="cat-badge cat-selimut">${kategori}</span>`;
  if (kat.includes('handuk')) return `<span class="cat-badge cat-handuk">${kategori}</span>`;
  if (kat.includes('sarung')) return `<span class="cat-badge cat-sarung">${kategori}</span>`;
  if (kat.includes('bed') || kat.includes('cover')) return `<span class="cat-badge cat-bedcover">${kategori}</span>`;
  return `<span class="cat-badge cat-lainnya">${kategori}</span>`;
}

let linenFilterInitialized = false;

function initLinenFilterOptions(ruanganList) {
  const selectKat = document.getElementById('filter-linen-kategori');
  const selectLokasi = document.getElementById('filter-linen-lokasi');
  if (!selectKat || !selectLokasi) return;

  const currentKat = selectKat.value;
  const currentLokasi = selectLokasi.value;

  // Extract unique categories from masterLinen
  const categories = Array.from(new Set(masterLinen.map(l => l.kategori).filter(Boolean))).sort();
  
  // Custom dropdown support for Kategori
  const ddKatOpts = document.getElementById('dropdown-filter-linen-kategori-options');
  const ddKatSelected = document.querySelector('#dropdown-filter-linen-kategori .dropdown-selected');
  if (ddKatOpts) {
    ddKatOpts.innerHTML = '<div class="dropdown-option ' + (!currentKat ? 'selected' : '') + '" data-value="">Semua Kategori</div>' +
      categories.map(k => `<div class="dropdown-option ${currentKat === k ? 'selected' : ''}" data-value="${k}">${k}</div>`).join('');
    if (ddKatSelected) {
      ddKatSelected.textContent = (currentKat && categories.includes(currentKat)) ? currentKat : 'Semua Kategori';
    }
  } else if (selectKat.tagName === 'SELECT') {
    selectKat.innerHTML = '<option value="">Semua Kategori</option>' +
      categories.map(k => `<option value="${k}">${k}</option>`).join('');
    if (currentKat && categories.includes(currentKat)) {
      selectKat.value = currentKat;
    }
  }

  // Extract unique rooms / locations
  const activeRooms = (ruanganList || []).filter(r => r.is_active !== false).map(r => r.nama_ruangan);
  const extraLocations = Array.from(new Set(masterLinen.map(l => l.lokasi).filter(Boolean)));
  const allLocations = Array.from(new Set(['Storage', 'R. Laundry', ...activeRooms, ...extraLocations])).sort();

  // Custom dropdown support for Lokasi
  const ddLokOpts = document.getElementById('dropdown-filter-linen-lokasi-options');
  const ddLokSelected = document.querySelector('#dropdown-filter-linen-lokasi .dropdown-selected');
  if (ddLokOpts) {
    ddLokOpts.innerHTML = '<div class="dropdown-option ' + (!currentLokasi ? 'selected' : '') + '" data-value="">Semua Lokasi</div>' +
      allLocations.map(loc => `<div class="dropdown-option ${currentLokasi === loc ? 'selected' : ''}" data-value="${loc}">${loc}</div>`).join('');
    if (ddLokSelected) {
      ddLokSelected.textContent = (currentLokasi && allLocations.includes(currentLokasi)) ? currentLokasi : 'Semua Lokasi';
    }
  } else if (selectLokasi.tagName === 'SELECT') {
    selectLokasi.innerHTML = '<option value="">Semua Lokasi</option>' +
      allLocations.map(loc => `<option value="${loc}">${loc}</option>`).join('');
    if (currentLokasi && allLocations.includes(currentLokasi)) {
      selectLokasi.value = currentLokasi;
    }
  }

  if (!linenFilterInitialized) {
    linenFilterInitialized = true;
    document.getElementById('filter-linen-kategori')?.addEventListener('change', applyLinenFilters);
    document.getElementById('filter-linen-nama')?.addEventListener('input', applyLinenFilters);
    document.getElementById('filter-linen-lokasi')?.addEventListener('change', applyLinenFilters);
    document.getElementById('filter-linen-cuci')?.addEventListener('change', applyLinenFilters);
    document.getElementById('btn-reset-linen-filter')?.addEventListener('click', () => {
      const elKat = document.getElementById('filter-linen-kategori');
      if (elKat) elKat.value = '';
      const inputNama = document.getElementById('filter-linen-nama');
      if (inputNama) inputNama.value = '';
      const elLok = document.getElementById('filter-linen-lokasi');
      if (elLok) elLok.value = '';
      const selectCuci = document.getElementById('filter-linen-cuci');
      if (selectCuci) selectCuci.value = '';

      // Reset custom dropdowns UI
      const resetCustomDD = (id, defaultLabel) => {
        const dd = document.getElementById(id);
        if (dd) {
          const sel = dd.querySelector('.dropdown-selected');
          if (sel) sel.textContent = defaultLabel;
          dd.querySelectorAll('.dropdown-option').forEach(o => {
            o.classList.toggle('selected', o.getAttribute('data-value') === '');
          });
        }
      };
      resetCustomDD('dropdown-filter-linen-kategori', 'Semua Kategori');
      resetCustomDD('dropdown-filter-linen-lokasi', 'Semua Lokasi');
      resetCustomDD('dropdown-filter-linen-cuci', 'Semua Siklus Cuci');

      applyLinenFilters();
    });
  }
}

function applyLinenFilters() {
  const selectKat = document.getElementById('filter-linen-kategori');
  const inputNama = document.getElementById('filter-linen-nama');
  const selectLokasi = document.getElementById('filter-linen-lokasi');
  const selectCuci = document.getElementById('filter-linen-cuci');

  const selectedKat = selectKat ? selectKat.value : '';
  const searchNama = inputNama ? inputNama.value.trim().toLowerCase() : '';
  const selectedLokasi = selectLokasi ? selectLokasi.value : '';
  const selectedCuci = selectCuci ? selectCuci.value : '';

  const filtered = masterLinen.filter(item => {
    // 1. Kategori
    if (selectedKat && item.kategori !== selectedKat) return false;

    // 2. Nama / EPC
    if (searchNama) {
      const namaMatch = (item.nama_linen || '').toLowerCase().includes(searchNama);
      const epcMatch = (item.epc || '').toLowerCase().includes(searchNama);
      if (!namaMatch && !epcMatch) return false;
    }

    // 3. Lokasi
    if (selectedLokasi && (item.lokasi || '') !== selectedLokasi) return false;

    // 4. Jumlah Cuci
    const cuci = Number(item.total_cuci || 0);
    if (selectedCuci === '0-14' && !(cuci < 15)) return false;
    if (selectedCuci === '15-49' && !(cuci >= 15 && cuci <= 49)) return false;
    if (selectedCuci === '50-99' && !(cuci >= 50 && cuci <= 99)) return false;
    if (selectedCuci === '100+' && !(cuci >= 100)) return false;

    return true;
  });

  // Update Counters
  const cntTotal = document.getElementById('counter-filter-total');
  const cntCuci = document.getElementById('counter-filter-cuci');
  const cntPakai = document.getElementById('counter-filter-pakai');
  const cntAfkir = document.getElementById('counter-filter-afkir');

  const cuciList = filtered.filter(item => item.status === 'dicuci' || item.lokasi === 'R. Laundry');
  const pakaiList = filtered.filter(item => item.status === 'dipakai' || (item.lokasi !== 'R. Laundry' && item.lokasi !== 'Storage' && item.lokasi !== 'Gudang / Storage' && item.status !== 'afkir'));
  const afkirList = filtered.filter(item => item.status === 'afkir' || item.status === 'dimusnahkan');

  if (cntTotal) cntTotal.textContent = filtered.length;
  if (cntCuci) cntCuci.textContent = cuciList.length;
  if (cntPakai) cntPakai.textContent = pakaiList.length;
  if (cntAfkir) cntAfkir.textContent = afkirList.length;

  // 1. Data Semua Linen Table
  const linenAllBody = document.getElementById('linen-all-body') || document.getElementById('linen-data-body');
  if (linenAllBody) {
    let count = 1;
    linenAllBody.innerHTML = filtered.length
      ? filtered.map((item) => `<tr><td>${count++}</td><td>${item.epc}</td><td>${formatCategoryBadge(item.kategori)}</td><td>${item.nama_linen}</td><td>${item.lokasi}</td><td>${item.total_cuci}</td></tr>`).join('')
      : '<tr><td colspan="6" style="text-align:center; color:var(--text-sub); height: 48px;">Tidak ada data linen yang cocok dengan filter.</td></tr>';
  }

  // 2. Linen Dicuci Table
  const linenDicuciBody = document.getElementById('linen-dicuci-body');
  if (linenDicuciBody) {
    let count = 1;
    linenDicuciBody.innerHTML = cuciList.length
      ? cuciList.map((item) => `<tr><td>${count++}</td><td>${item.epc}</td><td>${formatCategoryBadge(item.kategori)}</td><td>${item.nama_linen}</td><td>${item.lokasi}</td><td>${item.total_cuci}</td></tr>`).join('')
      : '<tr><td colspan="6" style="text-align:center; color:var(--text-sub); height: 48px;">Tidak ada linen dicuci yang cocok dengan filter.</td></tr>';
  }

  // 3. Linen Dipakai Table
  const linenDipakaiBody = document.getElementById('linen-dipakai-body');
  if (linenDipakaiBody) {
    let count = 1;
    linenDipakaiBody.innerHTML = pakaiList.length
      ? pakaiList.map((item) => `<tr><td>${count++}</td><td>${item.epc}</td><td>${formatCategoryBadge(item.kategori)}</td><td>${item.nama_linen}</td><td>${item.lokasi}</td></tr>`).join('')
      : '<tr><td colspan="5" style="text-align:center; color:var(--text-sub); height: 48px;">Tidak ada linen dipakai yang cocok dengan filter.</td></tr>';
  }

  // 4. Linen Afkir Table
  const linenAfkirBody = document.getElementById('linen-afkir-body');
  if (linenAfkirBody) {
    let count = 1;
    linenAfkirBody.innerHTML = afkirList.length
      ? afkirList.map((item) => `
        <tr>
          <td>${count++}</td>
          <td style="font-family: monospace; color: #fff;">${item.epc}</td>
          <td>${formatCategoryBadge(item.kategori)}</td>
          <td>${item.nama_linen}</td>
          <td>${item.lokasi || '-'}</td>
          <td>${item.total_cuci || 0}</td>
          <td><span class="badge" style="background: rgba(239,68,68,0.15); color: #ef4444; border: 1px solid rgba(239,68,68,0.3); font-size: 0.75rem; font-weight: 700;">AFKIR</span></td>
        </tr>
      `).join('')
      : '<tr><td colspan="7" style="text-align:center; color:var(--text-sub); height: 48px;">Tidak ada linen afkir yang cocok dengan filter.</td></tr>';
  }

  // Update Pagination Info
  const pAll = document.querySelector('#card-all .pagination-info');
  if (pAll) pAll.textContent = `Menampilkan ${filtered.length} dari ${masterLinen.length} data`;
  const pCuci = document.querySelector('#card-dicuci .pagination-info');
  if (pCuci) pCuci.textContent = `Menampilkan ${cuciList.length} dari ${masterLinen.filter(item => item.status === 'dicuci' || item.lokasi === 'R. Laundry').length} data`;
  const pPakai = document.querySelector('#card-dipakai .pagination-info');
  if (pPakai) pPakai.textContent = `Menampilkan ${pakaiList.length} dari ${masterLinen.filter(item => item.status === 'dipakai' || (item.lokasi !== 'R. Laundry' && item.lokasi !== 'Storage' && item.lokasi !== 'Gudang / Storage' && item.status !== 'afkir')).length} data`;
  const pAfkir = document.getElementById('pagination-afkir-info');
  if (pAfkir) pAfkir.textContent = `Menampilkan ${afkirList.length} dari ${masterLinen.filter(item => item.status === 'afkir' || item.status === 'dimusnahkan').length} data afkir`;
}

async function loadMasterData() {
  masterLinen = await requestJson('/api/master/linen').catch(() => []);
  const ruangan = await requestJson('/api/master/ruangan').catch(() => []);

  // Inisialisasi opsi filter dinamis & terapkan filter ke tabel linen
  initLinenFilterOptions(ruangan);
  applyLinenFilters();

  // Fill Data Ruangan Table
  const ruanganBody = document.getElementById('ruangan-table-body');
  if (ruanganBody) {
    let count = 1;
    ruanganBody.innerHTML = ruangan.length
      ? ruangan.map((item) => {
          const isActive = item.is_active !== false && item.is_active !== 0 && item.is_active !== '0';
          const statusBadge = isActive
            ? '<span class="badge" style="background:rgba(0,208,132,0.15);color:#00D084;border:none;padding:4px 12px;border-radius:6px;font-weight:600;display:inline-flex;align-items:center;gap:6px;"><span style="width:6px;height:6px;border-radius:50%;background:#00D084;display:inline-block;"></span>Aktif</span>'
            : '<span class="badge" style="background:rgba(239,68,68,0.15);color:#ef4444;border:none;padding:4px 12px;border-radius:6px;font-weight:600;display:inline-flex;align-items:center;gap:6px;"><span style="width:6px;height:6px;border-radius:50%;background:#ef4444;display:inline-block;"></span>Nonaktif</span>';

          const toggleStatusBtn = isActive
            ? `<button style="background:#d97706; border:none; border-radius:6px; width:32px; height:32px; display:flex; align-items:center; justify-content:center; cursor:pointer;" data-action="toggle-status-ruangan" data-id="${item.id}" data-active="false" data-name="${encodeURIComponent(item.nama_ruangan)}" title="Nonaktifkan Ruangan (sembunyikan dari transaksi)"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line></svg></button>`
            : `<button style="background:#059669; border:none; border-radius:6px; width:32px; height:32px; display:flex; align-items:center; justify-content:center; cursor:pointer;" data-action="toggle-status-ruangan" data-id="${item.id}" data-active="true" data-name="${encodeURIComponent(item.nama_ruangan)}" title="Aktifkan Ruangan (tampilkan di transaksi)"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg></button>`;

          return `<tr style="${isActive ? '' : 'opacity:0.75;'}">
            <td>${count++}</td>
            <td><strong>${item.kode_ruangan}</strong></td>
            <td>${item.nama_ruangan}</td>
            <td>${item.keterangan || '-'}</td>
            <td>${statusBadge}</td>
            <td>
              <div style="display:flex; gap:8px;">
                <button style="background:#0e7490; border:none; border-radius:6px; width:32px; height:32px; display:flex; align-items:center; justify-content:center; cursor:pointer;" data-action="edit-ruangan" data-id="${item.id}" title="Edit Ruangan">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                </button>
                ${toggleStatusBtn}
                <button style="background:#be123c; border:none; border-radius:6px; width:32px; height:32px; display:flex; align-items:center; justify-content:center; cursor:pointer;" data-action="delete-ruangan" data-id="${item.id}" data-name="${encodeURIComponent(item.nama_ruangan)}" title="Hapus Ruangan">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                </button>
              </div>
            </td>
          </tr>`;
        }).join('')
      : '<tr><td colspan="6" style="text-align:center; color:var(--text-sub);">Belum ada data ruangan.</td></tr>';

    // Real-time table search binding
    const searchInput = document.getElementById('ruangan-search');
    if (searchInput && !searchInput.dataset.bound) {
      searchInput.dataset.bound = '1';
      searchInput.addEventListener('input', (e) => {
        const term = e.target.value.toLowerCase().trim();
        const rows = document.querySelectorAll('#ruangan-table-body tr');
        rows.forEach(row => {
          const text = row.textContent.toLowerCase();
          row.style.display = text.includes(term) ? '' : 'none';
        });
      });
    }
  }

  // Fill Ruangan Select in Laundry Linen Keluar (Hanya Ruangan Aktif)
  const selectRuanganInput = document.getElementById('select-ruangan-keluar');
  const dropdownRuanganOpts = document.getElementById('dropdown-ruangan-options');
  if (selectRuanganInput && dropdownRuanganOpts) {
    const activeRooms = ruangan.filter(r => r.is_active !== false && r.is_active !== 0 && r.is_active !== '0');
    dropdownRuanganOpts.innerHTML = '<div class="dropdown-option selected" data-value="">-- Pilih Ruangan --</div>' +
      activeRooms.map(r => `<div class="dropdown-option" data-value="${r.nama_ruangan}">${r.nama_ruangan}</div>`).join('');
  }
}

function renderHistoryTable(items) {
  // Logic for Dashboard history
  const tbody = document.getElementById('recent-history-body');
  if (!tbody) return;
  const recent = items.slice(0, 5);
  tbody.innerHTML = recent.length
    ? recent.map((item) => {
        const isMasuk = item.event_type.toLowerCase().includes('masuk') || item.event_type.toLowerCase() === 'verifikasi' || item.event_type.toLowerCase() === 'penerimaan';
        const iconColor = isMasuk ? '#00D084' : '#3b82f6';
        const iconBg = isMasuk ? 'rgba(0,208,132,0.1)' : 'rgba(59,130,246,0.1)';
        const icon = isMasuk
          ? '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="' + iconColor + '" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>'
          : '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="' + iconColor + '" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>';

        let dateStr = '-';
        if (item.created_at) {
          const d = new Date(item.created_at);
          dateStr = d.toLocaleString('id-ID', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short' });
        }

        return '<div class="activity-item">'
          + '<div style="background: ' + iconBg + '; padding: 10px; border-radius: 50%; display: flex;">' + icon + '</div>'
          + '<div style="display: flex; flex-direction: column; gap: 4px;">'
          + '<span style="color: #fff; font-weight: 600; font-size: 0.9rem; text-transform: capitalize;">' + item.event_type + '</span>'
          + '<span style="color: #8297b0; font-size: 0.75rem;">' + (item.lokasi_sesudah || '-') + ' &bull; ' + dateStr + '</span>'
          + '</div></div>';
      }).join('')
    : '<div class="activity-item" style="justify-content: center; background: transparent; border: none; color: #8297b0;">Belum ada aktivitas hari ini.</div>';
}

async function loadHistory() {
  const history = await requestJson('/api/transaksi/riwayat').catch(() => []);
  renderHistoryTable(history);

  const transactions = await requestJson('/api/transaksi').catch(() => []);
  
  // Calculate dynamic stats
  const masukList = transactions.filter(t => t.jenis_transaksi === 'masuk');
  const keluarList = transactions.filter(t => t.jenis_transaksi === 'keluar');
  
  let totalLinenMasuk = 0;
  masukList.forEach(t => totalLinenMasuk += (t.total_linen || 0));
  
  let totalLinenKeluar = 0;
  keluarList.forEach(t => totalLinenKeluar += (t.total_linen || 0));
  
  const totalLinenAll = totalLinenMasuk + totalLinenKeluar;
  const pctMasuk = totalLinenAll ? Math.round((totalLinenMasuk / totalLinenAll) * 100) : 0;
  const pctKeluar = totalLinenAll ? (100 - pctMasuk) : 0;
  
  // Update UI Stats
  const elTotalMasuk = document.getElementById('history-total-masuk');
  if (elTotalMasuk) {
    elTotalMasuk.textContent = totalLinenMasuk.toLocaleString('id-ID');
    document.getElementById('history-subtext-masuk').innerHTML = `<span style="color:#00D084; font-weight:700;">Data Real-time</span>`;
  }
  
  const elTotalKeluar = document.getElementById('history-total-keluar');
  if (elTotalKeluar) {
    elTotalKeluar.textContent = totalLinenKeluar.toLocaleString('id-ID');
    document.getElementById('history-subtext-keluar').innerHTML = `<span style="color:#00D084; font-weight:700;">Data Real-time</span>`;
  }
  
  const donutMasuk = document.getElementById('donut-masuk');
  if (donutMasuk) {
    donutMasuk.setAttribute('stroke-dasharray', `${pctMasuk}, 100`);
    if (pctMasuk > 0) {
      donutMasuk.setAttribute('stroke-dashoffset', `-${pctKeluar}`);
    } else {
      donutMasuk.setAttribute('stroke-dashoffset', `0`);
    }
  }
  const donutKeluar = document.getElementById('donut-keluar');
  if (donutKeluar) {
    donutKeluar.setAttribute('stroke-dasharray', `${pctKeluar}, 100`);
  }
  
  const legendMasuk = document.getElementById('legend-masuk');
  if (legendMasuk) legendMasuk.textContent = `${pctMasuk}%`;
  
  const legendKeluar = document.getElementById('legend-keluar');
  if (legendKeluar) legendKeluar.textContent = `${pctKeluar}%`;

  const donutCenterNum = document.getElementById('donut-center-number');
  if (donutCenterNum) donutCenterNum.textContent = totalLinenAll.toLocaleString('id-ID');

  const masukTable = document.getElementById('history-masuk-table');
  const keluarTable = document.getElementById('history-keluar-table');

  if (masukTable) {
    let masukCount = 1;
        masukTable.innerHTML = transactions.filter(t => t.jenis_transaksi === 'masuk').length
      ? transactions.filter(t => t.jenis_transaksi === 'masuk').map(t =>
        `<tr class="history-row" data-id="${t.id}"><td>${masukCount++}</td><td>${t.created_at}</td><td>${t.petugas}</td><td>${t.ruangan}</td><td>${t.total_linen}</td><td><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--accent-cyan); opacity: 0.8;"><polyline points="9 18 15 12 9 6"></polyline></svg></td></tr>`
      ).join('')
      : '<tr><td colspan="6" style="text-align:center; color:var(--text-sub);">Belum ada log masuk.</td></tr>';
  }
  if (keluarTable) {
    let keluarCount = 1;
    keluarTable.innerHTML = transactions.filter(t => t.jenis_transaksi === 'keluar').length
      ? transactions.filter(t => t.jenis_transaksi === 'keluar').map(t =>
        `<tr class="history-row" data-id="${t.id}"><td>${keluarCount++}</td><td>${t.created_at}</td><td>${t.petugas}</td><td>${t.ruangan}</td><td>${t.total_linen}</td><td><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--accent-cyan); opacity: 0.8;"><polyline points="9 18 15 12 9 6"></polyline></svg></td></tr>`
      ).join('')
      : '<tr><td colspan="6" style="text-align:center; color:var(--text-sub);">Belum ada log keluar.</td></tr>';
  }

  document.querySelectorAll('.history-row').forEach(row => {
    row.addEventListener('click', async () => {
      document.querySelectorAll('.history-row').forEach(r => r.classList.remove('selected'));
      row.classList.add('selected');
      const id = row.getAttribute('data-id');
      const details = await requestJson(`/api/transaksi/${id}/detail`).catch(() => []);
      const detailTbody = document.querySelector('#history-detail-table tbody');
      if (detailTbody) {
        let count = 1;
        detailTbody.innerHTML = details.length ? details.map(d =>
          `<tr><td>${count++}</td><td>${d.epc}</td><td>${formatCategoryBadge(d.kategori)}</td><td>${d.nama_linen}</td><td>${d.total_cuci}</td><td>${d.keterangan || '-'}</td></tr>`
        ).join('') : '<tr><td colspan="6" style="text-align:center; color:var(--text-sub);">Tidak ada detail.</td></tr>';
      }
    });
  });
  if (typeof loadDashboardActivityHistory === 'function') {
    loadDashboardActivityHistory().catch(() => {});
  }
}

function updateRfidBadges(connected, data = null) {
  const statusText = connected ? 'CONNECTED' : 'DISCONNECTED';
  const className = connected ? 'badge-connected' : 'badge-disconnected';

  const badges = document.querySelectorAll('#rfid-status-badge, .header-status-badge span, .sidebar-reader-status > span, .header-status-badge > span');
  badges.forEach(badge => {
    badge.className = className;
    badge.innerHTML = `<span class="led-dot"></span>${statusText}`;
  });

  const isMasukConn = data && data.incoming ? (data.incoming.status === 'connected') : connected;
  const isKeluarConn = data && data.outgoing ? (data.outgoing.status === 'connected') : connected;

  const masukBadge = document.getElementById('rfid-status-badge-masuk');
  if (masukBadge) {
    const txt = isMasukConn ? 'CONNECTED' : 'DISCONNECTED';
    const cls = isMasukConn ? 'badge-connected' : 'badge-disconnected';
    masukBadge.innerHTML = `<span class="${cls}"><span class="led-dot"></span>${txt}</span>`;
  }

  const keluarBadge = document.getElementById('rfid-status-badge-keluar');
  if (keluarBadge) {
    const txt = isKeluarConn ? 'CONNECTED' : 'DISCONNECTED';
    const cls = isKeluarConn ? 'badge-connected' : 'badge-disconnected';
    keluarBadge.innerHTML = `<span class="${cls}"><span class="led-dot"></span>${txt}</span>`;
  }

  if (data) {
    if (data.incoming && data.incoming.port) {
      const pMasuk = document.getElementById('rfid-port-masuk');
      if (pMasuk) pMasuk.textContent = data.incoming.port;
    }
    if (data.outgoing && data.outgoing.port) {
      const pKeluar = document.getElementById('rfid-port-keluar');
      if (pKeluar) pKeluar.textContent = data.outgoing.port;
    }
  }

  const readerStatus = document.getElementById('reader-status');
  if (readerStatus) {
    readerStatus.textContent = connected ? 'Reader connected' : 'Reader disconnected';
    readerStatus.style.color = connected ? '#00D084' : '#ed5968';
  }
}

async function initRfidPortWidget() {
  const select = document.getElementById('rfid-port-select');
  const badges = document.querySelectorAll('#rfid-status-badge, .header-status-badge span');
  const sidebarPort = document.getElementById('sidebar-port-name');
  // Always run - don't bail out just because selectors aren't found on this page

  async function refreshRfidStatus() {
    try {
      const data = await requestJson('/api/rfid/status?_t=' + Date.now());
      const currentPort = data.port || 'COM3';
      const sidebarMode = document.getElementById('sidebar-mode-name');
      const sidebarActive = document.getElementById('sidebar-active-scanner');
      const sidebarSync = document.getElementById('sidebar-last-sync');
      if (sidebarMode && data.mode) sidebarMode.textContent = data.mode;
      if (sidebarActive) {
        const activeLabel = data.active_scanner_label || (data.active_reader ? (data.active_reader + ' - ' + (data.transaction_type === 'LINEN_KELUAR' ? 'Linen Keluar' : 'Linen Masuk')) : 'COM3 - Linen Masuk');
        sidebarActive.textContent = activeLabel;
      }
      if (sidebarPort && data.port) sidebarPort.textContent = data.port;
      if (sidebarSync && data.last_sync) sidebarSync.textContent = data.last_sync;


      if (select) {
        const available = Array.isArray(data.available_ports) && data.available_ports.length > 0 ? data.available_ports : [currentPort];
        const dropdownOptions = document.getElementById('dropdown-port-options');
        
        if (dropdownOptions) {
          const existing = Array.from(dropdownOptions.children).map(o => o.getAttribute('data-value'));
          const same = existing.length === available.length && available.every(p => existing.includes(p));
          if (!same) {
            dropdownOptions.innerHTML = '';
            available.forEach(port => {
              const div = document.createElement('div');
              div.className = 'dropdown-option' + (port === currentPort ? ' selected' : '');
              div.setAttribute('data-value', port);
              div.textContent = port;
              dropdownOptions.appendChild(div);
            });
          }
          const selectedLabel = document.querySelector('#dropdown-port .dropdown-selected');
          if (selectedLabel) selectedLabel.textContent = currentPort;
        } else if (select.options) {
          const existing = Array.from(select.options).map(o => o.value);
          const same = existing.length === available.length && available.every(p => existing.includes(p));
          if (!same) {
            select.innerHTML = '';
            available.forEach(port => {
              const opt = document.createElement('option');
              opt.value = port;
              opt.textContent = port;
              select.appendChild(opt);
            });
          }
        }
        select.value = currentPort;
      }
      
      const connected = data.status === 'connected';
      updateRfidBadges(connected, data);
    } catch (err) {
      console.warn('RFID status check failed:', err);
      updateRfidBadges(false);
    }
  }

  await refreshRfidStatus();
  setInterval(refreshRfidStatus, 2000);

  if (select) {
    select.addEventListener('change', async () => {
      const newPort = select.value;
      try {
        await requestJson('/api/rfid/port', {
          method: 'POST',
          body: JSON.stringify({ port: newPort }),
        });
        await refreshRfidStatus();
      } catch (err) {
        console.warn('Gagal mengganti port RFID:', err);
      }
    });
  }
}

function processScannedEpc(epc) {
  if (typeof window.onSyncDataEpcScanned === 'function') {
    window.onSyncDataEpcScanned(epc);
  }
  if (settingScanActive) {
    processSettingScannedEpc(epc);
    return;
  }
  if (afkirScanActive) {
    processAfkirScannedEpc(epc);
    return;
  }
  if (!scanActive || !scanContext) return;

  if (scannedEpcs.has(epc)) return; // Deduplicate
  scannedEpcs.add(epc);

  const cekTbody = document.querySelector(`#${scanContext}-cek-table tbody`);
  const mainTbody = document.querySelector(`#${scanContext}-main-table tbody`);

  if (!cekTbody || !mainTbody) return;

  const count = scannedEpcs.size;

  // If first item added, clear empty placeholder if any
  const emptyRowMain = mainTbody.querySelector('.empty-table-box');
  if (emptyRowMain) mainTbody.innerHTML = '';
  const emptyRowCek = cekTbody.querySelector('.empty-table-box');
  if (emptyRowCek) cekTbody.innerHTML = '';

  cekTbody.insertAdjacentHTML('afterbegin', `<tr><td>${count}</td><td>${epc}</td></tr>`);

  const linenData = masterLinen.find(l => l.epc === epc) || {
    id: 'LN-' + String(count).padStart(5, '0'), kategori: 'Lainnya', nama_linen: 'Linen RFID', total_cuci: 1, lokasi: scanContext === 'masuk' ? 'R. Laundry' : 'Ruangan', status: 'Tercatat'
  };

  mainTbody.insertAdjacentHTML('afterbegin', `
    <tr>
      <td>${count}</td>
      <td>${linenData.id}</td>
      <td>${epc}</td>
      <td>${formatCategoryBadge(linenData.kategori)}</td>
      <td>${linenData.nama_linen}</td>
      <td>${linenData.total_cuci}</td>
      <td>${linenData.lokasi}</td>
      <td><span class="badge-connected"><span class="led-dot"></span>Tercatat</span></td>
      <td>-</td>
    </tr>
  `);
}

function normalizeEpc(epc) {
  if (!epc) return '';
  const s = String(epc).trim().toUpperCase();
  if (s.length === 28 && s.startsWith('3000')) {
    return s.slice(4);
  }
  return s;
}

function settingRowMessage(colspan, message) {
  return `<tr><td colspan="${colspan}" style="text-align:center; color: var(--muted);">${message}</td></tr>`;
}

function renderSettingSession() {
  const cek = document.getElementById('cek-linen-body');
  const registered = document.getElementById('linen-terdaftar-body');
  const unregistered = document.getElementById('linen-tidak-terdaftar-body');
  const registeredItems = Array.from(settingScannedEpcs)
    .map(epc => settingCloudItems.get(normalizeEpc(epc))).filter(Boolean);
  const unknownItems = Array.from(settingScannedEpcs)
    .filter(epc => !settingCloudItems.has(normalizeEpc(epc)));

  if (cek) cek.innerHTML = settingScannedEpcs.size
    ? Array.from(settingScannedEpcs).map((epc, i) => `<tr><td>${i + 1}</td><td>${epc}</td><td>${settingCloudItems.has(normalizeEpc(epc)) ? 'Ada' : 'Tidak'}</td></tr>`).join('')
    : settingRowMessage(3, 'Belum ada data scan.');
  if (registered) registered.innerHTML = registeredItems.length
    ? registeredItems.map((item, i) => `<tr><td>${i + 1}</td><td>${item.id ?? '-'}</td><td>${item.epc}</td><td>${item.kategori || '-'}</td><td>${item.nama_linen || '-'}</td></tr>`).join('')
    : settingRowMessage(5, 'Belum ada data.');
  if (unregistered) unregistered.innerHTML = unknownItems.length
    ? unknownItems.map((epc, i) => `<tr><td>${i + 1}</td><td>${epc}</td></tr>`).join('')
    : settingRowMessage(2, 'Belum ada data.');
  const total = document.getElementById('setting-total-scan');
  const valid = document.getElementById('setting-valid-scan');
  const invalid = document.getElementById('setting-invalid-scan');
  if (total) total.textContent = settingScannedEpcs.size;
  if (valid) valid.textContent = registeredItems.length;
  if (invalid) invalid.textContent = unknownItems.length;
}

function processSettingScannedEpc(epc) {
  const norm = normalizeEpc(epc);
  if (settingScannedEpcs.has(norm)) return;
  settingScannedEpcs.add(norm);
  renderSettingSession();
}

async function loadSettingLog() {
  const body = document.getElementById('log-penerimaan-body');
  if (!body) return;
  try {
    const rows = await requestJson('/api/setting/log');
    if (!rows || !rows.length) {
      body.innerHTML = settingRowMessage(5, 'Belum ada log penerimaan.');
      const detailBody = document.getElementById('log-detail-body');
      if (detailBody) detailBody.innerHTML = settingRowMessage(4, 'Belum ada detail.');
      return;
    }
    body.innerHTML = rows.map(row => `
      <tr class="log-row" data-id="${row.id}">
        <td>${row.no}</td>
        <td style="color: #94a3b8; font-size: 0.85rem;">${row.tanggal}</td>
        <td style="color: #e2e8f0;">${row.petugas}</td>
        <td><span class="badge badge-info" style="font-weight:700;">${row.jumlah_linen} Linen</span></td>
        <td style="color: #cbd5e1; font-size: 0.85rem;">${row.keterangan}</td>
      </tr>
    `).join('');

    body.querySelectorAll('.log-row').forEach(row => {
      row.addEventListener('click', async () => {
        body.querySelectorAll('.log-row').forEach(item => item.classList.remove('selected'));
        row.classList.add('selected');
        const detailBody = document.getElementById('log-detail-body');
        if (detailBody) detailBody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:#94a3b8; padding: 20px;">Memuat detail linen...</td></tr>';
        try {
          const detail = await requestJson(`/api/setting/log/${row.dataset.id}/detail`);
          if (detailBody) {
            detailBody.innerHTML = detail.length ? detail.map((item, i) => `
              <tr>
                <td>${i + 1}</td>
                <td style="font-family: monospace; font-weight: 600; color: #00D4FF;">${item.epc}</td>
                <td>${formatCategoryBadge(item.kategori)}</td>
                <td style="color: #e2e8f0; font-weight: 500;">${item.nama_linen}</td>
              </tr>
            `).join('') : settingRowMessage(4, 'Tidak ada detail linen.');
          }
        } catch (err) {
          if (detailBody) detailBody.innerHTML = settingRowMessage(4, 'Gagal memuat detail: ' + err.message);
        }
      });
    });

    const firstRow = body.querySelector('.log-row');
    if (firstRow) {
      firstRow.click();
    }
  } catch (err) {
    body.innerHTML = settingRowMessage(5, 'Gagal memuat log: ' + err.message);
  }
}
window.loadSettingLog = loadSettingLog;

function updateSettingScanButtonUI(btn, active) {
  if (!btn) return;
  const iconPlay = btn.querySelector('.scan-icon-play');
  const iconStop = btn.querySelector('.scan-icon-stop');
  const text = btn.querySelector('.scan-text');

  if (active) {
    btn.classList.remove('btn-primary');
    btn.classList.add('btn-danger', 'is-scanning');
    if (iconPlay) iconPlay.style.display = 'none';
    if (iconStop) iconStop.style.display = 'inline-block';
    if (text) text.textContent = 'Stop Scan';
  } else {
    btn.classList.remove('btn-danger', 'is-scanning');
    btn.classList.add('btn-primary');
    if (iconPlay) iconPlay.style.display = 'inline-block';
    if (iconStop) iconStop.style.display = 'none';
    if (text) text.textContent = 'Start Scan';
  }
}

function setupSettings() {
  loadSettingLog();

  const form = document.getElementById('form-verifikasi');
  if (form) {
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const code = document.getElementById('input-kode-verifikasi').value.trim();
      const petugas = document.getElementById('input-nama-petugas').value.trim();
      const status = document.getElementById('verifikasi-status');
      if (!code || !petugas) { notify('Kode verifikasi dan nama petugas wajib diisi.', 'warning'); return; }
      const button = document.getElementById('btn-get-data');
      button.disabled = true;
      try {
        const result = await requestJson(`/api/setting/get-data?kode=${encodeURIComponent(code)}`);
        settingPackage = result.paket;
        settingCloudItems = new Map((result.linen_items || []).map(item => {
          const norm = normalizeEpc(item.epc);
          return [norm, { ...item, epc: norm }];
        }));
        settingScannedEpcs.clear();
        renderSettingSession();
        status.textContent = `Paket ditemukan: ${settingCloudItems.size} linen.`;
      } catch (err) {
        settingPackage = null; settingCloudItems.clear(); settingScannedEpcs.clear(); renderSettingSession();
        status.textContent = err.message;
        notify(err.message, 'error');
      } finally { button.disabled = false; }
    });
  }

  const toggleScanBtn = document.getElementById('btn-toggle-cek-linen') || document.getElementById('btn-start-scan-setting');
  if (toggleScanBtn) {
    toggleScanBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!settingScanActive) {
        try {
          const result = await requestJson('/api/rfid/scan/start', { method: 'POST' });
          if (result.status !== 'ok') { notify(result.message, 'error'); return; }
          settingScanActive = true;
          updateSettingScanButtonUI(toggleScanBtn, true);
          notify('Scan linen verifikasi dimulai.', 'info');
        } catch (err) { notify(err.message, 'error'); }
      } else {
        try { await requestJson('/api/rfid/scan/stop', { method: 'POST' }); } catch (err) { notify(err.message, 'error'); }
        settingScanActive = false;
        updateSettingScanButtonUI(toggleScanBtn, false);
        notify('Scan linen dihentikan.', 'info');
      }
    });
  }

  const resetBtn = document.getElementById('btn-reset-cek-linen') || document.getElementById('btn-reset-setting');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      settingScanActive = false;
      settingScannedEpcs.clear();
      if (toggleScanBtn) updateSettingScanButtonUI(toggleScanBtn, false);
      renderSettingSession();
      notify('Tabel scan verifikasi di-reset.', 'info');
    });
  }

  const saveBtn = document.getElementById('btn-simpan-cek-linen') || document.getElementById('btn-simpan-data');
  if (saveBtn) {
    saveBtn.addEventListener('click', async event => {
      if (settingSaving) return;
      const validItems = Array.from(settingScannedEpcs).map(epc => settingCloudItems.get(epc)).filter(Boolean);
      if (!settingPackage || !validItems.length) { notify('Tidak ada linen valid yang siap disimpan. Scan linen terlebih dahulu.', 'warning'); return; }
      const petugas = document.getElementById('input-nama-petugas').value.trim();
      if (!petugas) { notify('Nama petugas wajib diisi.', 'warning'); return; }
      settingSaving = true; event.currentTarget.disabled = true;
      try {
        const result = await requestJson('/api/setting/simpan-data', {
          method: 'POST', body: JSON.stringify({
            verification_code: document.getElementById('input-kode-verifikasi').value.trim(),
            petugas, paket_id: settingPackage.id, supplier: settingPackage.supplier,
            catatan: settingPackage.nomor_pengiriman || settingPackage.catatan, linen_terdaftar: validItems
          })
        });
        notify(result.message, 'success');
        settingPackage = null; settingCloudItems.clear(); settingScannedEpcs.clear(); settingScanActive = false;
        if (toggleScanBtn) updateSettingScanButtonUI(toggleScanBtn, false);
        renderSettingSession();
        await loadMasterData(); await loadSettingLog();
      } catch (err) { notify(err.message, 'error'); }
      finally { settingSaving = false; event.currentTarget.disabled = false; }
    });
  }

  loadSettingLog();
}

// ==================== AFKIR / PEMUSNAHAN LINEN ====================
function processAfkirScannedEpc(epc) {
  if (!epc) return;
  const cleanEpc = normalizeEpc(epc);
  if (afkirScannedEpcs.has(cleanEpc)) return; // Deduplicate

  // Lookup in cached masterLinen
  const found = masterLinen.find(l => (l.epc || '').toUpperCase() === cleanEpc.toUpperCase());
  const isValid = !!found;
  const timeStr = new Date().toLocaleTimeString('id-ID');

  afkirScannedEpcs.set(cleanEpc, {
    epc: cleanEpc,
    time: timeStr,
    found: found,
    isValid: isValid
  });

  renderAfkirScanTable();
}

function renderAfkirScanTable() {
  const tbody = document.getElementById('afkir-scan-table-body');
  if (!tbody) return;

  const items = Array.from(afkirScannedEpcs.values());
  const statTotal = document.getElementById('afkir-stat-total');
  const statValid = document.getElementById('afkir-stat-valid');
  const statInvalid = document.getElementById('afkir-stat-invalid');
  const submitBtnText = document.getElementById('btn-submit-afkir-text');

  const validCount = items.filter(i => i.isValid).length;
  const invalidCount = items.length - validCount;

  if (statTotal) statTotal.textContent = items.length;
  if (statValid) statValid.textContent = validCount;
  if (statInvalid) statInvalid.textContent = invalidCount;
  if (submitBtnText) submitBtnText.textContent = `Proses Pemusnahan (${validCount} Linen)`;

  if (items.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="9" style="text-align: center; color: #8297b0; padding: 30px;">
          Silakan klik <strong>"Mulai Scan Fisik"</strong> dan dekatkan tumpukan fisik linen yang akan diafkirkan ke antena RFID.
        </td>
      </tr>
    `;
    return;
  }

  let no = 1;
  tbody.innerHTML = items.map((item) => {
    const l = item.found;
    const badgeStatus = item.isValid
      ? '<span style="background: rgba(0,208,132,0.15); color: #00D084; border: 1px solid rgba(0,208,132,0.3); padding: 2px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600;">Terdaftar di RS</span>'
      : '<span style="background: rgba(239,68,68,0.15); color: #ef4444; border: 1px solid rgba(239,68,68,0.3); padding: 2px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600;">Tag Tidak Dikenal</span>';

    return `
      <tr>
        <td>${no++}</td>
        <td style="color: #8297b0; font-size: 0.8rem;">${item.time}</td>
        <td style="font-family: monospace; color: #fff; font-weight: 600;">${item.epc}</td>
        <td>${l ? formatCategoryBadge(l.kategori) : '-'}</td>
        <td style="color: ${item.isValid ? '#fff' : '#ef4444'}; font-weight: 500;">${l ? l.nama_linen : '(Bukan Milik RS)'}</td>
        <td>${l ? (l.total_cuci || 0) : '-'}</td>
        <td style="color: #8297b0;">${l ? (l.lokasi || '-') : '-'}</td>
        <td>${badgeStatus}</td>
        <td style="text-align: center;">
          <button type="button" onclick="removeAfkirScannedItem('${item.epc}')" style="background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); color: #ef4444; padding: 4px 8px; border-radius: 4px; cursor: pointer; font-size: 0.75rem; font-weight: 700;" title="Hapus dari daftar scan">
            ✕
          </button>
        </td>
      </tr>
    `;
  }).join('');
}

window.removeAfkirScannedItem = function(epc) {
  if (afkirScannedEpcs.has(epc)) {
    afkirScannedEpcs.delete(epc);
    renderAfkirScanTable();
  }
};

function setupAfkirLinen() {
  const toggleBtn = document.getElementById('btn-toggle-afkir-scan');
  const resetBtn = document.getElementById('btn-reset-afkir-scan');
  const submitBtn = document.getElementById('btn-submit-afkir');
  const statusIndicator = document.getElementById('afkir-scan-status-indicator');
  const iconSpan = document.getElementById('afkir-scan-icon');
  const textSpan = document.getElementById('afkir-scan-text');
  const petugasInput = document.getElementById('afkir-petugas');

  if (!toggleBtn || !submitBtn) return;

  toggleBtn.addEventListener('click', async () => {
    if (!afkirScanActive) {
      try {
        const res = await requestJson('/api/rfid/scan/start', { method: 'POST' });
        if (res.status !== 'ok') {
          notify(res.message || 'Gagal memulai scanner RFID.', 'error');
          return;
        }
        afkirScanActive = true;
        toggleBtn.style.background = '#ea580c';
        toggleBtn.style.color = '#fff';
        if (iconSpan) iconSpan.textContent = '■';
        if (textSpan) textSpan.textContent = 'Hentikan Scan Fisik';
        if (statusIndicator) {
          statusIndicator.innerHTML = '<span style="color:#00D4FF; font-weight:600;"><span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#00D084; box-shadow:0 0 8px #00D084; margin-right:6px;"></span>Scanner Aktif (Mendeteksi Tag...)</span>';
        }
        notify('Scan fisik pemusnahan linen dimulai. Dekatkan linen ke antena RFID.', 'info');
      } catch (err) {
        notify('Error scanner: ' + err.message, 'error');
      }
    } else {
      try {
        await requestJson('/api/rfid/scan/stop', { method: 'POST' });
      } catch (_) {}
      afkirScanActive = false;
      toggleBtn.style.background = '#00D4FF';
      toggleBtn.style.color = '#000';
      if (iconSpan) iconSpan.textContent = '▶';
      if (textSpan) textSpan.textContent = 'Mulai Scan Fisik';
      if (statusIndicator) {
        statusIndicator.innerHTML = '<span style="color:#8297b0;">Scanner Standby</span>';
      }
      notify('Scan fisik dihentikan.', 'info');
    }
  });

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      afkirScannedEpcs.clear();
      renderAfkirScanTable();
      notify('Tabel scan pemusnahan berhasil dibersihkan.', 'info');
    });
  }

  submitBtn.addEventListener('click', async () => {
    if (afkirScannedEpcs.size === 0) {
      notify('Scan fisik linen terlebih dahulu sebelum memproses pemusnahan.', 'warning');
      return;
    }

    const validItems = Array.from(afkirScannedEpcs.values()).filter(x => x.isValid);
    if (validItems.length === 0) {
      notify('Tidak ada linen terdaftar milik rumah sakit ini dalam daftar scan fisik.', 'error');
      return;
    }

    const validEpcs = validItems.map(x => x.epc);
    const alasan = document.getElementById('afkir-alasan')?.value || 'Rusak / Robek / Berlubang';
    const petugas = document.getElementById('afkir-petugas')?.value?.trim();
    if (!petugas) {
      notify('Nama Petugas Eksekutor wajib diisi terlebih dahulu.', 'warning');
      document.getElementById('afkir-petugas')?.focus();
      return;
    }
    const action = document.getElementById('afkir-action')?.value || 'afkir';
    const catatan = document.getElementById('afkir-catatan')?.value?.trim() || '';

    const confirmPrompt = action === 'delete'
      ? `PERINGATAN KERAS:\nAnda akan MENGHAPUS PERMANEN ${validEpcs.length} linen fisik dari database rumah sakit.\n\nAlasan: ${alasan}\nPetugas: ${petugas}\n\nTindakan ini tidak dapat dibatalkan. Lanjutkan?`
      : `KONFIRMASI PEMUSNAHAN LINEN:\nAnda akan menandai status AFKIR untuk ${validEpcs.length} linen fisik yang telah discan.\n\nAlasan: ${alasan}\nPetugas: ${petugas}\nLinen akan dinonaktifkan dari sirkulasi aktif & transaksi.\n\nLanjutkan?`;

    if (!(await showConfirm(confirmPrompt))) {
      return;
    }

    try {
      submitBtn.disabled = true;
      submitBtn.style.opacity = '0.6';

      const res = await requestJson('/api/master/linen/decommission', {
        method: 'POST',
        body: JSON.stringify({
          epc_list: validEpcs,
          alasan: alasan,
          petugas: petugas,
          catatan: catatan,
          action: action
        })
      });

      notify(res.message || `Berhasil memproses pemusnahan ${validEpcs.length} linen.`, 'success');

      // Stop scanner if active
      if (afkirScanActive) {
        try { await requestJson('/api/rfid/scan/stop', { method: 'POST' }); } catch (_) {}
        afkirScanActive = false;
        toggleBtn.style.background = '#00D4FF';
        toggleBtn.style.color = '#000';
        if (iconSpan) iconSpan.textContent = '▶';
        if (textSpan) textSpan.textContent = 'Mulai Scan Fisik';
        if (statusIndicator) statusIndicator.innerHTML = '<span style="color:#8297b0;">Scanner Standby</span>';
      }

      afkirScannedEpcs.clear();
      renderAfkirScanTable();

      // Refresh master data and dashboard
      await loadMasterData();
      if (typeof refreshDashboardGlobal === 'function') {
        refreshDashboardGlobal();
      }

      // Switch to 'afkir' tab to view decommissioned linen list
      const afkirTabBtn = document.querySelectorAll('.linen-tab')[3];
      if (afkirTabBtn) {
        afkirTabBtn.click();
      }
    } catch (err) {
      notify('Gagal memproses pemusnahan: ' + err.message, 'error');
    } finally {
      submitBtn.disabled = false;
      submitBtn.style.opacity = '1';
    }
  });
}

function initWebSocket() {
  if (typeof WebSocket === 'undefined') return;
  if (activeSocket && (activeSocket.readyState === WebSocket.CONNECTING || activeSocket.readyState === WebSocket.OPEN)) {
    return;
  }

  try {
    activeSocket = new WebSocket(wsUrl);

    activeSocket.onopen = () => {
      wsConnected = true;
      if (isServerOffline) {
        hideReconnectOverlay();
      }
      refreshRfidStatus();
    };


const scanDebounceMap = new Map();

async function handleAutoScanTrigger(payload) {
  const path = window.location.pathname;
  if (settingScanActive || path.includes('/settings') || path.includes('/master-data')) return;
  const epc = payload.epc;
  if (!epc) return;
  const isKeluar = payload.transaction_type === 'LINEN_KELUAR' || payload.port === 'COM4' || payload.reader_name === 'RFID_LINEN_KELUAR';
  const trxType = isKeluar ? 'LINEN_KELUAR' : 'LINEN_MASUK';
  const key = `${trxType}_${epc}`;

  const now = Date.now();
  if (scanDebounceMap.has(key) && (now - scanDebounceMap.get(key) < 4000)) {
    return;
  }
  scanDebounceMap.set(key, now);

  try {
    const result = await requestJson('/api/transaksi/auto-scan', {
      method: 'POST',
      body: JSON.stringify({
        epc: epc,
        transaction_type: trxType,
        reader_name: payload.reader_name || (isKeluar ? 'RFID_LINEN_KELUAR' : 'RFID_LINEN_MASUK'),
        port: payload.port || (isKeluar ? 'COM4' : 'COM3'),
        ruangan: isKeluar ? (document.getElementById('select-ruangan-keluar')?.value || 'Ruangan Pasien') : 'R. Laundry'
      })
    });

    if (result && result.status === 'ok') {
      if (typeof loadMasterData === 'function') loadMasterData().catch(() => {});
      if (typeof loadHistory === 'function') loadHistory().catch(() => {});
      if (typeof refreshDashboardGlobal === 'function') refreshDashboardGlobal().catch(() => {});
    }
  } catch (err) {
    console.warn('Auto-scan API failed:', err);
  }
}

    activeSocket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === 'reader_status' || payload.type === 'rfid_status') {
          updateRfidBadges(payload.status === 'connected' || payload.status === 'ACTIVE', payload);
          const sidebarMode = document.getElementById('sidebar-mode-name');
          const modeText = payload.mode_label || (payload.mode === 'DUAL_READER' ? 'Dual Reader Mode' : 'Single Reader Mode');
          if (sidebarMode) sidebarMode.textContent = modeText;

          const sidebarPort = document.getElementById('sidebar-port-name');
          if (sidebarPort && payload.port) sidebarPort.textContent = payload.port;

          const sidebarActive = document.getElementById('sidebar-active-scanner');
          if (sidebarActive && payload.active_scanner_label) {
            sidebarActive.textContent = payload.active_scanner_label;
          }
        } else if (payload.type === 'epc') {
          const isKeluar = payload.transaction_type === 'LINEN_KELUAR' || payload.port === 'COM4' || payload.reader_name === 'RFID_LINEN_KELUAR';

          const dashboardEpcBody = document.getElementById('epc-table-body');
          if (dashboardEpcBody) {
            const emptyRow = dashboardEpcBody.querySelector('.empty-table-box');
            if (emptyRow) dashboardEpcBody.innerHTML = '';

            const statusBadge = isKeluar
              ? '<span style="background: rgba(59,130,246,0.15); color: #3b82f6; padding: 4px 12px; border-radius: 12px; border: 1px solid rgba(59,130,246,0.3); font-weight: 600; font-size: 0.8rem; display: inline-block;">Keluar</span>'
              : '<span style="background: rgba(0,208,132,0.15); color: #00D084; padding: 4px 12px; border-radius: 12px; border: 1px solid rgba(0,208,132,0.3); font-weight: 600; font-size: 0.8rem; display: inline-block;">Masuk</span>';

            const row = document.createElement('tr');
            row.className = 'scan-highlight';
            row.innerHTML = `<td>${new Date().toLocaleTimeString('id-ID')}</td><td style="font-family: monospace; letter-spacing: 0.5px;">${payload.epc}</td><td>${isKeluar ? 'Ruangan Pasien' : 'Laundry Room'}</td><td>${statusBadge}</td>`;
            dashboardEpcBody.prepend(row);
            while (dashboardEpcBody.children.length > 6) {
              dashboardEpcBody.removeChild(dashboardEpcBody.lastChild);
            }
          }

          const timeStr = new Date().toLocaleTimeString('id-ID');
          if (isKeluar) {
            const keluarTbody = document.getElementById('keluar-scanner-live-tbody');
            if (keluarTbody) {
              const emptyCell = keluarTbody.querySelector('td[colspan]');
              if (emptyCell) keluarTbody.innerHTML = '';
              const tr = document.createElement('tr');
              tr.className = 'scan-highlight';
              tr.innerHTML = `<td>${timeStr}</td><td style="font-family: monospace;">${payload.epc}</td><td>Linen ${payload.epc.slice(-6)}</td><td>Ruangan Pasien</td><td><span class="badge-connected" style="padding: 2px 8px; font-size: 0.75rem;">Tercatat</span></td>`;
              keluarTbody.prepend(tr);
              while (keluarTbody.children.length > 5) keluarTbody.removeChild(keluarTbody.lastChild);
            }
          } else {
            const masukTbody = document.getElementById('masuk-scanner-live-tbody');
            if (masukTbody) {
              const emptyCell = masukTbody.querySelector('td[colspan]');
              if (emptyCell) masukTbody.innerHTML = '';
              const tr = document.createElement('tr');
              tr.className = 'scan-highlight';
              tr.innerHTML = `<td>${timeStr}</td><td style="font-family: monospace;">${payload.epc}</td><td>Linen ${payload.epc.slice(-6)}</td><td>Linen General</td><td><span class="badge-connected" style="padding: 2px 8px; font-size: 0.75rem;">Tercatat</span></td>`;
              masukTbody.prepend(tr);
              while (masukTbody.children.length > 5) masukTbody.removeChild(masukTbody.lastChild);
            }
          }

          // Scan RFID hanya mendata tag ke tabel UI sementara. Transaksi hanya dicatat saat form disubmit.
          if (typeof window.onSyncDataEpcScanned === 'function') {
            window.onSyncDataEpcScanned(payload.epc);
          }
          processScannedEpc(payload.epc);
        }
      } catch (error) {
        console.warn('WebSocket message parse failed', error);
      }
    };

    activeSocket.onerror = () => {
      // Only show overlay if WS had previously connected successfully.
      // On first page load, onerror can fire before a connection is established
      // which would incorrectly block the UI.
      if (wsConnected) {
        updateRfidBadges(false);
        pingServer().then(online => { if (!online) showReconnectOverlay(); });
      }
    };

    activeSocket.onclose = (event) => {
      console.log('WS ditutup, code:', event.code);
      // code 1000 = normal close, don't trigger overlay
      // Only trigger if we had a live connection before
      if (wsConnected) {
        wsConnected = false;
        updateRfidBadges(false);
        // Verify server is actually down before showing scary overlay
        pingServer().then(online => {
          if (!online) showReconnectOverlay();
        });
      }
      // Always try to reconnect after 3s
      setTimeout(initWebSocket, 3000);
    };
  } catch (_) {
    // Only show overlay if we previously had a connection
    if (wsConnected) showReconnectOverlay();
  }
}

function setupLaundryTabs() {
  const tabs = document.querySelectorAll('.tab-btn');
  const contents = document.querySelectorAll('.tab-content');
  tabs.forEach(tab => {
    tab.addEventListener('click', (e) => {
      e.preventDefault();
      tabs.forEach(t => t.classList.remove('active'));
      contents.forEach(c => c.style.display = 'none');
      tab.classList.add('active');
      const target = tab.getAttribute('data-target');
      document.getElementById(target).style.display = 'block';

      // Update scanContext implicitly
      if (target === 'tab-masuk') scanContext = 'masuk';
      else if (target === 'tab-keluar') scanContext = 'keluar';
      else scanContext = null;

      setScanState(false); // Stop scanning when switching tabs
    });
  });

  // Initialize context based on active tab
  const activeTab = document.querySelector('.tab-btn.active');
  if (activeTab) {
    const target = activeTab.getAttribute('data-target');
    scanContext = target === 'tab-masuk' ? 'masuk' : (target === 'tab-keluar' ? 'keluar' : null);
  }

  // Bind Scan buttons
  document.querySelectorAll('.btn-toggle-scan').forEach(btn => btn.addEventListener('click', () => {
    setScanState(!scanActive);
    if (scanActive) {
      notify('Scan dimulai.', 'info');
    } else {
      notify('Scan dihentikan.', 'info');
    }
  }));
  document.querySelectorAll('.btn-reset-table').forEach(btn => btn.addEventListener('click', () => {
    if (scanContext) {
      document.querySelector(`#${scanContext}-cek-table tbody`).innerHTML = '';
      renderEmptyTable(scanContext);
      scannedEpcs.clear();
    }
  }));

  // Setup current time inputs
  setInterval(() => {
    const now = new Date();
    const formatted = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0') + ' ' +
      String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0') + ':' + String(now.getSeconds()).padStart(2, '0');
    document.querySelectorAll('.current-time-input').forEach(input => input.value = formatted);
  }, 1000);

  // Setup search filters for Laundry tables
  const setupSearch = (inputId, tableId) => {
    const input = document.getElementById(inputId);
    const table = document.getElementById(tableId);
    if (!input || !table) return;

    input.addEventListener('input', (e) => {
      const term = e.target.value.toLowerCase();
      const rows = table.querySelectorAll('tbody tr');
      rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(term) ? '' : 'none';
      });
    });
  };

  setupSearch('search-masuk', 'masuk-main-table');
  setupSearch('search-keluar', 'keluar-main-table');
}

async function handleTransaksiSubmit(event, jenis) {
  event.preventDefault();
  if (scannedEpcs.size === 0) {
    notify('Scan linen terlebih dahulu sebelum memproses.', 'warning');
    return;
  }

  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form));

  try {
    await requestJson('/api/transaksi/batch', {
      method: 'POST',
      body: JSON.stringify({
        jenis_transaksi: jenis,
        petugas: payload.petugas,
        ruangan: payload.ruangan,
        epc_list: Array.from(scannedEpcs),
        catatan: `Transaksi ${jenis} via form UI`
      })
    });
    notify('Transaksi berhasil disimpan.', 'success');
    form.reset();
    scannedEpcs.clear();
    document.querySelector(`#${jenis}-cek-table tbody`).innerHTML = '';
    renderEmptyTable(jenis);
    scanActive = false;
    loadHistory(); // Refresh history
  } catch (err) {
    notify('Error: ' + err.message, 'error');
  }
}

function setScanState(active) {
  scanActive = active;
  const endpoint = active ? '/api/rfid/scan/start' : '/api/rfid/scan/stop';
  fetch(endpoint, {
    method: 'POST',
    headers: { 'X-ClientS-Request': '1' }
  }).catch(err => {
    console.warn('Gagal mengubah status scan RFID backend:', err);
  });

  document.querySelectorAll('.btn-toggle-scan').forEach(btn => {
    if (active) {
      btn.classList.remove('btn-primary');
      btn.classList.add('btn-danger', 'is-scanning');
      const iconPlay = btn.querySelector('.scan-icon-play');
      const iconStop = btn.querySelector('.scan-icon-stop');
      if (iconPlay) iconPlay.style.display = 'none';
      if (iconStop) iconStop.style.display = 'inline-block';
      const text = btn.querySelector('.scan-text');
      if (text) text.textContent = 'Stop Scan';
    } else {
      btn.classList.remove('btn-danger', 'is-scanning');
      btn.classList.add('btn-primary');
      const iconPlay = btn.querySelector('.scan-icon-play');
      const iconStop = btn.querySelector('.scan-icon-stop');
      if (iconPlay) iconPlay.style.display = 'inline-block';
      if (iconStop) iconStop.style.display = 'none';
      const text = btn.querySelector('.scan-text');
      if (text) text.textContent = 'Start Scan';
    }
  });
}

function renderEmptyTable(context) {
  const mainTbody = document.querySelector(`#${context}-main-table tbody`);
  const cekTbody = document.querySelector(`#${context}-cek-table tbody`);

  const isKeluar = context === 'keluar';

  // Render Main Table Empty State
  if (mainTbody) {
    const title = isKeluar ? 'Belum ada data linen keluar' : 'Belum ada data linen masuk';
    const desc = isKeluar
      ? 'Silakan scan linen dan pilih ruangan tujuan lalu klik proses untuk mencatat linen keluar.'
      : 'Silakan scan linen lalu klik proses untuk mencatat linen masuk.';

    mainTbody.innerHTML = `
      <tr>
        <td colspan="9" style="padding:0;">
          <div class="empty-table-box">
            <div class="empty-table-icon-box">
              <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 7V5a2 2 0 0 1 2-2h2"></path>
                <path d="M17 3h2a2 2 0 0 1 2 2v2"></path>
                <path d="M21 17v2a2 2 0 0 1-2 2h-2"></path>
                <path d="M7 21H5a2 2 0 0 1-2-2v-2"></path>
                <line x1="7" y1="12" x2="17" y2="12" stroke-width="1.5" stroke="currentColor"></line>
              </svg>
            </div>
            <div class="empty-table-title">${title}</div>
            <div class="empty-table-desc">${desc}</div>
          </div>
        </td>
      </tr>
    `;
  }

  // Render Cek Table Empty State (Compact)
  if (cekTbody) {
    cekTbody.innerHTML = `
      <tr>
        <td colspan="2" style="padding:0;">
          <div class="empty-table-box" style="padding: 24px 10px;">
            <div class="empty-table-icon-box" style="width: 48px; height: 48px; margin-bottom: 10px;">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M4 7V5a2 2 0 0 1 2-2h2"></path>
                <path d="M16 3h2a2 2 0 0 1 2 2v2"></path>
                <path d="M20 17v2a2 2 0 0 1-2 2h-2"></path>
                <path d="M8 21H6a2 2 0 0 1-2-2v-2"></path>
                <line x1="6" y1="12" x2="18" y2="12"></line>
              </svg>
            </div>
            <div class="empty-table-title" style="font-size: 0.9rem;">Belum ada EPC</div>
            <div class="empty-table-desc" style="font-size: 0.75rem;">Mulai scan untuk melihat EPC.</div>
          </div>
        </td>
      </tr>
    `;
  }
}

function renderDashboardEmptyTable() {
  const tbody = document.getElementById('epc-table-body');
  if (!tbody) return;
  tbody.innerHTML = `
    <tr>
      <td colspan="4" style="padding:0;">
        <div class="empty-table-box" style="padding: 30px 10px;">
          <div class="empty-table-icon-box" style="width: 48px; height: 48px; margin-bottom: 10px;">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M4 7V5a2 2 0 0 1 2-2h2"></path>
              <path d="M16 3h2a2 2 0 0 1 2 2v2"></path>
              <path d="M20 17v2a2 2 0 0 1-2 2h-2"></path>
              <path d="M8 21H6a2 2 0 0 1-2-2v-2"></path>
              <line x1="6" y1="12" x2="18" y2="12"></line>
            </svg>
          </div>
          <div class="empty-table-title" style="font-size: 0.95rem;">Belum ada Live Scan</div>
          <div class="empty-table-desc" style="font-size: 0.8rem;">Menunggu data dari mesin scanner...</div>
        </div>
      </td>
    </tr>
  `;
}

function onReady(fn) {
  if (document.readyState !== 'loading') {
    fn();
  } else {
    document.addEventListener('DOMContentLoaded', fn);
  }
}

onReady(() => {
  try {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/static/sw.js').catch((err) => {
        console.warn('SW registration failed:', err);
      });
    }
  } catch (_) {}

  try { startHeartbeatMonitor(); } catch (e) { console.error('Heartbeat error:', e); }
  try { initWebSocket(); } catch (e) { console.error('WS error:', e); }
  try { initRfidPortWidget(); } catch (e) { console.error('RFID widget error:', e); }
  try { updateConnectionStatus(); } catch (e) { console.error('Conn status error:', e); }

  try { window.addEventListener('online', updateConnectionStatus); } catch (_) {}
  try {
    window.addEventListener('offline', () => {
      updateConnectionStatus();
      showReconnectOverlay();
    });
  } catch (_) {}

  try { loadMasterData(); } catch (e) { console.error('Master data error:', e); }
  try { loadHistory(); } catch (e) { console.error('History error:', e); }
  try { loadDashboardActivityHistory(); } catch (e) { console.error('Dashboard activity error:', e); }
  try { setupLaundryTabs(); } catch (e) { console.error('Laundry tabs error:', e); }
  try { setupSettings(); } catch (e) { console.error('Settings error:', e); }
  try { setupAfkirLinen(); } catch (e) { console.error('Afkir linen setup error:', e); }
  try { renderEmptyTable('masuk'); } catch (_) {}
  try { renderEmptyTable('keluar'); } catch (_) {}

  // Sidebar Dropdown Logic
  document.querySelectorAll('.nav-group > .nav-item').forEach(header => {
    header.addEventListener('click', (e) => {
      // If it doesn't have a sub-menu, do nothing
      if (!header.nextElementSibling || !header.nextElementSibling.classList.contains('nav-sub')) {
        return;
      }
      e.preventDefault();
      const group = header.parentElement;
      group.classList.toggle('open');
    });
  });

  // Form handling
  document.getElementById('form-masuk')?.addEventListener('submit', (e) => handleTransaksiSubmit(e, 'masuk'));
  document.getElementById('form-keluar')?.addEventListener('submit', (e) => handleTransaksiSubmit(e, 'keluar'));

  // Dashboard summaries
  
// =============================================================================
// MODUL MONITORING SUPPLIER (PHASE 3.6 INTEGRATION)
// =============================================================================

async function loadIncomingSupplierPackages(statusFilter = null, limit = 50) {
  try {
    let url = `/api/receiving/packages?limit=${limit}`;
    if (statusFilter) url += `&status=${encodeURIComponent(statusFilter)}`;
    const res = await fetch(url, {
      credentials: "same-origin",
      headers: { "X-ClientS-Request": "1" }
    });
    if (!res.ok) return [];
    const data = await res.json().catch(() => ({}));
    return data.packages || [];
  } catch (err) {
    console.warn("loadIncomingSupplierPackages gagal (non-fatal):", err);
    return [];
  }
}

async function loadSupplierContracts() {
  try {
    const res = await fetch("/api/receiving/contracts", {
      credentials: "same-origin",
      headers: { "X-ClientS-Request": "1" }
    });
    if (!res.ok) return [];
    const data = await res.json().catch(() => ({}));
    return data.contracts || [];
  } catch (err) {
    console.warn("loadSupplierContracts gagal (non-fatal):", err);
    return [];
  }
}

async function loadSupplierDevices() {
  try {
    const res = await fetch("/api/receiving/devices", {
      credentials: "same-origin",
      headers: { "X-ClientS-Request": "1" }
    });
    if (!res.ok) return [];
    const data = await res.json().catch(() => ({}));
    return data.devices || [];
  } catch (err) {
    console.warn("loadSupplierDevices gagal (non-fatal):", err);
    return [];
  }
}

async function loadSupplierDashboardMetrics() {
  const pendingEl = document.getElementById("stat-paket-pending");
  const confirmedEl = document.getElementById("stat-paket-confirmed");
  const supplierEl = document.getElementById("stat-supplier-aktif");
  const recentTableBody = document.getElementById("supplier-recent-packages-body");

  // Jika elemen tidak ada di halaman ini, abaikan
  if (!pendingEl && !confirmedEl && !supplierEl && !recentTableBody) return;

  try {
    // 1. Ambil data paket incoming
    const packages = await loadIncomingSupplierPackages();
    const pendingCount = packages.filter(p => p.status === "pending" || p.status === "kirim").length;
    const confirmedCount = packages.filter(p => p.status === "confirmed").length;

    if (pendingEl) pendingEl.textContent = pendingCount;
    if (confirmedEl) confirmedEl.textContent = confirmedCount;

    // 2. Ambil data supplier rekanan
    try {
      const resSupp = await fetch("/api/receiving/suppliers", {
        credentials: "same-origin",
        headers: { "X-ClientS-Request": "1" }
      });
      if (resSupp.ok) {
        const suppData = await resSupp.json();
        const activeSuppliers = (suppData.suppliers || []).filter(s => s.is_active);
        if (supplierEl) supplierEl.textContent = activeSuppliers.length;
      } else {
        if (supplierEl) supplierEl.textContent = "0";
      }
    } catch (_) {
      if (supplierEl) supplierEl.textContent = "0";
    }

    // 3. Render tabel kiriman supplier terbaru pada dashboard
    if (recentTableBody) {
      if (!packages || packages.length === 0) {
        recentTableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #8297b0; padding: 12px;">Belum ada riwayat pengiriman dari supplier.</td></tr>';
      } else {
        const recent = packages.slice(0, 5);
        recentTableBody.innerHTML = recent.map(p => {
          let badgeClass = "badge-secondary";
          if (p.status === "kirim" || p.status === "pending") badgeClass = "badge-warning";
          else if (p.status === "claimed") badgeClass = "badge-info";
          else if (p.status === "confirmed") badgeClass = "badge-success";

          const createdTime = p.created_at ? new Date(p.created_at).toLocaleString('id-ID') : '-';
          const isPending = p.status === "kirim" || p.status === "pending";

          return `
            <tr>
              <td style="color: #8297b0; font-size: 0.8rem;">${createdTime}</td>
              <td style="font-family: monospace; color: #00D4FF; font-weight: 600;">${p.kode_pengiriman || '-'}</td>
              <td style="color: #fff;">${p.id}</td>
              <td><span class="badge ${badgeClass}" style="display:inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.7rem; font-weight: 700;">${p.status.toUpperCase()}</span></td>
              <td>
                <a href="/settings?tab=sync&paket_id=${p.id}" style="color: #00D4FF; font-size: 0.75rem; text-decoration: none; font-weight: 600; padding: 4px 8px; border-radius: 4px; background: rgba(0, 212, 255, 0.1); border: 1px solid rgba(0, 212, 255, 0.2);">
                  ${isPending ? 'Terima Paket' : 'Lihat'}
                </a>
              </td>
            </tr>
          `;
        }).join("");
      }
    }
  } catch (err) {
    console.warn("loadSupplierDashboardMetrics gagal (non-fatal):", err);
  }
}

async function loadDashboardActivityHistory() {
  const tbody = document.getElementById('app-recent-activity-body');
  if (!tbody) return;

  try {
    const transactions = await requestJson('/api/transaksi').catch(() => []);
    if (!transactions || transactions.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #8297b0; padding: 20px;">Belum ada riwayat aktivitas transaksi pada aplikasi.</td></tr>';
      return;
    }

    const recent = transactions.slice(0, 10);
    tbody.innerHTML = recent.map((t) => {
      let badgeStyle = '';
      let badgeLabel = t.jenis_transaksi || 'transaksi';
      const jenisLower = (t.jenis_transaksi || '').toLowerCase();

      if (jenisLower === 'penerimaan' || jenisLower === 'sync') {
        badgeStyle = 'background: rgba(0,212,255,0.12); color: #00D4FF; border: 1px solid rgba(0,212,255,0.3);';
        badgeLabel = 'Penerimaan Paket';
      } else if (jenisLower.includes('masuk')) {
        badgeStyle = 'background: rgba(0,208,132,0.12); color: #00D084; border: 1px solid rgba(0,208,132,0.3);';
        badgeLabel = 'Linen Masuk';
      } else if (jenisLower.includes('keluar')) {
        badgeStyle = 'background: rgba(59,130,246,0.12); color: #3b82f6; border: 1px solid rgba(59,130,246,0.3);';
        badgeLabel = 'Linen Keluar';
      } else if (jenisLower.includes('cuci')) {
        badgeStyle = 'background: rgba(168,85,247,0.12); color: #a855f7; border: 1px solid rgba(168,85,247,0.3);';
        badgeLabel = 'Pencucian';
      } else if (jenisLower.includes('afkir')) {
        badgeStyle = 'background: rgba(239,68,68,0.12); color: #ef4444; border: 1px solid rgba(239,68,68,0.3);';
        badgeLabel = 'Afkir Linen';
      } else {
        badgeStyle = 'background: rgba(148,163,184,0.12); color: #94a3b8; border: 1px solid rgba(148,163,184,0.3);';
        badgeLabel = (t.jenis_transaksi || '-').toUpperCase();
      }

      const waktuStr = t.created_at || '-';
      const kodeTrx = t.kode_transaksi || ('TRX-' + (t.id ? String(t.id).padStart(5, '0') : '-'));
      const ruanganStr = t.ruangan || '-';
      const totalLinen = t.total_linen || 0;
      const petugasStr = t.petugas || '-';
      const statusStr = (t.status || 'selesai').toUpperCase();

      return `
        <tr>
          <td style="color: #8297b0; font-size: 0.8rem; padding: 12px 14px;">${waktuStr}</td>
          <td style="padding: 12px 14px;">
            <span style="display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; ${badgeStyle}">
              ${badgeLabel}
            </span>
          </td>
          <td style="font-family: monospace; color: #fff; font-weight: 600; padding: 12px 14px;">${kodeTrx}</td>
          <td style="color: #cbd5e1; font-size: 0.85rem; padding: 12px 14px;">
            <span style="display: inline-flex; align-items: center; gap: 6px;">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#8297b0" stroke-width="2">
                <path d="M3 21h18"></path><path d="M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16"></path>
                <path d="M9 9h1"></path><path d="M9 13h1"></path><path d="M9 17h1"></path>
                <path d="M14 9h1"></path><path d="M14 13h1"></path><path d="M14 17h1"></path>
              </svg>
              ${ruanganStr}
            </span>
          </td>
          <td style="padding: 12px 14px;">
            <strong style="color: #00D4FF;">${totalLinen}</strong> <span style="font-size: 0.75rem; color: #8297b0;">pcs</span>
          </td>
          <td style="color: #94a3b8; font-size: 0.85rem; padding: 12px 14px;">${petugasStr}</td>
          <td style="padding: 12px 14px;">
            <span style="display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.7rem; font-weight: 700; background: rgba(0,208,132,0.15); color: #00D084; border: 1px solid rgba(0,208,132,0.3); text-transform: uppercase;">
              ${statusStr}
            </span>
          </td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    console.warn('loadDashboardActivityHistory gagal:', err);
    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #ef4444; padding: 14px;">Gagal memuat riwayat aktivitas.</td></tr>';
  }
}

  const refreshDashboard = async () => {
    const linen = await requestJson('/api/master/linen').catch(() => []);

    const totalLinenCount = linen.length;
    const linenMasukCount = linen.filter(item => item.status === 'dicuci' || item.status === 'tercatat').length;
    const linenKeluarCount = linen.filter(item => item.status === 'dipakai').length;

    // Top Cards
    const totalLinenEl = document.getElementById('total-linen');
    const statMasukEl = document.getElementById('stat-masuk');
    const statKeluarEl = document.getElementById('stat-keluar');

    if (totalLinenEl) totalLinenEl.textContent = totalLinenCount;
    if (statMasukEl) statMasukEl.textContent = linenMasukCount;
    if (statKeluarEl) statKeluarEl.textContent = linenKeluarCount;

    // Ringkasan Section
    const sumTotalEl = document.getElementById('summary-total');
    const sumMasukEl = document.getElementById('summary-masuk');
    const sumKeluarEl = document.getElementById('summary-keluar');
    const sumTotalSideEl = document.getElementById('summary-total-side');

    if (sumTotalEl) sumTotalEl.textContent = totalLinenCount;

    const calcPct = (val) => totalLinenCount > 0 ? Math.round((val / totalLinenCount) * 100) : 0;
    const masukPct = calcPct(linenMasukCount);
    const keluarPct = calcPct(linenKeluarCount);

    if (sumMasukEl) sumMasukEl.textContent = `${linenMasukCount} (${masukPct}%)`;
    if (sumKeluarEl) sumKeluarEl.textContent = `${linenKeluarCount} (${keluarPct}%)`;
    if (sumTotalSideEl) sumTotalSideEl.textContent = `${totalLinenCount} (100%)`;

    // Panggil metrik monitoring supplier (non-blocking)
    if (typeof loadSupplierDashboardMetrics === 'function') {
      loadSupplierDashboardMetrics().catch(() => {});
    }

    // Panggil riwayat aktivitas dashboard (non-blocking)
    if (typeof loadDashboardActivityHistory === 'function') {
      loadDashboardActivityHistory().catch(() => {});
    }
  };
  refreshDashboardGlobal = refreshDashboard;
  refreshDashboard();

  // Master data form handling
  document.getElementById('ruangan-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = Object.fromEntries(new FormData(form));
    const editId = payload.id;
    delete payload.id;

    if ('is_active' in payload) {
      payload.is_active = (payload.is_active === 'true' || payload.is_active === true);
    }

    if (!editId) {
      if (!payload.kode_ruangan || !payload.nama_ruangan) {
        notify('Kode Ruangan dan Nama Ruangan wajib diisi untuk menambah ruangan baru.', 'error');
        return;
      }
    } else {
      if (!payload.kode_ruangan) delete payload.kode_ruangan;
      if (!payload.nama_ruangan) delete payload.nama_ruangan;
    }

    try {
      if (editId) {
        await requestJson(`/api/master/ruangan/${editId}`, { method: 'PUT', body: JSON.stringify(payload) });
        notify('Data ruangan berhasil diperbarui.', 'success');
      } else {
        await requestJson('/api/master/ruangan', { method: 'POST', body: JSON.stringify(payload) });
        notify('Ruangan baru berhasil ditambahkan.', 'success');
      }
      form.reset();
      document.getElementById('ruangan-edit-id').value = '';
      const activeEl = document.getElementById('ruangan_is_active');
      if (activeEl) activeEl.value = 'true';
      document.getElementById('ruangan-submit-button').textContent = 'Simpan Ruangan';
      const cancelBtn = document.getElementById('cancel-ruangan-edit');
      if (cancelBtn) cancelBtn.style.display = 'none';
      await loadMasterData();
      refreshDashboard();
      if (typeof loadActiveRooms === 'function') loadActiveRooms();
    } catch (err) { notify(err.message, 'error'); }
  });

  document.addEventListener('click', async (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    // Ruangan actions
    const editBtn = target.closest('[data-action="edit-ruangan"]');
    const toggleStatusBtn = target.closest('[data-action="toggle-status-ruangan"]');
    const deleteBtn = target.closest('[data-action="delete-ruangan"]');

    if (editBtn) {
      const ruanganId = editBtn.getAttribute('data-id');
      try {
        const item = await requestJson(`/api/master/ruangan`);
        const ruanganItem = item.find(r => r.id == ruanganId);
        if (!ruanganItem) return;
        const form = document.getElementById('ruangan-form');
        if (!form) return;
        document.getElementById('ruangan-edit-id').value = ruanganItem.id;
        if (form.elements.namedItem('kode_ruangan')) form.elements.namedItem('kode_ruangan').value = ruanganItem.kode_ruangan;
        if (form.elements.namedItem('nama_ruangan')) form.elements.namedItem('nama_ruangan').value = ruanganItem.nama_ruangan;
        if (form.elements.namedItem('keterangan')) form.elements.namedItem('keterangan').value = ruanganItem.keterangan || '';
        const activeSelect = form.elements.namedItem('is_active') || document.getElementById('ruangan_is_active');
        if (activeSelect) {
          const isAct = (ruanganItem.is_active !== false && ruanganItem.is_active !== 0 && ruanganItem.is_active !== '0');
          activeSelect.value = isAct ? 'true' : 'false';
        }
        document.getElementById('ruangan-submit-button').textContent = 'Update Ruangan';
        document.getElementById('cancel-ruangan-edit').style.display = 'inline-block';
      } catch (err) { notify(err.message, 'error'); }
    }

    if (toggleStatusBtn) {
      const ruanganId = toggleStatusBtn.getAttribute('data-id');
      const targetActive = toggleStatusBtn.getAttribute('data-active') === 'true';
      const roomName = decodeURIComponent(toggleStatusBtn.getAttribute('data-name') || 'ruangan');
      const confirmMsg = targetActive
        ? `Aktifkan kembali ruangan '${roomName}'? Ruangan akan kembali muncul di dropdown pemilihan transaksi.`
        : `Nonaktifkan ruangan '${roomName}'? Ruangan tidak akan muncul di dropdown pemilihan transaksi.`;

      if (await showConfirm(confirmMsg)) {
        try {
          await requestJson(`/api/master/ruangan/${ruanganId}/status?is_active=${targetActive}`, {
            method: 'PATCH'
          });
          notify(`Ruangan '${roomName}' berhasil di${targetActive ? 'aktifkan' : 'nonaktifkan'}.`, 'success');
          await loadMasterData();
          refreshDashboard();
          if (typeof loadActiveRooms === 'function') loadActiveRooms();
        } catch (err) { notify(err.message, 'error'); }
      }
    }

    if (deleteBtn) {
      const ruanganId = deleteBtn.getAttribute('data-id');
      const roomName = decodeURIComponent(deleteBtn.getAttribute('data-name') || 'ruangan');
      if (await showConfirm(`Apakah Anda yakin ingin menonaktifkan ruangan '${roomName}'?`)) {
        try {
          await requestJson(`/api/master/ruangan/${ruanganId}`, { method: 'DELETE' });
          notify(`Ruangan '${roomName}' berhasil dinonaktifkan.`, 'success');
          await loadMasterData();
          refreshDashboard();
          if (typeof loadActiveRooms === 'function') loadActiveRooms();
        } catch (err) { notify(err.message, 'error'); }
      }
    }
  });

  // Hamburger Sidebar Toggle
  document.getElementById('btn-sidebar-toggle')?.addEventListener('click', () => {
    document.getElementById('sidebar')?.classList.toggle('collapsed');
  });

  // Custom Dropdown Toggle Logic
  document.addEventListener('click', (e) => {
    // Close all custom dropdowns if clicked outside
    document.querySelectorAll('.custom-dropdown').forEach(dropdown => {
      if (!dropdown.contains(e.target)) {
        dropdown.classList.remove('open');
      }
    });

    // Toggle the clicked custom dropdown
    const clickedDropdown = e.target.closest('.custom-dropdown');
    if (clickedDropdown) {
      // If an option was clicked, handle it
      const clickedOption = e.target.closest('.dropdown-option');
      if (clickedOption) {
        const val = clickedOption.getAttribute('data-value');
        const text = clickedOption.textContent;
        const selectedLabel = clickedDropdown.querySelector('.dropdown-selected');
        if (selectedLabel) selectedLabel.textContent = text;

        clickedDropdown.querySelectorAll('.dropdown-option').forEach(o => o.classList.remove('selected'));
        clickedOption.classList.add('selected');

        // Find associated hidden input and update it
        const targetId = clickedDropdown.getAttribute('data-target');
        const hiddenInput = targetId
          ? document.getElementById(targetId)
          : clickedDropdown.parentElement.querySelector('input[type="hidden"]');
        if (hiddenInput) {
          hiddenInput.value = val;
          hiddenInput.dispatchEvent(new Event('change', { bubbles: true }));
          hiddenInput.dispatchEvent(new Event('input', { bubbles: true }));
        }
        clickedDropdown.classList.remove('open');
      } else {
        // Close other dropdowns first
        document.querySelectorAll('.custom-dropdown.open').forEach(dd => {
          if (dd !== clickedDropdown) dd.classList.remove('open');
        });
        clickedDropdown.classList.toggle('open');
      }
    }
  });

  // Keyboard navigation for custom dropdowns
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      const activeEl = document.activeElement;
      if (activeEl && activeEl.classList.contains('custom-dropdown')) {
        e.preventDefault();
        activeEl.classList.toggle('open');
      }
    } else if (e.key === 'Escape') {
      document.querySelectorAll('.custom-dropdown.open').forEach(dd => dd.classList.remove('open'));
    }
  });

  // Master Data Tabs Switching
  document.querySelectorAll('.master-tab-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      document.querySelectorAll('.master-tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.master-tab-content').forEach(c => c.style.display = 'none');
      btn.classList.add('active');
      const target = btn.getAttribute('data-target');
      const el = document.getElementById(target);
      if (el) el.style.display = 'block';
    });
  });

  // Settings Tabs Switching
  document.querySelectorAll('.setting-tab-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      document.querySelectorAll('.setting-tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.setting-tab-content').forEach(c => c.style.display = 'none');
      btn.classList.add('active');
      const target = btn.getAttribute('data-target');
      const el = document.getElementById(target);
      if (el) el.style.display = 'block';
      if (target === 'setting-tab-log') {
        loadSettingLog();
      }
    });
  });

  // URL query parameter tab sync
  const urlParams = new URLSearchParams(window.location.search);
  const tabParam = urlParams.get('tab');
  if (tabParam) {
    if (window.location.pathname.includes('/laundry')) {
      const matchingBtn = document.querySelector(`.tab-btn[data-target="tab-${tabParam}"]`);
      if (matchingBtn) matchingBtn.click();
    } else if (window.location.pathname.includes('/settings')) {
      const targetId = tabParam === 'sync' ? 'setting-tab-sync' : (tabParam === 'log' ? 'setting-tab-log' : `setting-tab-${tabParam}`);
      const matchingBtn = document.querySelector(`.setting-tab-btn[data-target="${targetId}"]`);
      if (matchingBtn) matchingBtn.click();
      if (tabParam === 'log') {
        loadSettingLog();
      }
    }

    // Update sidebar sub-item active state
    const matchingSubNav = document.getElementById(`sub-nav-${tabParam}`);
    if (matchingSubNav) {
      document.querySelectorAll('.sub-item').forEach(el => el.classList.remove('active'));
      matchingSubNav.classList.add('active');
    }
  }

  // Test Connection button
  document.getElementById('btn-test-connection')?.addEventListener('click', async () => {
    notify('Memeriksa koneksi reader RFID...', 'info');
    await initRfidPortWidget();
  });

  try { renderDashboardEmptyTable(); } catch (_) {}
  try { initHeaderWidgets(); } catch (err) { console.warn("initHeaderWidgets error:", err); }
});

// ============================================================================
// Header Widgets: Notifications Panel & Hospital Account Profile Popover
// ============================================================================

function getHospitalInitial(hospitalName) {
  if (!hospitalName || typeof hospitalName !== 'string') return 'A';
  let cleaned = hospitalName.replace(/^(RSUD|RSU|RS|RUMAH\s+SAKIT)\b[\s.]*/i, '').trim();
  cleaned = cleaned.replace(/^(DR|DOKTER)\b[\s.]*/i, '').trim();
  if (cleaned.length > 0) {
    return cleaned.charAt(0).toUpperCase();
  }
  return hospitalName.trim().charAt(0).toUpperCase() || 'A';
}

function escapeNotifHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function formatNotificationTime(isoString) {
  if (!isoString) return '-';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    return d.toLocaleString('id-ID', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit'
    });
  } catch (_) {
    return isoString;
  }
}

async function loadUserHeaderProfile() {
  try {
    const res = await fetch('/api/auth/me', {
      credentials: 'same-origin',
      headers: { 'X-ClientS-Request': '1' }
    });
    if (!res.ok) return;
    const data = await res.json();
    if (data.status !== 'ok') return;

    const user = data.user || {};
    const hospital = data.hospital || {};
    const hospitalName = hospital.nama_rs || 'Rumah Sakit';
    const initial = getHospitalInitial(hospitalName);

    // Update avatar trigger button
    document.querySelectorAll('.user-avatar').forEach(el => {
      el.textContent = initial;
      el.title = `${hospitalName} (${user.email || 'Admin'})`;
    });

    // Update inside profile dropdown if present
    const profileInitialEl = document.getElementById('profile-avatar-initial');
    if (profileInitialEl) profileInitialEl.textContent = initial;

    const profileRsNameEl = document.getElementById('profile-hospital-name');
    if (profileRsNameEl) profileRsNameEl.textContent = hospitalName;

    const profileRsCodeEl = document.getElementById('profile-hospital-code');
    if (profileRsCodeEl) profileRsCodeEl.textContent = hospital.kode_rs || `RS-${hospital.id || ''}`;

    const profileEmailEl = document.getElementById('profile-user-email');
    if (profileEmailEl) profileEmailEl.textContent = user.email || '-';

    const profileRoleEl = document.getElementById('profile-user-role');
    if (profileRoleEl) profileRoleEl.textContent = (user.role || 'Administrator').toUpperCase();

    const profileRsIdEl = document.getElementById('profile-hospital-id');
    if (profileRsIdEl) profileRsIdEl.textContent = hospital.id ? `#${hospital.id}` : '-';

  } catch (err) {
    console.warn('loadUserHeaderProfile gagal:', err);
  }
}

let lastNotificationCount = null;

async function loadHeaderNotifications(isManualClick = false) {
  const notifDot = document.querySelector('.header-right .notification-dot');
  const countBadge = document.getElementById('notif-unread-count-badge');
  const notifBody = document.getElementById('header-notif-body');

  try {
    const res = await fetch('/api/receiving/notifications', {
      credentials: 'same-origin',
      headers: { 'X-ClientS-Request': '1' }
    });

    if (!res.ok) {
      if (notifBody && isManualClick) {
        notifBody.innerHTML = `
          <div class="notif-empty">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#f87171" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
            <span>Gagal memuat notifikasi cloud. Silakan coba lagi.</span>
          </div>`;
      }
      return;
    }

    const data = await res.json();
    const packages = data.packages || [];
    const unread = typeof data.unread_count === 'number' ? data.unread_count : packages.filter(p => p.status === 'pending').length;

    // Update red notification badge dot on the bell icon
    if (notifDot) {
      if (unread > 0) {
        notifDot.style.display = 'flex';
        notifDot.textContent = unread > 99 ? '99+' : unread;
      } else {
        notifDot.style.display = 'none';
        notifDot.textContent = '0';
      }
    }

    // Update badge in dropdown header
    if (countBadge) {
      countBadge.textContent = `${unread} Menunggu`;
    }

    // Play a gentle notification toast if a new shipment arrived while user is active
    if (lastNotificationCount !== null && unread > lastNotificationCount) {
      notify(`Ada ${unread - lastNotificationCount} pengiriman linen baru dari supplier!`, 'info', 6000);
    }
    lastNotificationCount = unread;

    // Render list inside notifBody
    if (!notifBody) return;

    if (packages.length === 0) {
      notifBody.innerHTML = `
        <div class="notif-empty">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="opacity: 0.5;">
            <path d="M22 12h-6l-2 3h-4l-2-3H2"></path>
            <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"></path>
          </svg>
          <span>Belum ada pengiriman linen masuk dari supplier.</span>
        </div>`;
      return;
    }

    notifBody.innerHTML = packages.map(pkg => {
      const isPending = pkg.status === 'pending';
      const statusLabel = isPending ? 'Menunggu Diterima' : 'Sudah Diterima';
      const statusClass = isPending ? 'pending' : 'confirmed';
      const timeStr = formatNotificationTime(pkg.created_at);
      const itemCount = pkg.item_count || (pkg.items ? pkg.items.length : 0);
      const verifCode = pkg.verification_code || '-';

      return `
        <div class="notif-item">
          <div class="notif-item-top">
            <span class="notif-pkg-status ${statusClass}">${statusLabel}</span>
            <span class="notif-time">${escapeNotifHtml(timeStr)}</span>
          </div>
          <div class="notif-pkg-code" title="${escapeNotifHtml(pkg.kode_pengiriman || '')}">
            ${escapeNotifHtml(pkg.kode_pengiriman || 'PAKET PENGIRIMAN')}
          </div>
          <div class="notif-pkg-desc">
            ${itemCount} Item Linen ${pkg.catatan ? ' &bull; ' + escapeNotifHtml(pkg.catatan) : ''}
          </div>
          <div class="notif-code-box">
            <div>
              <div style="font-size: 0.68rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">Kode Verifikasi / Penerimaan:</div>
              <div class="notif-code-val">${escapeNotifHtml(verifCode)}</div>
            </div>
            <div class="notif-code-actions">
              <button type="button" class="btn-notif-copy" data-code="${escapeNotifHtml(verifCode)}" title="Salin Kode Verifikasi">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                </svg>
                <span>Salin</span>
              </button>
              ${isPending ? `
              <button type="button" class="btn-notif-use" data-code="${escapeNotifHtml(verifCode)}" title="Terima Paket Ini di Menu Sync">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                <span>Terima</span>
              </button>
              ` : ''}
            </div>
          </div>
        </div>
      `;
    }).join('');

    // Attach click events for "Salin" (copy)
    notifBody.querySelectorAll('.btn-notif-copy').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const code = btn.getAttribute('data-code');
        if (!code || code === '-') return;
        try {
          await navigator.clipboard.writeText(code);
          notify(`Kode verifikasi ${code} disalin ke clipboard!`, 'success');
        } catch (_) {
          prompt('Salin kode verifikasi pengiriman:', code);
        }
      });
    });

    // Attach click events for "Terima" (auto fill & sync)
    notifBody.querySelectorAll('.btn-notif-use').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const code = btn.getAttribute('data-code');
        if (!code || code === '-') return;

        // Close dropdown
        const dropdown = document.getElementById('header-notification-dropdown');
        if (dropdown) dropdown.classList.remove('active');

        if (window.location.pathname.includes('/settings')) {
          // Switch to sync tab
          const syncTabBtn = document.querySelector('.setting-tab-btn[data-target="setting-tab-sync"]');
          if (syncTabBtn && !syncTabBtn.classList.contains('active')) {
            syncTabBtn.click();
          }
          const verifInput = document.getElementById('input-verif-code');
          if (verifInput) {
            verifInput.value = code;
            verifInput.focus();
            verifInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
            if (typeof fetchPackageByVerificationCode === 'function') {
              notify(`Memuat paket verifikasi ${code}...`, 'info');
              setTimeout(() => { fetchPackageByVerificationCode(); }, 200);
            }
          }
        } else {
          // Redirect to settings sync tab with code parameter
          window.location.href = `/settings?tab=sync&code=${encodeURIComponent(code)}`;
        }
      });
    });

  } catch (err) {
    console.warn('loadHeaderNotifications gagal:', err);
  }
}

function initHeaderWidgets() {
  const headerRight = document.querySelector('.top-header .header-right, header .header-right');
  if (!headerRight) return;

  const notifBtn = headerRight.querySelector('.header-icon-btn[title="Notifikasi"], .header-icon-btn');
  const userAvatar = headerRight.querySelector('.user-avatar');

  // Ensure notification dropdown exists
  let notifDropdown = document.getElementById('header-notification-dropdown');
  if (!notifDropdown) {
    notifDropdown = document.createElement('div');
    notifDropdown.id = 'header-notification-dropdown';
    notifDropdown.className = 'header-dropdown-panel';
    notifDropdown.innerHTML = `
      <div class="notif-header">
        <div class="notif-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
            <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
          </svg>
          <span>Notifikasi Pengiriman</span>
          <span class="notif-badge" id="notif-unread-count-badge">0 Menunggu</span>
        </div>
        <button type="button" class="notif-refresh-btn" id="btn-refresh-notifications" title="Segarkan Data Notifikasi">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M23 4v6h-6"></path>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
          </svg>
        </button>
      </div>
      <div class="notif-body" id="header-notif-body">
        <div class="notif-empty">Memuat notifikasi pengiriman...</div>
      </div>
    `;
    headerRight.appendChild(notifDropdown);
  }

  // Ensure user profile dropdown exists
  let profileDropdown = document.getElementById('header-user-profile-dropdown');
  if (!profileDropdown) {
    profileDropdown = document.createElement('div');
    profileDropdown.id = 'header-user-profile-dropdown';
    profileDropdown.className = 'header-dropdown-panel';
    profileDropdown.innerHTML = `
      <div class="profile-card-header">
        <div class="profile-avatar-lg" id="profile-avatar-initial">A</div>
        <div class="profile-rs-name" id="profile-hospital-name">Memuat...</div>
        <div class="profile-rs-code" id="profile-hospital-code">RS-ID</div>
      </div>
      <div class="profile-card-body">
        <div class="profile-info-row">
          <span>Akun Pengguna</span>
          <strong id="profile-user-email">-</strong>
        </div>
        <div class="profile-info-row">
          <span>Role / Akses</span>
          <strong id="profile-user-role">-</strong>
        </div>
        <div class="profile-info-row">
          <span>ID Rumah Sakit</span>
          <strong id="profile-hospital-id">-</strong>
        </div>
      </div>
      <div class="profile-card-footer">
        <button type="button" class="btn-profile-logout" id="btn-header-logout">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
            <polyline points="16 17 21 12 16 7"></polyline>
            <line x1="21" y1="12" x2="9" y2="12"></line>
          </svg>
          <span>Keluar (Logout)</span>
        </button>
      </div>
    `;
    headerRight.appendChild(profileDropdown);
  }

  // Notification button click handler
  if (notifBtn) {
    notifBtn.style.cursor = 'pointer';
    notifBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (profileDropdown) profileDropdown.classList.remove('active');
      const willOpen = !notifDropdown.classList.contains('active');
      notifDropdown.classList.toggle('active');
      if (willOpen) {
        loadHeaderNotifications(true);
      }
    });
  }

  // Refresh notifications inside dropdown
  const refreshBtn = document.getElementById('btn-refresh-notifications');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      loadHeaderNotifications(true);
    });
  }

  // Avatar click handler
  if (userAvatar) {
    userAvatar.style.cursor = 'pointer';
    userAvatar.addEventListener('click', (e) => {
      e.stopPropagation();
      if (notifDropdown) notifDropdown.classList.remove('active');
      profileDropdown.classList.toggle('active');
    });
  }

  // Logout button click handler
  const logoutBtn = document.getElementById('btn-header-logout');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!confirm('Apakah Anda yakin ingin keluar dari sistem?')) return;
      try {
        await fetch('/api/auth/logout', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'X-ClientS-Request': '1' }
        });
      } catch (_) {}
      window.location.href = '/login';
    });
  }

  // Close dropdowns when clicking outside
  document.addEventListener('click', (e) => {
    if (notifDropdown && notifDropdown.classList.contains('active')) {
      if (!notifDropdown.contains(e.target) && (!notifBtn || !notifBtn.contains(e.target))) {
        notifDropdown.classList.remove('active');
      }
    }
    if (profileDropdown && profileDropdown.classList.contains('active')) {
      if (!profileDropdown.contains(e.target) && (!userAvatar || !userAvatar.contains(e.target))) {
        profileDropdown.classList.remove('active');
      }
    }
  });

  // Initial load
  loadUserHeaderProfile();
  loadHeaderNotifications(false);

  // Setup periodic polling every 12 seconds for real-time shipment updates
  if (!window._notifPollTimer) {
    window._notifPollTimer = setInterval(() => {
      loadHeaderNotifications(false);
    }, 12000);
  }
}

