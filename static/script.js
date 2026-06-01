let _ragChatDefaults = {top_k: 5, min_score: 0, max_citations: 5};
let currentSources = [];
let currentCitations = [];
let currentChatId = null;
let isProcessing = false;
let currentAuth = {authenticated: false, role: 'guest', user: null};
const SOURCE_REFERENCE_PATTERN = /\[Источник:\s*([^\]]+)\]/g;
let _mermaidInitialized = false;
let _mermaidLightbox = null;
let _mermaidLightboxCurrentSvg = null;

const messagesContainer = document.getElementById('messages');
const messageForm = document.getElementById('messageForm');
const messageInput = document.getElementById('messageInput');
const sendButton = document.getElementById('sendButton');
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const sourcesPanel = document.getElementById('sourcesPanel');
const sourcesList = document.getElementById('sourcesList');
const closeSources = document.getElementById('closeSources');
const sidebarNewChatBtn = document.getElementById('sidebarNewChatBtn');
const ragAdvancedToggle = document.getElementById('ragAdvancedToggle');
const ragAdvancedPanel = document.getElementById('ragAdvancedPanel');
const clearChatsBtn = document.getElementById('clearChatsBtn');
const chatList = document.getElementById('chatList');
const chatSearchInput = document.getElementById('chatSearchInput');
const answerModeSelect = document.getElementById('answerModeSelect');
const topKInput = document.getElementById('topKInput');
const minScoreInput = document.getElementById('minScoreInput');
const exportChatBtn = document.getElementById('exportChatBtn');
const uploadForm = document.getElementById('uploadForm');
const documentFileInput = document.getElementById('documentFileInput');
const documentsList = document.getElementById('documentsList');
const refreshDocumentsBtn = document.getElementById('refreshDocumentsBtn');
const previewDocumentBtn = document.getElementById('previewDocumentBtn');
const reindexBtn = document.getElementById('reindexBtn');
const jobStatus = document.getElementById('jobStatus');
const indexPreview = document.getElementById('indexPreview');
const refreshAdminBtn = document.getElementById('refreshAdminBtn');
const adminOverview = document.getElementById('adminOverview');
const adminSettings = document.getElementById('adminSettings');
const adminSettingsSearch = document.getElementById('adminSettingsSearch');
const refreshAdminSettingsBtn = document.getElementById('refreshAdminSettingsBtn');
const saveAdminSettingsDraftBtn = document.getElementById('saveAdminSettingsDraftBtn');
const resetAdminSettingsDraftBtn = document.getElementById('resetAdminSettingsDraftBtn');
const adminSettingsDraftInfo = document.getElementById('adminSettingsDraftInfo');
const adminOverviewTab = document.getElementById('adminOverviewTab');
const adminSettingsTab = document.getElementById('adminSettingsTab');
const authStatus = document.getElementById('authStatus');
const authOpenBtn = document.getElementById('authOpenBtn');
const logoutBtn = document.getElementById('logoutBtn');
const authModal = document.getElementById('authModal');
const authBackdrop = document.getElementById('authBackdrop');
const authCloseBtn = document.getElementById('authCloseBtn');
const loginTabBtn = document.getElementById('loginTabBtn');
const registerTabBtn = document.getElementById('registerTabBtn');
const loginForm = document.getElementById('loginForm');
const registerForm = document.getElementById('registerForm');
const loginIdentifier = document.getElementById('loginIdentifier');
const loginPassword = document.getElementById('loginPassword');
const registerUsername = document.getElementById('registerUsername');
const registerEmail = document.getElementById('registerEmail');
const registerPassword = document.getElementById('registerPassword');
const authMessage = document.getElementById('authMessage');
const assistantAvatarSrc = '/static/img/assistant-avatar.svg';

function createMessageAvatar(type) {
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';

    if (type === 'bot') {
        const image = document.createElement('img');
        image.src = assistantAvatarSrc;
        image.alt = 'AI-ассистент';
        avatar.appendChild(image);
    } else {
        avatar.textContent = 'Вы';
    }

    return avatar;
}

function ensureMermaidInitialized() {
    if (typeof mermaid === 'undefined') {
        return false;
    }
    if (_mermaidInitialized) {
        return true;
    }
    const theme = document.documentElement?.getAttribute('data-theme') === 'dark' ? 'dark' : 'default';
    try {
        mermaid.initialize({
            startOnLoad: false,
            securityLevel: 'strict',
            // Не даём Mermaid рисовать "бомбу" при ошибках синтаксиса — покажем fallback сами.
            suppressErrorRendering: true,
            theme,
        });
        _mermaidInitialized = true;
        return true;
    } catch (_) {
        return false;
    }
}

function looksLikeMermaid(codeText) {
    const text = String(codeText || '').trim();
    if (!text) return false;
    return (
        text.startsWith('graph ') ||
        text.startsWith('flowchart ') ||
        text.startsWith('sequenceDiagram') ||
        text.startsWith('classDiagram') ||
        text.startsWith('stateDiagram') ||
        text.startsWith('erDiagram') ||
        text.startsWith('journey') ||
        text.startsWith('gantt') ||
        text.startsWith('mindmap') ||
        text.startsWith('timeline') ||
        text.startsWith('quadrantChart') ||
        text.startsWith('sankey-beta')
    );
}

function replaceMermaidBlocksWithPlaceholder(container) {
    if (!container) return;
    const blocks = container.querySelectorAll('pre > code');
    blocks.forEach((codeEl) => {
        if (!(codeEl instanceof HTMLElement)) return;
        const pre = codeEl.parentElement;
        if (!pre || pre.tagName.toLowerCase() !== 'pre') return;

        const className = (codeEl.className || '').toLowerCase();
        const codeText = codeEl.textContent || '';
        const isMermaidBlock = className.includes('language-mermaid') || className.includes('lang-mermaid') || looksLikeMermaid(codeText);
        if (!isMermaidBlock) return;

        const ph = document.createElement('div');
        ph.className = 'mermaid-placeholder';
        ph.innerHTML = '<span class="mermaid-placeholder__spinner" aria-hidden="true"></span><span class="mermaid-placeholder__text">Формирование диаграммы…</span>';
        pre.replaceWith(ph);
    });
}

function renderMermaidIn(container) {
    if (!container || !ensureMermaidInitialized()) {
        return;
    }
    const blocks = container.querySelectorAll('pre > code');
    const nodesToRender = [];
    const nodesRawText = new Map();

    blocks.forEach((codeEl) => {
        if (!(codeEl instanceof HTMLElement)) return;
        const pre = codeEl.parentElement;
        if (!pre || pre.tagName.toLowerCase() !== 'pre') return;
        if (pre.getAttribute('data-mermaid-processed') === '1') return;

        const className = (codeEl.className || '').toLowerCase();
        const codeText = codeEl.textContent || '';
        const isMermaidBlock = className.includes('language-mermaid') || className.includes('lang-mermaid') || looksLikeMermaid(codeText);
        if (!isMermaidBlock) return;

        const mermaidDiv = document.createElement('div');
        mermaidDiv.className = 'mermaid';
        const raw = codeText.trim();
        mermaidDiv.textContent = raw;
        pre.replaceWith(mermaidDiv);
        pre.setAttribute('data-mermaid-processed', '1');
        nodesToRender.push(mermaidDiv);
        nodesRawText.set(mermaidDiv, raw);
    });

    if (!nodesToRender.length) {
        return;
    }

    // Рендерим каждый блок отдельно и перехватываем ошибки сами.
    // Важно: mermaid.run/init иногда НЕ бросают исключение и рисуют "error diagram" в DOM.
    // Поэтому по возможности используем mermaid.render(...) и управляем результатом вручную.
    nodesToRender.forEach((node, idx) => {
        const raw = nodesRawText.get(node) || node.textContent || '';
        const renderId = `mmd-${Date.now()}-${Math.random().toString(16).slice(2)}-${idx}`;

        const fallback = () => {
            node.classList.add('mermaid-error');
            node.innerHTML = `<pre class="mermaid-error__pre"><code>${escapeHtml(raw)}</code></pre>`;
        };

        try {
            if (typeof mermaid.render === 'function') {
                const maybe = mermaid.render(renderId, raw);
                Promise.resolve(maybe)
                    .then((res) => {
                        const svg = res && (res.svg || res);
                        if (typeof svg !== 'string' || !svg.trim().startsWith('<svg')) {
                            fallback();
                            return;
                        }
                        node.classList.remove('mermaid-error');
                        node.innerHTML = svg;
                    })
                    .catch(() => fallback());
                return;
            }

            // Fallback для старых API: всё равно оборачиваем в try/catch + suppressErrorRendering.
            if (typeof mermaid.run === 'function') {
                mermaid.run({nodes: [node]});
            } else if (typeof mermaid.init === 'function') {
                mermaid.init(undefined, [node]);
            } else {
                fallback();
            }
        } catch (_) {
            fallback();
        }
    });
}

function ensureMermaidLightbox() {
    if (_mermaidLightbox) {
        return _mermaidLightbox;
    }

    const root = document.createElement('div');
    root.className = 'mermaid-lightbox';
    root.hidden = true;
    root.innerHTML = `
        <div class="mermaid-lightbox__backdrop" data-mermaid-lightbox-close="1"></div>
        <div class="mermaid-lightbox__dialog" role="dialog" aria-modal="true" aria-label="Диаграмма Mermaid">
            <div class="mermaid-lightbox__header">
                <div class="mermaid-lightbox__header-left">
                    <div class="mermaid-lightbox__title">Mermaid diagram</div>
                    <div class="mermaid-lightbox__toolbar" role="toolbar" aria-label="Инструменты диаграммы">
                        <button class="mermaid-lightbox__toolbtn" type="button" data-mermaid-zoom="in">+</button>
                        <button class="mermaid-lightbox__toolbtn" type="button" data-mermaid-zoom="out">−</button>
                        <button class="mermaid-lightbox__toolbtn" type="button" data-mermaid-zoom="reset">Сброс</button>
                        <span class="mermaid-lightbox__zoomlabel" data-mermaid-zoom-label="1">100%</span>
                        <button class="mermaid-lightbox__toolbtn" type="button" data-mermaid-fullscreen="toggle">На весь экран</button>
                        <button class="mermaid-lightbox__toolbtn" type="button" data-mermaid-download="svg">Скачать SVG</button>
                    </div>
                </div>
                <button class="mermaid-lightbox__close" type="button" aria-label="Закрыть" data-mermaid-lightbox-close="1">×</button>
            </div>
            <div class="mermaid-lightbox__body" id="mermaidLightboxBody"></div>
        </div>
    `;

    root.addEventListener('click', (evt) => {
        const t = evt.target;
        if (!(t instanceof HTMLElement)) return;
        if (t.getAttribute('data-mermaid-lightbox-close') === '1') {
            closeMermaidLightbox();
        }
    });

    // Делегируем клики тулбара здесь, чтобы обработчики не терялись между открытиями.
    root.addEventListener('click', async (evt) => {
        const t = evt.target;
        if (!(t instanceof HTMLElement)) return;

        if (t.getAttribute('data-mermaid-fullscreen') === 'toggle') {
            const dialog = root.querySelector('.mermaid-lightbox__dialog');
            if (dialog instanceof HTMLElement) {
                try {
                    if (document.fullscreenElement) {
                        await document.exitFullscreen();
                    } else if (typeof dialog.requestFullscreen === 'function') {
                        await dialog.requestFullscreen();
                    }
                } catch (e) {
                    console.error('Fullscreen toggle failed', e);
                }
            }
            return;
        }

        const downloadKind = t.getAttribute('data-mermaid-download');
        if (downloadKind !== 'svg') return;

        const btn = t;
        const svg = _mermaidLightboxCurrentSvg;
        if (!(svg instanceof SVGSVGElement)) return;

        const prevText = btn.textContent;
        btn.setAttribute('disabled', 'disabled');
        btn.textContent = 'Готовлю…';
        try {
            downloadSvg(svg, 'mermaid-diagram');
        } catch (e) {
            console.error('Mermaid download failed', e);
            alert('Не удалось сохранить файл. Откройте DevTools → Console и пришлите ошибку.');
        } finally {
            btn.removeAttribute('disabled');
            btn.textContent = prevText || 'Скачать SVG';
        }
    });

    document.addEventListener('keydown', (evt) => {
        if (evt.key === 'Escape') {
            closeMermaidLightbox();
        }
    });

    document.body.appendChild(root);
    _mermaidLightbox = root;
    return root;
}

function setupMermaidLightboxInteractions(root, viewport, content) {
    if (!root || !viewport || !content) return;

    let scale = 1;
    let panX = 0;
    let panY = 0;
    let dragging = false;
    let startX = 0;
    let startY = 0;
    let startPanX = 0;
    let startPanY = 0;

    const zoomLabel = root.querySelector('[data-mermaid-zoom-label]');

    const apply = () => {
        content.style.transform = `translate(${panX}px, ${panY}px) scale(${scale})`;
        if (zoomLabel) {
            zoomLabel.textContent = `${Math.round(scale * 100)}%`;
        }
    };

    const clamp = (v, min, max) => Math.min(max, Math.max(min, v));
    const setScale = (next, anchorClientX, anchorClientY) => {
        const prev = scale;
        scale = clamp(next, 0.2, 6);
        if (scale === prev) return;

        const rect = viewport.getBoundingClientRect();
        const ax = anchorClientX != null ? anchorClientX - rect.left : rect.width / 2;
        const ay = anchorClientY != null ? anchorClientY - rect.top : rect.height / 2;

        // Сохраняем точку под курсором при зуме.
        panX = ax - (ax - panX) * (scale / prev);
        panY = ay - (ay - panY) * (scale / prev);
        apply();
    };

    const reset = () => {
        scale = 1;
        panX = 0;
        panY = 0;
        apply();
    };

    const fitToViewport = (contentWidth, contentHeight) => {
        const rect = viewport.getBoundingClientRect();
        const vw = rect.width || 1;
        const vh = rect.height || 1;
        const cw = Math.max(1, Number(contentWidth) || 1);
        const ch = Math.max(1, Number(contentHeight) || 1);
        const nextScale = clamp(Math.min(vw / cw, vh / ch) * 0.96, 0.2, 6);
        scale = nextScale;
        panX = (vw - cw * scale) / 2;
        panY = (vh - ch * scale) / 2;
        apply();
    };

    // Drag to pan
    viewport.addEventListener('mousedown', (evt) => {
        if (evt.button !== 0) return;
        dragging = true;
        viewport.classList.add('is-dragging');
        startX = evt.clientX;
        startY = evt.clientY;
        startPanX = panX;
        startPanY = panY;
        evt.preventDefault();
    });
    document.addEventListener('mousemove', (evt) => {
        if (!dragging) return;
        panX = startPanX + (evt.clientX - startX);
        panY = startPanY + (evt.clientY - startY);
        apply();
    });
    document.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        viewport.classList.remove('is-dragging');
    });

    // Wheel zoom (Ctrl optional not required)
    viewport.addEventListener('wheel', (evt) => {
        evt.preventDefault();
        const delta = evt.deltaY;
        const factor = delta > 0 ? 0.9 : 1.1;
        setScale(scale * factor, evt.clientX, evt.clientY);
    }, {passive: false});

    // Toolbar buttons
    root.addEventListener('click', (evt) => {
        const t = evt.target;
        if (!(t instanceof HTMLElement)) return;
        const z = t.getAttribute('data-mermaid-zoom');
        if (z === 'in') setScale(scale * 1.2);
        if (z === 'out') setScale(scale / 1.2);
        if (z === 'reset') reset();
    });

    apply();
    return {reset, apply, fitToViewport, getState: () => ({scale, panX, panY})};
}

function downloadSvg(svgEl, filenameBase = 'diagram') {
    if (!(svgEl instanceof SVGSVGElement)) return;
    const svgText = new XMLSerializer().serializeToString(svgEl);
    const blob = new Blob([svgText], {type: 'image/svg+xml;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${filenameBase}.svg`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
}

function openMermaidLightboxFromSvg(svg) {
    if (!(svg instanceof SVGSVGElement)) {
        return;
    }
    const root = ensureMermaidLightbox();
    const body = root.querySelector('#mermaidLightboxBody');
    if (!body) {
        return;
    }

    body.innerHTML = '';
    const viewport = document.createElement('div');
    viewport.className = 'mermaid-lightbox__viewport';
    const content = document.createElement('div');
    content.className = 'mermaid-lightbox__content';
    viewport.appendChild(content);
    body.appendChild(viewport);

    const clone = svg.cloneNode(true);
    if (clone instanceof SVGSVGElement) {
        // Гарантируем корректные размеры/viewport, иначе SVG может "схлопнуться" в lightbox.
        let vb = clone.viewBox?.baseVal;
        if (!vb || !vb.width || !vb.height) {
            const srcVb = svg.viewBox?.baseVal;
            if (srcVb && srcVb.width && srcVb.height) {
                clone.setAttribute('viewBox', `${srcVb.x} ${srcVb.y} ${srcVb.width} ${srcVb.height}`);
            } else {
                try {
                    const box = svg.getBBox();
                    const w = Math.max(1, Math.round(box.width));
                    const h = Math.max(1, Math.round(box.height));
                    clone.setAttribute('viewBox', `0 0 ${w} ${h}`);
                } catch (_) {
                    // fallback: стандартный размер
                    clone.setAttribute('viewBox', '0 0 1200 800');
                }
            }
        }
        vb = clone.viewBox.baseVal;
        clone.setAttribute('width', String(Math.max(1, Math.round(vb.width))));
        clone.setAttribute('height', String(Math.max(1, Math.round(vb.height))));
    }
    content.appendChild(clone);
    _mermaidLightboxCurrentSvg = clone instanceof SVGSVGElement ? clone : null;

    // Зум/панорамирование
    const controller = setupMermaidLightboxInteractions(root, viewport, content);
    // Авто-fit после вставки в DOM (нужны реальные размеры viewport).
    requestAnimationFrame(() => {
        if (!controller) return;
        const svgInside = content.querySelector('svg');
        if (!(svgInside instanceof SVGSVGElement)) return;
        const vb = svgInside.viewBox?.baseVal;
        const w = vb && vb.width ? vb.width : svgInside.getBoundingClientRect().width;
        const h = vb && vb.height ? vb.height : svgInside.getBoundingClientRect().height;
        controller.fitToViewport(w, h);
    });

    // Скачивание JPG обрабатывается делегированием в ensureMermaidLightbox().

    root.hidden = false;
    document.body.classList.add('mermaid-lightbox-open');
}

function closeMermaidLightbox() {
    const root = _mermaidLightbox;
    if (!root || root.hidden) {
        return;
    }
    root.hidden = true;
    document.body.classList.remove('mermaid-lightbox-open');
    const body = root.querySelector('#mermaidLightboxBody');
    if (body) {
        body.innerHTML = '';
    }
    _mermaidLightboxCurrentSvg = null;
}

function initMermaidLightboxClicks() {
    document.addEventListener('click', (evt) => {
        const target = evt.target;
        if (!(target instanceof Element)) return;

        // Ищем клик по SVG, который находится внутри div.mermaid (рендер Mermaid)
        const svg = target.closest?.('.mermaid svg');
        if (!(svg instanceof SVGSVGElement)) return;

        // Не мешаем, если пользователь кликает по ссылке внутри сообщения (на всякий случай)
        const link = target.closest?.('a');
        if (link) return;

        evt.preventDefault();
        evt.stopPropagation();
        openMermaidLightboxFromSvg(svg);
    });
}

document.addEventListener('DOMContentLoaded', () => {
    initializeAuth();
    checkHealth();
    loadChats();
    syncRagToolbarDefaults();
    setInterval(checkHealth, 30000);

    messageForm.addEventListener('submit', handleSubmit);
    closeSources.addEventListener('click', closeSourcesPanel);
    if (sidebarNewChatBtn) {
        sidebarNewChatBtn.addEventListener('click', startNewChat);
    }
    if (ragAdvancedToggle && ragAdvancedPanel) {
        ragAdvancedToggle.addEventListener('click', () => {
            const open = ragAdvancedPanel.hidden;
            ragAdvancedPanel.hidden = !open;
            ragAdvancedToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
    }
    clearChatsBtn.addEventListener('click', clearAllChats);
    chatSearchInput.addEventListener('input', debounce(() => loadChats(chatSearchInput.value.trim()), 250));
    exportChatBtn.addEventListener('click', exportCurrentChat);
    refreshDocumentsBtn.addEventListener('click', loadDocuments);
    previewDocumentBtn.addEventListener('click', previewDocument);
    reindexBtn.addEventListener('click', startReindex);
    uploadForm.addEventListener('submit', uploadDocument);
    refreshAdminBtn.addEventListener('click', loadAdminOverview);
    if (refreshAdminSettingsBtn) {
        refreshAdminSettingsBtn.addEventListener('click', loadAdminSettings);
    }
    if (saveAdminSettingsDraftBtn) {
        saveAdminSettingsDraftBtn.addEventListener('click', saveAdminSettingsDraft);
    }
    if (resetAdminSettingsDraftBtn) {
        resetAdminSettingsDraftBtn.addEventListener('click', resetAdminSettingsDraft);
    }
    authOpenBtn.addEventListener('click', () => openAuthModal('login'));
    logoutBtn.addEventListener('click', logout);
    authBackdrop.addEventListener('click', closeAuthModal);
    authCloseBtn.addEventListener('click', closeAuthModal);
    loginTabBtn.addEventListener('click', () => switchAuthForm('login'));
    registerTabBtn.addEventListener('click', () => switchAuthForm('register'));
    loginForm.addEventListener('submit', login);
    registerForm.addEventListener('submit', register);
    document.querySelectorAll('.workspace-tabs .tab-btn').forEach((btn) => {
        btn.addEventListener('click', () => switchPanel(btn.dataset.panel));
    });

    initAdminSubtabs();
    initAdminSettingsSearch();
    initAdminSettingsEditorEvents();
    initTooltips();
    initMermaidLightboxClicks();

    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            messageForm.dispatchEvent(new Event('submit'));
        }
    });

    messageInput.focus();
});

async function apiJson(url, options = {}) {
    const response = await fetch(url, {credentials: 'same-origin', ...options});
    let data = {};
    try {
        data = await response.json();
    } catch (_) {
        data = {};
    }
    if (!response.ok) {
        throw new Error(data.error || `Ошибка ${response.status}`);
    }
    return data;
}

function setJobStatus(message, options = {}) {
    if (!jobStatus) {
        return;
    }

    const hasProgress = typeof options.progress === 'number';
    const progress = hasProgress ? Math.max(0, Math.min(100, Math.round(options.progress))) : null;
    const state = options.state || '';
    jobStatus.classList.toggle('is-error', state === 'failed' || state === 'error');
    jobStatus.classList.toggle('is-success', state === 'done' || state === 'success');

    if (!hasProgress && !options.indeterminate) {
        jobStatus.textContent = message || '';
        return;
    }

    const progressLabel = hasProgress ? `${progress}%` : '';
    const progressStyle = hasProgress ? ` style="width: ${progress}%"` : '';
    const progressClass = options.indeterminate ? ' job-progress__bar--indeterminate' : '';
    jobStatus.innerHTML = `
        <div class="job-status__line">
            <span>${escapeHtml(message || '')}</span>
            ${progressLabel ? `<span>${progressLabel}</span>` : ''}
        </div>
        <div class="job-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100"${hasProgress ? ` aria-valuenow="${progress}"` : ''}>
            <div class="job-progress__bar${progressClass}"${progressStyle}></div>
        </div>
    `;
}

function renderJob(job) {
    if (!job) {
        return;
    }
    const progress = typeof job.progress === 'number' ? job.progress : null;
    const isActive = job.status === 'pending' || job.status === 'running';
    setJobStatus(`${job.status}: ${job.message}`, {
        progress,
        state: job.status,
        indeterminate: isActive && progress === null,
    });
}

function uploadJsonWithProgress(url, formData, progressMessage) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', url);
        xhr.withCredentials = true;

        xhr.upload.onprogress = (event) => {
            if (!event.lengthComputable) {
                setJobStatus(progressMessage, {state: 'running', indeterminate: true});
                return;
            }
            const progress = Math.round((event.loaded / event.total) * 100);
            setJobStatus(`${progressMessage}: ${formatBytes(event.loaded)} из ${formatBytes(event.total)}`, {
                progress,
                state: 'running',
            });
        };

        xhr.onload = () => {
            let data = {};
            try {
                data = JSON.parse(xhr.responseText || '{}');
            } catch (_) {
                data = {};
            }
            if (xhr.status >= 200 && xhr.status < 300) {
                resolve(data);
            } else {
                reject(new Error(data.error || `Ошибка ${xhr.status}`));
            }
        };

        xhr.onerror = () => reject(new Error('Ошибка загрузки файла'));
        xhr.onabort = () => reject(new Error('Загрузка файла отменена'));
        xhr.send(formData);
    });
}

async function initializeAuth() {
    try {
        currentAuth = await apiJson('/api/auth/me');
    } catch (_) {
        currentAuth = {authenticated: false, role: 'guest', user: null};
    }
    applyAuthState();
}

function applyAuthState() {
    const isAdminRole = currentAuth.role === 'admin';
    const user = currentAuth.user || {};
    authStatus.textContent = currentAuth.authenticated
        ? `${user.username || user.email || 'Пользователь'} · ${currentAuth.role}`
        : 'Гость';
    authOpenBtn.hidden = currentAuth.authenticated;
    logoutBtn.hidden = !currentAuth.authenticated;
    document.querySelectorAll('.admin-only').forEach((node) => {
        node.hidden = !isAdminRole;
    });
    if (!isAdminRole && document.getElementById('adminPanel').classList.contains('active')) {
        switchPanel('chatPanel');
    }
    if (!isAdminRole && document.getElementById('documentsPanel').classList.contains('active')) {
        switchPanel('chatPanel');
    }
}

function openAuthModal(mode = 'login') {
    switchAuthForm(mode);
    authMessage.textContent = '';
    authModal.hidden = false;
    setTimeout(() => (mode === 'login' ? loginIdentifier : registerUsername).focus(), 0);
}

function closeAuthModal() {
    authModal.hidden = true;
}

function switchAuthForm(mode) {
    const registerMode = mode === 'register';
    loginTabBtn.classList.toggle('active', !registerMode);
    registerTabBtn.classList.toggle('active', registerMode);
    loginForm.classList.toggle('active', !registerMode);
    registerForm.classList.toggle('active', registerMode);
    document.getElementById('authTitle').textContent = registerMode ? 'Регистрация' : 'Вход';
    authMessage.textContent = '';
}

async function login(e) {
    e.preventDefault();
    authMessage.textContent = 'Выполняю вход...';
    try {
        currentAuth = await apiJson('/api/auth/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                identifier: loginIdentifier.value.trim(),
                password: loginPassword.value,
            }),
        });
        loginPassword.value = '';
        closeAuthModal();
        applyAuthState();
        loadChats();
    } catch (error) {
        authMessage.textContent = error.message;
    }
}

async function register(e) {
    e.preventDefault();
    authMessage.textContent = 'Создаю аккаунт...';
    try {
        currentAuth = await apiJson('/api/auth/register', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                username: registerUsername.value.trim(),
                email: registerEmail.value.trim(),
                password: registerPassword.value,
            }),
        });
        registerPassword.value = '';
        closeAuthModal();
        applyAuthState();
        loadChats();
    } catch (error) {
        authMessage.textContent = error.message;
    }
}

async function logout() {
    try {
        currentAuth = await apiJson('/api/auth/logout', {method: 'POST'});
        currentChatId = null;
        resetMessages(true);
        applyAuthState();
        loadChats();
    } catch (error) {
        showInlineError(error.message);
    }
}

function debounce(fn, delay) {
    let timer = null;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
    };
}

function switchPanel(panelId) {
    if ((panelId === 'documentsPanel' || panelId === 'adminPanel') && currentAuth.role !== 'admin') {
        showInlineError('Этот раздел доступен только администратору');
        panelId = 'chatPanel';
    }
    document.querySelectorAll('.workspace-tabs .tab-btn').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.panel === panelId);
    });
    document.querySelectorAll('.workspace-panel').forEach((panel) => {
        panel.classList.toggle('active', panel.id === panelId);
    });
    if (panelId === 'documentsPanel') {
        loadDocuments();
    }
    if (panelId === 'adminPanel') {
        loadAdminOverview();
    }
}

async function checkHealth() {
    try {
        const data = await apiJson('/api/health');
        if (data.ollama && data.database) {
            statusDot.className = 'status-dot online';
            statusText.textContent = 'Онлайн';
        } else {
            statusDot.className = 'status-dot offline';
            statusText.textContent = 'Ошибка подключения';
        }
    } catch (error) {
        statusDot.className = 'status-dot offline';
        statusText.textContent = 'Ошибка подключения';
    }
}

async function loadChats(search = '') {
    try {
        const qs = search ? `?q=${encodeURIComponent(search)}` : '';
        const data = await apiJson(`/api/chats${qs}`);
        renderChatList(data.chats || []);
    } catch (error) {
        chatList.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    }
}

function renderChatList(chats) {
    chatList.innerHTML = '';
    if (!chats.length) {
        chatList.innerHTML = '<div class="empty-state">История пуста</div>';
        return;
    }
    chats.forEach((chat) => {
        const item = document.createElement('button');
        item.className = `chat-list-item ${chat.id === currentChatId ? 'active' : ''}`;
        item.type = 'button';
        item.innerHTML = `
            <span class="chat-title">${escapeHtml(chat.title || 'Новый чат')}</span>
            <span class="chat-date">${formatDate(chat.updated_at)}</span>
        `;
        item.addEventListener('click', () => openChat(chat.id));

        const actions = document.createElement('span');
        actions.className = 'chat-actions';
        const rename = document.createElement('button');
        rename.type = 'button';
        rename.textContent = '✎';
        rename.title = 'Переименовать';
        rename.addEventListener('click', (e) => {
            e.stopPropagation();
            renameChat(chat);
        });
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.textContent = '×';
        remove.title = 'Удалить';
        remove.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteChat(chat.id);
        });
        actions.append(rename, remove);
        item.appendChild(actions);
        chatList.appendChild(item);
    });
}

async function openChat(chatId) {
    try {
        const data = await apiJson(`/api/chats/${chatId}`);
        currentChatId = data.chat.id;
        resetMessages(false);
        (data.messages || []).forEach((msg) => {
            const type = msg.role === 'assistant' ? 'bot' : 'user';
            const messageEl = addMessage(msg.content, type, {
                sources: msg.sources || [],
                citations: msg.citations || [],
                messageId: msg.id,
            });
            if (type === 'bot' && ((msg.sources || []).length || (msg.citations || []).length)) {
                addSourcesButton(messageEl, msg.sources || [], msg.citations || []);
                addVerifyButton(messageEl, {
                    answer: msg.content,
                    sources: msg.sources || [],
                    citations: msg.citations || [],
                });
                loadFollowupSuggestions(messageEl, {
                    answer: msg.content,
                    sources: msg.sources || [],
                    citations: msg.citations || [],
                });
                loadRelatedDocuments(messageEl, msg.sources || []);
                addFeedbackControls(messageEl, msg.id);
            }
        });
        loadChats(chatSearchInput.value.trim());
        switchPanel('chatPanel');
        messageInput.focus();
    } catch (error) {
        showInlineError(error.message);
    }
}

async function startNewChat() {
    try {
        const chat = await apiJson('/api/chats', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title: 'Новый чат'}),
        });
        currentChatId = chat.id;
        resetMessages(true);
        loadChats();
        switchPanel('chatPanel');
        messageInput.focus();
    } catch (error) {
        showInlineError(error.message);
    }
}

async function renameChat(chat) {
    const title = prompt('Новое название чата', chat.title || 'Новый чат');
    if (!title || !title.trim()) {
        return;
    }
    try {
        await apiJson(`/api/chats/${chat.id}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title: title.trim()}),
        });
        loadChats(chatSearchInput.value.trim());
    } catch (error) {
        showInlineError(error.message);
    }
}

async function deleteChat(chatId) {
    if (!confirm('Удалить этот чат?')) {
        return;
    }
    try {
        await apiJson(`/api/chats/${chatId}`, {method: 'DELETE'});
        if (currentChatId === chatId) {
            currentChatId = null;
            resetMessages(true);
        }
        loadChats(chatSearchInput.value.trim());
    } catch (error) {
        showInlineError(error.message);
    }
}

async function clearAllChats() {
    if (!confirm('Очистить все чаты? Это действие нельзя отменить.')) {
        return;
    }
    try {
        await apiJson('/api/chats', {method: 'DELETE'});
        currentChatId = null;
        chatSearchInput.value = '';
        resetMessages(true);
        loadChats();
    } catch (error) {
        showInlineError(error.message);
    }
}

async function ensureChat() {
    if (currentChatId) {
        return currentChatId;
    }
    const chat = await apiJson('/api/chats', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title: 'Новый чат'}),
    });
    currentChatId = chat.id;
    loadChats();
    return currentChatId;
}

function resetMessages(withWelcome) {
    messagesContainer.innerHTML = '';
    currentSources = [];
    currentCitations = [];
    closeSourcesPanel();
    if (withWelcome) {
        addMessage('Привет! Я AI-ассистент по базе знаний компании. Задайте мне любой вопрос, и я постараюсь найти ответ в документации.', 'bot');
    }
}

async function sendChatClassic(message) {
    const data = await apiJson('/api/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(buildChatPayload(message)),
    });
    hideTypingIndicator();
    const botMessage = addMessage(data.answer, 'bot', {
        sources: data.sources || [],
        citations: data.citations || [],
        messageId: data.message_id,
    });
    currentChatId = data.chat_id || currentChatId;
    addSourcesButton(botMessage, data.sources || [], data.citations || []);
    addVerifyButton(botMessage, {
        answer: data.answer,
        sources: data.sources || [],
        citations: data.citations || [],
    });
    loadFollowupSuggestions(botMessage, {
        answer: data.answer,
        sources: data.sources || [],
        citations: data.citations || [],
    });
    loadRelatedDocuments(botMessage, data.sources || []);
    addFeedbackControls(botMessage, data.message_id);
    loadChats();
}

async function handleSubmit(e) {
    e.preventDefault();
    const message = messageInput.value.trim();
    if (!message || isProcessing) {
        return;
    }

    await ensureChat();
    addMessage(message, 'user');
    messageInput.value = '';
    showTypingIndicator();
    isProcessing = true;
    sendButton.disabled = true;

    try {
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream',
            },
            body: JSON.stringify(buildChatPayload(message)),
        });

        if (response.status === 404) {
            await sendChatClassic(message);
            return;
        }

        hideTypingIndicator();
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            addMessage(errData.error || `Ошибка ${response.status}`, 'bot');
            return;
        }
        if (!response.body || !response.body.getReader) {
            addMessage('Поток ответа недоступен в этом браузере', 'bot');
            return;
        }

        await readStream(response);
    } catch (error) {
        hideTypingIndicator();
        addMessage(`Произошла ошибка при отправке запроса: ${error.message}`, 'bot');
    } finally {
        isProcessing = false;
        sendButton.disabled = false;
        messageInput.focus();
        loadChats(chatSearchInput.value.trim());
    }
}

function buildChatPayload(message) {
    return {
        message,
        chat_id: currentChatId,
        answer_mode: answerModeSelect.value,
        top_k: Number(topKInput.value),
        min_score: Number(minScoreInput.value),
    };
}

async function syncRagToolbarDefaults() {
    if (!topKInput || !minScoreInput) {
        return;
    }
    try {
        const data = await apiJson('/api/rag/defaults');
        _ragChatDefaults = data;
        if (Number.isFinite(Number(data.top_k))) {
            topKInput.value = String(data.top_k);
        }
        if (Number.isFinite(Number(data.min_score))) {
            minScoreInput.value = String(data.min_score);
        }
    } catch (_) {
        /* ignore */
    }
}

async function readStream(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let streamShell = null;
    let streamContent = null;
    let accumulated = '';
    let streamRafId = null;
    let doneReceived = false;

    const cancelStreamMarkdownFrame = () => {
        if (streamRafId != null) {
            cancelAnimationFrame(streamRafId);
            streamRafId = null;
        }
    };

    const flushStreamMarkdown = () => {
        streamRafId = null;
        if (!streamContent) {
            return;
        }
        streamContent.innerHTML = formatMessage(accumulated);
        // Mermaid рендерим только после завершения стрима (payload.type === 'done'):
        // во время стрима Markdown/код-блоки могут быть незавершенными, и Mermaid
        // периодически падает с "Syntax error in text", после чего блок помечается как обработанный.
        // Вместо рендера показываем анимированную заглушку.
        replaceMermaidBlocksWithPlaceholder(streamContent);
        scrollToBottom();
    };

    const scheduleStreamMarkdown = () => {
        if (streamRafId != null) {
            return;
        }
        streamRafId = requestAnimationFrame(flushStreamMarkdown);
    };

    const ensureStreamShell = () => {
        if (streamShell) {
            return;
        }
        streamShell = document.createElement('div');
        streamShell.className = 'message bot-message';
        const avatar = createMessageAvatar('bot');
        streamContent = document.createElement('div');
        streamContent.className = 'message-content markdown-content streaming-in-progress';
        streamShell.append(avatar, streamContent);
        messagesContainer.appendChild(streamShell);
        scrollToBottom();
    };

    ensureStreamShell();
    streamContent.innerHTML = '<div class="thinking-status">Ищу информацию и готовлю ответ<span class="thinking-dots">...</span></div>';
    scrollToBottom();

    const processSseBlock = (block) => {
        if (doneReceived) {
            return;
        }
        const lines = block.split('\n').map((line) => line.replace(/\r$/, ''));
        lines.forEach((line) => {
            if (!line.startsWith('data:')) {
                return;
            }
            const jsonStr = line.startsWith('data: ') ? line.slice(6) : line.slice(5).trimStart();
            let payload;
            try {
                payload = JSON.parse(jsonStr);
            } catch (_) {
                return;
            }
            if (payload.type === 'delta') {
                accumulated += payload.text || '';
                ensureStreamShell();
                scheduleStreamMarkdown();
            } else if (payload.type === 'status') {
                if (!accumulated) {
                    ensureStreamShell();
                    streamContent.innerHTML = `<div class="thinking-status">${escapeHtml(payload.message || 'Готовлю ответ')}<span class="thinking-dots">...</span></div>`;
                    scrollToBottom();
                }
            } else if (payload.type === 'done') {
                cancelStreamMarkdownFrame();
                const finalText = payload.answer != null ? payload.answer : accumulated;
                currentChatId = payload.chat_id || currentChatId;
                ensureStreamShell();
                streamContent.innerHTML = formatMessage(finalText);
                renderMermaidIn(streamContent);
                streamContent.classList.remove('streaming-in-progress');
                linkifySourceReferences(streamShell, payload.sources || [], payload.citations || []);
                addSourcesButton(streamShell, payload.sources || [], payload.citations || []);
                addVerifyButton(streamShell, {
                    answer: finalText,
                    sources: payload.sources || [],
                    citations: payload.citations || [],
                });
                loadFollowupSuggestions(streamShell, {
                    answer: finalText,
                    sources: payload.sources || [],
                    citations: payload.citations || [],
                });
                loadRelatedDocuments(streamShell, payload.sources || []);
                addFeedbackControls(streamShell, payload.message_id);
                doneReceived = true;
            } else if (payload.type === 'error') {
                cancelStreamMarkdownFrame();
                ensureStreamShell();
                streamContent.textContent = payload.message || 'Ошибка потока';
                streamContent.classList.remove('streaming-in-progress');
                doneReceived = true;
            }
        });
    };

    let processedBlocksSinceYield = 0;
    while (true) {
        const {done, value} = await reader.read();
        if (done) {
            break;
        }
        buffer += decoder.decode(value, {stream: true});
        const chunks = buffer.split('\n\n');
        buffer = chunks.pop() || '';
        for (const part of chunks) {
            if (part.trim()) {
                processSseBlock(part);
                processedBlocksSinceYield += 1;
                if (doneReceived) {
                    try { await reader.cancel(); } catch (_) { /* ignore */ }
                    return;
                }
                // Даём браузеру шанс обработать ввод/скролл, но не тормозим на каждом блоке.
                if (processedBlocksSinceYield >= 50) {
                    processedBlocksSinceYield = 0;
                    await new Promise((resolve) => setTimeout(resolve, 0));
                }
            }
        }
    }
    if (buffer.trim()) {
        processSseBlock(buffer);
    }
}

function addMessage(text, type, details = {}) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}-message`;
    if (details.messageId) {
        messageDiv.dataset.messageId = details.messageId;
    }

    const avatar = createMessageAvatar(type);

    const content = document.createElement('div');
    content.className = 'message-content';
    if (type === 'bot') {
        content.innerHTML = formatMessage(text);
        renderMermaidIn(content);
    } else {
        content.textContent = text;
    }

    messageDiv.append(avatar, content);
    messagesContainer.appendChild(messageDiv);
    if (type === 'bot') {
        linkifySourceReferences(messageDiv, details.sources || [], details.citations || []);
    }
    scrollToBottom();
    return messageDiv;
}

function formatMessage(text) {
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,
            gfm: true,
            highlight: (code, lang) => {
                if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
                    try {
                        return hljs.highlight(code, {language: lang}).value;
                    } catch (_) {
                        return escapeHtml(code);
                    }
                }
                return escapeHtml(code);
            },
        });
        const html = marked.parse(text || '');
        if (typeof DOMPurify !== 'undefined') {
            return `<div class="markdown-content">${DOMPurify.sanitize(html)}</div>`;
        }
        return `<div class="markdown-content">${sanitizeHtml(html)}</div>`;
    }
    const paragraphs = escapeHtml(text || '').split('\n\n');
    return paragraphs.map((p) => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');
}

function sanitizeHtml(html) {
    const template = document.createElement('template');
    template.innerHTML = html;
    template.content.querySelectorAll('script, iframe, object, embed').forEach((node) => node.remove());
    template.content.querySelectorAll('*').forEach((node) => {
        [...node.attributes].forEach((attr) => {
            if (attr.name.startsWith('on') || attr.value.startsWith('javascript:')) {
                node.removeAttribute(attr.name);
            }
        });
    });
    return template.innerHTML;
}

function normalizeSourceLabel(value) {
    return String(value || '').trim().replace(/\s+/g, ' ').toLowerCase();
}

function sourceLabels(source = {}, citation = {}) {
    return [
        source.title,
        source.source,
        source.path,
        citation.source,
        citation.chunk_id,
    ].map(normalizeSourceLabel).filter(Boolean);
}

function findSourceIndexByTitle(title, sources = [], citations = []) {
    const needle = normalizeSourceLabel(title);
    if (!needle) {
        return -1;
    }

    const max = Math.max(sources.length, citations.length);
    for (let i = 0; i < max; i += 1) {
        if (sourceLabels(sources[i] || {}, citations[i] || {}).includes(needle)) {
            return i;
        }
    }
    for (let i = 0; i < max; i += 1) {
        if (sourceLabels(sources[i] || {}, citations[i] || {}).some((label) => label.includes(needle) || needle.includes(label))) {
            return i;
        }
    }
    return -1;
}

function openDocumentFromSource(source = {}) {
    const path = source.path;
    if (!path || path === 'N/A') {
        return false;
    }
    window.open(`/api/documents/open?path=${encodeURIComponent(path)}`, '_blank', 'noopener');
    return true;
}

function openSourceReference(title, sources = [], citations = []) {
    const index = findSourceIndexByTitle(title, sources, citations);
    currentSources = sources;
    currentCitations = citations;
    openSourcesPanel({focusIndex: index, focusTitle: title});
    if (index >= 0) {
        openDocumentFromSource(sources[index] || {});
    }
}

function linkifySourceReferences(messageEl, sources = [], citations = []) {
    const root = messageEl?.querySelector('.markdown-content');
    if (!root) {
        return;
    }

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
            if (!/\[Источник:\s*[^\]]+\]/.test(node.nodeValue || '')) {
                return NodeFilter.FILTER_REJECT;
            }
            if (node.parentElement?.closest('a, button, code, pre')) {
                return NodeFilter.FILTER_REJECT;
            }
            return NodeFilter.FILTER_ACCEPT;
        },
    });
    const nodes = [];
    while (walker.nextNode()) {
        nodes.push(walker.currentNode);
    }

    nodes.forEach((node) => {
        const text = node.nodeValue || '';
        const fragment = document.createDocumentFragment();
        let lastIndex = 0;
        SOURCE_REFERENCE_PATTERN.lastIndex = 0;
        let match = SOURCE_REFERENCE_PATTERN.exec(text);
        while (match) {
            if (match.index > lastIndex) {
                fragment.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
            }
            const sourceTitle = match[1];
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'source-reference-link';
            button.textContent = match[0];
            button.title = 'Открыть источник';
            button.addEventListener('click', () => openSourceReference(sourceTitle, sources, citations));
            fragment.appendChild(button);
            lastIndex = SOURCE_REFERENCE_PATTERN.lastIndex;
            match = SOURCE_REFERENCE_PATTERN.exec(text);
        }
        if (lastIndex < text.length) {
            fragment.appendChild(document.createTextNode(text.slice(lastIndex)));
        }
        node.replaceWith(fragment);
    });
}

function showTypingIndicator() {
    const typingDiv = document.createElement('div');
    typingDiv.className = 'message bot-message';
    typingDiv.id = 'typingIndicator';
    typingDiv.innerHTML = `
        <div class="message-avatar"><img src="${assistantAvatarSrc}" alt="AI-ассистент"></div>
        <div class="message-content"><div class="typing-indicator"><span></span><span></span><span></span></div></div>
    `;
    messagesContainer.appendChild(typingDiv);
    scrollToBottom();
}

function hideTypingIndicator() {
    const typingIndicator = document.getElementById('typingIndicator');
    if (typingIndicator) {
        typingIndicator.remove();
    }
}

function addSourcesButton(messageEl, sources, citations) {
    if (!messageEl || (!sources.length && !citations.length)) {
        return;
    }
    const content = messageEl.querySelector('.message-content');
    if (!content || content.querySelector('.show-sources-btn')) {
        return;
    }
    const button = document.createElement('button');
    button.className = 'show-sources-btn';
    button.textContent = `Источники (${Math.max(sources.length, citations.length)})`;
    button.addEventListener('click', () => {
        currentSources = sources;
        currentCitations = citations;
        openSourcesPanel();
    });
    content.appendChild(button);
}

function addVerifyButton(messageEl, details = {}) {
    if (!messageEl || !(details.citations || []).length) {
        return;
    }
    const content = messageEl.querySelector('.message-content');
    if (!content || content.querySelector('.verify-answer-btn')) {
        return;
    }
    const button = document.createElement('button');
    button.className = 'verify-answer-btn';
    button.type = 'button';
    button.textContent = 'Проверить ответ';
    button.addEventListener('click', () => verifyAnswer(messageEl, details, button));
    content.appendChild(button);
}

async function verifyAnswer(messageEl, details, button) {
    const content = messageEl.querySelector('.message-content');
    if (!content) {
        return;
    }
    button.disabled = true;
    button.textContent = 'Проверяю...';
    let resultBox = content.querySelector('.verification-result');
    if (!resultBox) {
        resultBox = document.createElement('div');
        resultBox.className = 'verification-result';
        content.appendChild(resultBox);
    }
    resultBox.textContent = 'Сверяю ответ с цитатами...';

    try {
        const data = await apiJson('/api/chat/verify', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                answer: details.answer || '',
                sources: details.sources || [],
                citations: details.citations || [],
            }),
        });
        renderVerificationResult(resultBox, data.verification || {});
        button.textContent = 'Проверить еще раз';
    } catch (error) {
        resultBox.className = 'verification-result verification-result--error';
        resultBox.textContent = error.message;
        button.textContent = 'Повторить проверку';
    } finally {
        button.disabled = false;
    }
}

function renderVerificationResult(container, verification) {
    const statusLabels = {
        confirmed: 'Подтверждено источниками',
        partial: 'Подтверждено частично',
        unsupported: 'Есть неподтвержденные утверждения',
        no_sources: 'Нет цитат для проверки',
        error: 'Проверка недоступна',
    };
    const status = verification.status || 'partial';
    const details = Array.isArray(verification.details) ? verification.details : [];
    container.className = `verification-result verification-result--${status}`;
    const detailsHtml = details.length
        ? `<ul>${details.map((item) => `
            <li>
                <strong>${escapeHtml(item.claim || 'Утверждение')}</strong>
                <span>${escapeHtml(item.evidence || item.verdict || '')}</span>
            </li>
        `).join('')}</ul>`
        : '';
    container.innerHTML = `
        <div class="verification-title">${escapeHtml(statusLabels[status] || statusLabels.partial)}</div>
        <div>${escapeHtml(verification.summary || 'Проверка завершена.')}</div>
        ${detailsHtml}
    `;
}

async function loadFollowupSuggestions(messageEl, details = {}) {
    if (!messageEl || !details.answer || messageEl.querySelector('.followup-suggestions')) {
        return;
    }
    try {
        const data = await apiJson('/api/chat/suggestions', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                answer: details.answer,
                sources: details.sources || [],
                citations: details.citations || [],
            }),
        });
        const suggestions = Array.isArray(data.suggestions) ? data.suggestions : [];
        if (suggestions.length) {
            renderFollowupSuggestions(messageEl, suggestions);
        }
    } catch (_) {
        /* Рекомендации не критичны для основного ответа. */
    }
}

function renderFollowupSuggestions(messageEl, suggestions) {
    const content = messageEl.querySelector('.message-content');
    if (!content || content.querySelector('.followup-suggestions')) {
        return;
    }
    const wrapper = document.createElement('div');
    wrapper.className = 'followup-suggestions';
    wrapper.innerHTML = '<div class="followup-title">Можно уточнить:</div>';
    suggestions.slice(0, 5).forEach((question) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = question;
        btn.addEventListener('click', () => {
            messageInput.value = question;
            messageInput.focus();
            messageForm.dispatchEvent(new Event('submit'));
        });
        wrapper.appendChild(btn);
    });
    content.appendChild(wrapper);
}

async function loadRelatedDocuments(messageEl, sources = []) {
    if (currentAuth.role !== 'admin') {
        return;
    }
    if (!messageEl || !sources.length || messageEl.querySelector('.related-documents')) {
        return;
    }
    try {
        const data = await apiJson('/api/documents/related', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                sources,
                limit: Math.min(Number(_ragChatDefaults.top_k) || 5, 10),
            }),
        });
        const documents = Array.isArray(data.documents) ? data.documents : [];
        if (documents.length) {
            renderRelatedDocuments(messageEl, documents);
        }
    } catch (_) {
        /* Связанные документы не критичны для основного ответа. */
    }
}

function renderRelatedDocuments(messageEl, documents) {
    const content = messageEl.querySelector('.message-content');
    if (!content || content.querySelector('.related-documents')) {
        return;
    }
    const wrapper = document.createElement('div');
    wrapper.className = 'related-documents';
    wrapper.innerHTML = '<div class="related-title">Что читать дальше:</div>';
    documents.forEach((doc) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.innerHTML = `
            <strong>${escapeHtml(doc.filename || doc.path || 'Документ')}</strong>
            <span>${escapeHtml(doc.path || '')}</span>
        `;
        btn.addEventListener('click', () => openDocumentFromSource(doc));
        wrapper.appendChild(btn);
    });
    content.appendChild(wrapper);
}

function addFeedbackControls(messageEl, messageId) {
    if (!messageEl || !messageId) {
        return;
    }
    const content = messageEl.querySelector('.message-content');
    if (!content || content.querySelector('.feedback-controls')) {
        return;
    }
    const controls = document.createElement('div');
    controls.className = 'feedback-controls';
    ['up', 'down'].forEach((rating) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = rating === 'up' ? 'Полезно' : 'Не полезно';
        btn.addEventListener('click', () => sendFeedback(messageId, rating, controls));
        controls.appendChild(btn);
    });
    content.appendChild(controls);
}

async function sendFeedback(messageId, rating, controls) {
    try {
        await apiJson('/api/chats/feedback', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message_id: messageId, session_id: currentChatId, rating}),
        });
        controls.textContent = 'Оценка сохранена';
    } catch (error) {
        controls.textContent = error.message;
    }
}

function openSourcesPanel(options = {}) {
    sourcesList.innerHTML = '';
    const citations = currentCitations || [];
    const sources = currentSources || [];
    const max = Math.max(citations.length, sources.length);
    const focusIndex = Number.isInteger(options.focusIndex) && options.focusIndex >= 0
        ? options.focusIndex
        : findSourceIndexByTitle(options.focusTitle, sources, citations);
    if (!max) {
        sourcesList.innerHTML = '<div class="empty-state">Источники не найдены</div>';
    }
    for (let i = 0; i < max; i += 1) {
        const source = sources[i] || {};
        const citation = citations[i] || {};
        const title = source.title || citation.source || 'Без названия';
        const path = source.path || source.source || citation.chunk_id || 'N/A';
        const fileType = source.file_type || fileTypeFromPath(path);
        const chunkLabel = Number.isInteger(source.chunk_index) && source.total_chunks
            ? `Чанк ${source.chunk_index + 1} из ${source.total_chunks}`
            : '';
        const sectionPath = source.section_path || '';
        const relevance = source.relevance || citation.score || 'n/a';
        const snippet = citation.text || source.text || '';
        const sourceItem = document.createElement('div');
        sourceItem.className = 'source-item';
        if (i === focusIndex) {
            sourceItem.classList.add('source-item--active');
        }
        sourceItem.innerHTML = `
            <div class="source-card-header">
                <div>
                    <div class="source-title">${escapeHtml(title)}</div>
                    <div class="source-path">${escapeHtml(path)}</div>
                    ${sectionPath ? `<div class="source-section-path">${escapeHtml(sectionPath)}</div>` : ''}
                </div>
            </div>
            <div class="source-meta-row">
                ${source.path && source.path !== 'N/A' ? '<button class="source-open-hint" type="button">Открыть</button>' : ''}
                <span class="source-relevance">Релевантность: ${escapeHtml(String(relevance))}</span>
                ${fileType ? `<span class="source-badge">${escapeHtml(fileType)}</span>` : ''}
                ${chunkLabel ? `<span class="source-badge">${escapeHtml(chunkLabel)}</span>` : ''}
                ${source.chunk_kind ? `<span class="source-badge">${escapeHtml(source.chunk_kind)}</span>` : ''}
            </div>
            <p class="source-snippet">${escapeHtml(snippet)}</p>
        `;
        const openButton = sourceItem.querySelector('.source-open-hint');
        if (openButton) {
            openButton.addEventListener('click', () => openDocumentFromSource(source));
        }
        sourcesList.appendChild(sourceItem);
    }
    sourcesPanel.classList.add('open');
    const activeSource = sourcesList.querySelector('.source-item--active');
    if (activeSource) {
        activeSource.scrollIntoView({block: 'nearest'});
    }
}

function closeSourcesPanel() {
    sourcesPanel.classList.remove('open');
}

function fileTypeFromPath(path) {
    const match = String(path || '').match(/\.([a-z0-9]+)$/i);
    return match ? match[1].toLowerCase() : '';
}

function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

async function loadDocuments() {
    if (currentAuth.role !== 'admin') {
        documentsList.innerHTML = '<div class="empty-state">Раздел доступен только администратору</div>';
        return;
    }
    documentsList.innerHTML = '<div class="empty-state">Загрузка...</div>';
    try {
        const data = await apiJson('/api/documents');
        const docs = data.documents || [];
        if (!docs.length) {
            documentsList.innerHTML = '<div class="empty-state">Документы не найдены</div>';
            return;
        }
        documentsList.innerHTML = docs.map((doc) => {
            const openUrl = `/api/documents/open?path=${encodeURIComponent(doc.path)}`;
            return `
            <a class="data-card data-card--link" href="${openUrl}" target="_blank" rel="noopener noreferrer" title="Открыть документ">
                <strong>${escapeHtml(doc.filename)}</strong>
                <span>${escapeHtml(doc.path)}</span>
                <small>${escapeHtml(doc.file_type || '')} · ${formatBytes(doc.size_bytes)} · ${formatDate(doc.modified_at)}</small>
            </a>`;
        }).join('');
    } catch (error) {
        documentsList.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    }
}

async function uploadDocument(e) {
    e.preventDefault();
    if (!documentFileInput.files.length) {
        setJobStatus('Выберите файл');
        return;
    }
    const formData = new FormData();
    formData.append('file', documentFileInput.files[0]);
    try {
        setJobStatus('Подготовка загрузки файла', {progress: 0, state: 'running'});
        await uploadJsonWithProgress('/api/documents/upload', formData, 'Загрузка файла');
        setJobStatus('Файл загружен', {progress: 100, state: 'done'});
        documentFileInput.value = '';
        loadDocuments();
    } catch (error) {
        setJobStatus(error.message, {state: 'failed'});
    }
}

async function previewDocument() {
    if (!documentFileInput.files.length) {
        setJobStatus('Выберите файл для предпросмотра');
        return;
    }
    const formData = new FormData();
    formData.append('file', documentFileInput.files[0]);
    indexPreview.innerHTML = '<div class="empty-state">Анализирую документ...</div>';
    try {
        setJobStatus('Загрузка файла для предпросмотра', {progress: 0, state: 'running'});
        const data = await uploadJsonWithProgress('/api/documents/preview', formData, 'Загрузка файла для предпросмотра');
        setJobStatus('Предпросмотр готов', {progress: 100, state: 'done'});
        renderIndexPreview(data.preview || {});
    } catch (error) {
        setJobStatus(error.message, {state: 'failed'});
        indexPreview.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    }
}

function renderIndexPreview(preview) {
    const warnings = preview.warnings || [];
    const chunks = preview.chunks || [];
    const versionDiff = preview.version_diff || null;
    indexPreview.innerHTML = `
        <div class="preview-card">
            <div class="preview-header">
                <strong>${escapeHtml(preview.filename || 'Документ')}</strong>
                <span>${escapeHtml(preview.file_type || '')} · ${formatBytes(preview.size_bytes)} · ${preview.chunk_count || 0} чанков</span>
            </div>
            <div class="preview-meta">
                <span>Заголовок: ${escapeHtml(preview.title || 'не найден')}</span>
                <span>Извлечено символов: ${preview.text_length || 0}</span>
            </div>
            ${warnings.length ? `<div class="preview-warnings">${warnings.map((item) => `<span>${escapeHtml(item)}</span>`).join('')}</div>` : ''}
            ${(preview.headings || []).length ? `<div class="preview-section"><strong>Похожие на заголовки фразы</strong>${renderPreviewList(preview.headings)}</div>` : ''}
            ${versionDiff ? renderVersionDiff(versionDiff) : ''}
            <div class="preview-section"><strong>Первые чанки</strong>${chunks.length ? chunks.map((chunk) => `<p>${escapeHtml(clipText(chunk, 500))}</p>`).join('') : '<span>Чанки не найдены</span>'}</div>
        </div>
    `;
}

function renderVersionDiff(diff) {
    const added = diff.added || [];
    const removed = diff.removed || [];
    return `
        <div class="preview-section version-diff">
            <strong>Сравнение с текущей версией</strong>
            <span>Файл: ${escapeHtml(diff.existing_path || '')}</span>
            <span>Сходство: ${Math.round(Number(diff.similarity || 0) * 100)}% · было ${diff.old_length || 0} символов, стало ${diff.new_length || 0}</span>
            ${added.length ? `<div class="diff-list diff-list--added"><b>Добавлено</b>${renderPreviewList(added.map((item) => clipText(item, 180)))}</div>` : ''}
            ${removed.length ? `<div class="diff-list diff-list--removed"><b>Удалено</b>${renderPreviewList(removed.map((item) => clipText(item, 180)))}</div>` : ''}
            ${!added.length && !removed.length ? '<span>Существенных текстовых отличий не найдено</span>' : ''}
        </div>
    `;
}

function renderPreviewList(items) {
    return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
}

async function startReindex() {
    try {
        const data = await apiJson('/api/documents/reindex', {method: 'POST'});
        renderJob(data.job);
        pollJobs();
    } catch (error) {
        setJobStatus(error.message, {state: 'failed'});
    }
}

async function pollJobs() {
    try {
        const data = await apiJson('/api/documents/jobs');
        const latest = (data.jobs || [])[0];
        if (latest) {
            renderJob(latest);
            if (latest.status === 'pending' || latest.status === 'running') {
                setTimeout(pollJobs, 2000);
            }
        }
    } catch (_) {
        /* ignore polling errors */
    }
}

async function loadAdminOverview() {
    if (currentAuth.role !== 'admin') {
        adminOverview.innerHTML = '<div class="empty-state">Раздел доступен только администратору</div>';
        return;
    }
    adminOverview.innerHTML = '<div class="empty-state">Проверка...</div>';
    try {
        const data = await apiJson('/api/admin/overview');
        const chroma = data.health.chroma || {};
        const models = data.models || {};
        const settings = data.settings || {};
        const quality = data.quality || {};
        const feedback = quality.feedback || {};
        const documents = quality.documents || {};
        const topSources = quality.top_sources || [];
        const negativeFeedback = quality.negative_feedback || [];
        const negativeSources = quality.negative_sources || [];
        const weakAnswers = quality.weak_answers || [];
        const knowledgeGaps = quality.knowledge_gaps || [];
        const risks = quality.risks || [];
        adminOverview.innerHTML = `
            <div class="data-card"><strong>LLM</strong><span>${data.health.llm ? 'доступен' : 'недоступен'}</span></div>
            <div class="data-card"><strong>Chroma</strong><span>${chroma.ok ? `${chroma.count} чанков` : escapeHtml(chroma.error || 'ошибка')}</span></div>
            <div class="data-card"><strong>Модели</strong><span>chat: ${escapeHtml(settings.chat_model || '')}<br>embed: ${escapeHtml(settings.embedding_model || '')}</span></div>
            <div class="data-card"><strong>История</strong><span>${data.usage.chat_count} чатов<br>${data.usage.message_count || 0} сообщений</span></div>
            <div class="data-card"><strong>Оценки</strong><span>Полезно: ${feedback.up || 0}<br>Не полезно: ${feedback.down || 0}</span></div>
            <div class="data-card"><strong>Документы</strong><span>${documents.total || 0} файлов<br>Устаревших: ${documents.stale_count || (documents.stale || []).length}<br>Дублей: ${(documents.duplicates || []).length}</span></div>
            <div class="data-card wide"><strong>Риски качества</strong>${renderAdminRiskList(risks)}</div>
            <div class="data-card wide"><strong>Доступные модели</strong><span>${escapeHtml((models.available || []).join(', ') || models.error || 'нет данных')}</span></div>
            <div class="data-card wide"><strong>RAG</strong><span>top_k=${settings.rag_top_k}, min_score=${settings.rag_min_score}, citations=${settings.rag_max_citations}</span></div>
            <div class="data-card wide"><strong>Топ источников</strong>${renderAdminList(topSources, (item) => `${item.count} × ${item.title || item.path}`)}</div>
            <div class="data-card wide"><strong>Источники с плохими оценками</strong>${renderAdminList(negativeSources, (item) => `${item.negative_count} × ${item.title || item.path}`)}</div>
            <div class="data-card wide"><strong>Слабые ответы</strong>${renderAdminList(weakAnswers, (item) => `${item.reason}: ${clipText(item.question || item.answer || '', 160)}`)}</div>
            <div class="data-card wide"><strong>Пробелы в базе знаний</strong>${renderAdminList(knowledgeGaps, (item) => `${item.count} × ${item.topic}: ${clipText(item.last_question || item.reason || '', 140)}`)}</div>
            <div class="data-card wide"><strong>Последние дизлайки</strong>${renderAdminList(negativeFeedback, (item) => `${item.chat_title || 'Чат'}: ${clipText(item.answer || item.comment || '', 140)}`)}</div>
            <div class="data-card wide"><strong>Давно не обновлялись</strong>${renderAdminList(documents.stale || [], (item) => `${item.path} · ${formatDate(item.modified_at)}`)}</div>
            <div class="data-card wide"><strong>Дубли документов</strong>${renderAdminList(documents.duplicates || [], (item) => `${item.count} × ${item.filename}: ${(item.paths || []).join(', ')}`)}</div>
        `;
    } catch (error) {
        adminOverview.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    }
}

function initAdminSubtabs() {
    const buttons = document.querySelectorAll('[data-admin-panel]');
    if (!buttons.length) {
        return;
    }
    buttons.forEach((btn) => {
        btn.addEventListener('click', () => {
            const panelId = btn.getAttribute('data-admin-panel');
            buttons.forEach((b) => b.classList.toggle('active', b === btn));
            document.querySelectorAll('.admin-subpanel').forEach((panel) => {
                panel.classList.toggle('active', panel.id === panelId);
            });
            if (panelId === 'adminSettingsPanel') {
                loadAdminSettings();
            }
        });
    });
}

let _adminSettingsCache = null;
let _adminSettingsBaseByKey = {};
let _adminSettingsDraft = {};
let _adminSettingsDirty = new Set();
let _adminSettingsEditorEventsInitialized = false;

async function loadAdminSettings() {
    if (!adminSettings) {
        return;
    }
    if (currentAuth.role !== 'admin') {
        adminSettings.innerHTML = '<div class="empty-state">Раздел доступен только администратору</div>';
        _adminSettingsCache = null;
        return;
    }
    adminSettings.innerHTML = '<div class="empty-state">Загрузка настроек...</div>';
    try {
        const data = await apiJson('/api/admin/settings/schema');
        _adminSettingsCache = data;
        _adminSettingsBaseByKey = indexAdminSettingsByKey(data);
        renderAdminSettings(data, (adminSettingsSearch?.value || '').trim());
        updateAdminSettingsDraftToolbar();
    } catch (error) {
        adminSettings.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
        _adminSettingsCache = null;
    }
}

function indexAdminSettingsByKey(payload) {
    const result = {};
    const groups = payload?.groups || [];
    for (const g of groups) {
        for (const item of (g.items || [])) {
            if (item?.key) {
                result[item.key] = item;
            }
        }
    }
    return result;
}

function initAdminSettingsSearch() {
    if (!adminSettingsSearch) {
        return;
    }
    adminSettingsSearch.addEventListener('input', () => {
        if (!_adminSettingsCache) {
            return;
        }
        renderAdminSettings(_adminSettingsCache, adminSettingsSearch.value);
    });
}

function renderAdminSettings(payload, query) {
    const groups = payload?.groups || [];
    const q = String(query || '').toLowerCase();
    const collapsed = loadAdminSettingsCollapsed();
    const filtered = groups.map((g) => {
        const items = (g.items || []).filter((item) => {
            if (!q) return true;
            const hay = [
                item.key,
                item.env,
                item.description,
                item.allowed,
                item.type,
                item.secret ? 'секрет' : '',
            ].join(' ').toLowerCase();
            return hay.includes(q);
        });
        return {...g, items};
    }).filter((g) => (g.items || []).length);

    if (!filtered.length) {
        adminSettings.innerHTML = '<div class="empty-state">Ничего не найдено</div>';
        return;
    }

    adminSettings.innerHTML = filtered.map((group) => {
        const items = group.items || [];
        const groupId = String(group.title || '').toLowerCase();
        const isCollapsed = !q && !!collapsed[groupId];
        return `
            <section class="admin-settings-group ${isCollapsed ? 'is-collapsed' : ''}" data-settings-group="${escapeHtml(groupId)}">
                <button class="admin-settings-group__header" type="button" aria-expanded="${isCollapsed ? 'false' : 'true'}">
                    <span class="admin-settings-group__chev" aria-hidden="true">▾</span>
                    <h3>${escapeHtml(group.title || '')}</h3>
                    <span>${items.length} шт.</span>
                    <span class="admin-settings-group__hint">${isCollapsed ? 'Нажмите, чтобы развернуть' : 'Нажмите, чтобы свернуть'}</span>
                </button>
                <div class="admin-settings-group__list">
                    ${items.map(renderAdminSettingItem).join('')}
                </div>
            </section>
        `;
    }).join('');
}

function renderAdminSettingItem(item) {
    const value = item.secret ? (item.masked ? item.masked : '—') : (item.value || '—');
    const desc = item.description || '';
    const allowed = item.allowed || '';
    const label = item.label || '';
    const ui = item.ui || {};
    const isOverridden = !!item.is_overridden;
    const restartRequired = !!item.restart_required;
    const restartHint = item.restart_hint || '';
    const dirty = _adminSettingsDirty.has(item.key);
    const input = renderSettingInput(item, ui);
    return `
        <div class="setting-item ${dirty ? 'is-dirty' : ''} ${restartRequired ? 'is-restart' : ''}" data-setting-row="${escapeHtml(item.key || '')}">
            <div class="setting-item__main">
                <div class="setting-item__title">
                    <strong>${escapeHtml(item.key || '')}</strong>
                    ${label ? `<span class="setting-item__label">${escapeHtml(label)}</span>` : ''}
                    <button
                        class="help-icon"
                        type="button"
                        aria-label="Справка по настройке"
                        data-setting-key="${escapeHtml(item.key || '')}"
                        data-setting-env="${escapeHtml(item.env || '')}"
                        data-setting-type="${escapeHtml(item.type || '')}"
                        data-setting-description="${escapeHtml(desc)}"
                        data-setting-allowed="${escapeHtml(allowed)}"
                        data-setting-secret="${item.secret ? '1' : '0'}"
                        data-setting-restart="${restartRequired ? '1' : '0'}"
                        data-setting-restart-hint="${escapeHtml(restartHint)}"
                    >?</button>
                </div>
                <div class="setting-item__meta">
                    <span class="setting-meta-chip" title="Переменная окружения">${escapeHtml(item.env || '')}</span>
                    <span class="setting-meta-chip" title="Тип">${escapeHtml(item.type || '')}</span>
                    ${item.secret ? '<span class="setting-meta-chip setting-meta-chip--secret">секрет</span>' : ''}
                    ${isOverridden ? '<span class="setting-meta-chip setting-meta-chip--override">override</span>' : ''}
                    ${restartRequired ? '<span class="setting-meta-chip setting-meta-chip--restart">нужен перезапуск</span>' : ''}
                    ${dirty ? '<span class="setting-meta-chip setting-meta-chip--dirty">изменено</span>' : ''}
                </div>
                <div class="setting-item__control">
                    ${input}
                    <div class="setting-item__actions">
                        ${isOverridden ? `<button class="secondary-btn setting-clear-btn" type="button" data-setting-clear="${escapeHtml(item.key || '')}">Сбросить</button>` : ''}
                        <span class="setting-item__status" data-setting-status="${escapeHtml(item.key || '')}"></span>
                    </div>
                </div>
            </div>
            <div class="setting-item__value" title="Текущее значение">${escapeHtml(value)}</div>
        </div>
    `;
}

function renderSettingInput(item, ui) {
    const key = item.key || '';
    const type = item.type || 'str';
    const draft = Object.prototype.hasOwnProperty.call(_adminSettingsDraft, key) ? _adminSettingsDraft[key] : undefined;
    const baseValue = item.secret ? '' : (item.value || '');
    const value = draft !== undefined ? String(draft) : baseValue;

    if (type === 'bool') {
        const raw = draft !== undefined ? draft : (item.value || '');
        const checked = raw === true || String(raw).toLowerCase() === 'true';
        return `<label class="setting-bool"><input type="checkbox" data-setting-input="${escapeHtml(key)}" ${checked ? 'checked' : ''}> <span>Включено</span></label>`;
    }

    if (type === 'int' && (ui.kind === 'slider')) {
        const min = Number(ui.min ?? 0);
        const max = Number(ui.max ?? 100);
        const step = Number(ui.step ?? 1);
        const v = Number(draft !== undefined ? draft : (item.value ?? min));
        return `
            <div class="setting-slider" data-setting-slider="${escapeHtml(key)}">
                <input type="range" min="${min}" max="${max}" step="${step}" value="${Number.isFinite(v) ? v : min}" data-setting-range="${escapeHtml(key)}">
                <input type="number" min="${min}" max="${max}" step="${step}" value="${Number.isFinite(v) ? v : min}" data-setting-input="${escapeHtml(key)}">
            </div>
        `;
    }

    if (type === 'int') {
        return `<input class="setting-text" type="number" data-setting-input="${escapeHtml(key)}" value="${escapeHtml(value)}">`;
    }
    if (type === 'float') {
        return `<input class="setting-text" type="number" step="0.01" data-setting-input="${escapeHtml(key)}" value="${escapeHtml(value)}">`;
    }
    if (type === 'list') {
        return `<textarea class="setting-textarea" rows="2" data-setting-input="${escapeHtml(key)}">${escapeHtml(value)}</textarea>`;
    }
    if (item.secret) {
        // Для секрета не показываем текущее значение. Draft храним только если пользователь ввёл что-то.
        return `<input class="setting-text" type="password" placeholder="Введите новое значение" data-setting-input="${escapeHtml(key)}" value="${escapeHtml(draft !== undefined ? String(draft) : '')}">`;
    }
    return `<input class="setting-text" type="text" data-setting-input="${escapeHtml(key)}" value="${escapeHtml(value)}">`;
}

function updateAdminSettingsGroupCollapsedUi(group, isCollapsed) {
    const header = group.querySelector('.admin-settings-group__header');
    if (!header) return;
    header.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
    const hint = header.querySelector('.admin-settings-group__hint');
    if (hint) {
        hint.textContent = isCollapsed ? 'Нажмите, чтобы развернуть' : 'Нажмите, чтобы свернуть';
    }
}

function initAdminSettingsEditorEvents() {
    if (!adminSettings) return;
    if (_adminSettingsEditorEventsInitialized) {
        return;
    }
    _adminSettingsEditorEventsInitialized = true;

    // sync range <-> number
    adminSettings.addEventListener('input', (evt) => {
        const target = evt.target;
        if (!(target instanceof HTMLElement)) return;
        if (target.matches('[data-setting-input]')) {
            const key = target.getAttribute('data-setting-input');
            if (key) {
                updateAdminSettingsDraftFromInput(key, target);
            }
        }
        if (target.matches('input[data-setting-range]')) {
            const key = target.getAttribute('data-setting-range');
            const wrap = adminSettings.querySelector(`[data-setting-slider="${CSS.escape(key)}"]`);
            const num = wrap?.querySelector(`input[data-setting-input="${CSS.escape(key)}"]`);
            if (num) num.value = target.value;
        } else if (target.matches('input[data-setting-input]')) {
            const key = target.getAttribute('data-setting-input');
            const wrap = adminSettings.querySelector(`[data-setting-slider="${CSS.escape(key)}"]`);
            const range = wrap?.querySelector(`input[data-setting-range="${CSS.escape(key)}"]`);
            if (range && target instanceof HTMLInputElement) range.value = target.value;
        }
    });

    adminSettings.addEventListener('click', async (evt) => {
        const target = evt.target;
        if (!(target instanceof HTMLElement)) return;

        const header = target.closest?.('.admin-settings-group__header');
        if (header) {
            const group = header.closest?.('.admin-settings-group');
            const groupId = group?.getAttribute('data-settings-group');
            if (groupId) {
                const collapsed = loadAdminSettingsCollapsed();
                const willCollapse = !group.classList.contains('is-collapsed');
                collapsed[groupId] = willCollapse;
                saveAdminSettingsCollapsed(collapsed);
                group.classList.toggle('is-collapsed', willCollapse);
                updateAdminSettingsGroupCollapsedUi(group, willCollapse);
            }
            return;
        }

        const clearKey = target.getAttribute('data-setting-clear');
        if (clearKey) {
            await clearAdminSetting(clearKey);
            return;
        }
    });
}

function updateAdminSettingsDraftFromInput(key, el) {
    const base = _adminSettingsBaseByKey[key];
    if (!base) return;

    let value = null;
    if (el instanceof HTMLInputElement && el.type === 'checkbox') {
        value = el.checked;
    } else if (el instanceof HTMLTextAreaElement) {
        value = el.value;
    } else if (el instanceof HTMLInputElement) {
        value = el.value;
    } else {
        return;
    }

    // Секрет считаем "изменённым" только если есть ввод.
    if (base.secret) {
        const str = String(value || '');
        if (!str) {
            delete _adminSettingsDraft[key];
            _adminSettingsDirty.delete(key);
        } else {
            _adminSettingsDraft[key] = str;
            _adminSettingsDirty.add(key);
        }
        updateAdminSettingsRowState(key);
        updateAdminSettingsDraftToolbar();
        return;
    }

    const baseVal = base.value ?? '';
    const baseType = base.type || 'str';
    const normalized = normalizeValueForCompare(baseType, value);
    const normalizedBase = normalizeValueForCompare(baseType, baseVal);
    if (normalized === normalizedBase) {
        delete _adminSettingsDraft[key];
        _adminSettingsDirty.delete(key);
    } else {
        _adminSettingsDraft[key] = value;
        _adminSettingsDirty.add(key);
    }
    updateAdminSettingsRowState(key);
    updateAdminSettingsDraftToolbar();
}

function normalizeValueForCompare(type, value) {
    if (type === 'bool') {
        if (value === true || String(value).toLowerCase() === 'true') return 'true';
        return 'false';
    }
    if (type === 'int') {
        const n = parseInt(String(value), 10);
        return Number.isFinite(n) ? String(n) : '';
    }
    if (type === 'float') {
        const n = Number(String(value).replace(',', '.'));
        return Number.isFinite(n) ? String(n) : '';
    }
    if (type === 'list') {
        return String(value || '')
            .split(',')
            .map((x) => x.trim())
            .filter(Boolean)
            .join(',');
    }
    return String(value ?? '');
}

function updateAdminSettingsRowState(key) {
    const row = adminSettings.querySelector(`[data-setting-row="${CSS.escape(key)}"]`);
    if (!row) return;
    row.classList.toggle('is-dirty', _adminSettingsDirty.has(key));
}

function updateAdminSettingsDraftToolbar() {
    const count = _adminSettingsDirty.size;
    if (adminSettingsDraftInfo) {
        adminSettingsDraftInfo.textContent = count ? `Изменено: ${count}` : '';
    }
    if (saveAdminSettingsDraftBtn) {
        saveAdminSettingsDraftBtn.disabled = count === 0;
    }
    if (resetAdminSettingsDraftBtn) {
        resetAdminSettingsDraftBtn.disabled = count === 0;
    }
}

async function resetAdminSettingsDraft() {
    _adminSettingsDraft = {};
    _adminSettingsDirty = new Set();
    if (_adminSettingsCache) {
        renderAdminSettings(_adminSettingsCache, (adminSettingsSearch?.value || '').trim());
    }
    updateAdminSettingsDraftToolbar();
}

async function saveAdminSettingsDraft() {
    const keys = Array.from(_adminSettingsDirty);
    if (!keys.length) return;
    if (saveAdminSettingsDraftBtn) {
        saveAdminSettingsDraftBtn.disabled = true;
        saveAdminSettingsDraftBtn.textContent = 'Сохранение...';
    }
    try {
        let i = 0;
        for (const key of keys) {
            i += 1;
            if (adminSettingsDraftInfo) {
                adminSettingsDraftInfo.textContent = `Сохранение ${i}/${keys.length}...`;
            }
            const value = _adminSettingsDraft[key];
            await apiJson('/api/admin/settings', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({key, value, action: 'set'}),
            });
        }
        _adminSettingsDraft = {};
        _adminSettingsDirty = new Set();
        await loadAdminSettings();
        await syncRagToolbarDefaults();
        if (adminSettingsDraftInfo) {
            adminSettingsDraftInfo.textContent = 'Сохранено';
            setTimeout(() => {
                if (adminSettingsDraftInfo) adminSettingsDraftInfo.textContent = '';
            }, 2000);
        }
    } catch (error) {
        if (adminSettingsDraftInfo) {
            adminSettingsDraftInfo.textContent = error.message;
        }
    } finally {
        if (saveAdminSettingsDraftBtn) {
            saveAdminSettingsDraftBtn.textContent = 'Сохранить всё';
        }
        updateAdminSettingsDraftToolbar();
    }
}

function loadAdminSettingsCollapsed() {
    try {
        const raw = localStorage.getItem('adminSettingsCollapsed') || '{}';
        const obj = JSON.parse(raw);
        return obj && typeof obj === 'object' ? obj : {};
    } catch (_) {
        return {};
    }
}

function saveAdminSettingsCollapsed(state) {
    try {
        localStorage.setItem('adminSettingsCollapsed', JSON.stringify(state || {}));
    } catch (_) {
        /* ignore */
    }
}

async function saveAdminSetting(key) {
    const input = adminSettings.querySelector(`[data-setting-input="${CSS.escape(key)}"]`);
    const status = adminSettings.querySelector(`[data-setting-status="${CSS.escape(key)}"]`);
    if (!input) return;
    if (status) status.textContent = 'Сохранение...';

    let value = null;
    if (input instanceof HTMLInputElement && input.type === 'checkbox') {
        value = input.checked;
    } else if (input instanceof HTMLTextAreaElement) {
        value = input.value;
    } else if (input instanceof HTMLInputElement) {
        value = input.value;
    }
    try {
        await apiJson('/api/admin/settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key, value, action: 'set'}),
        });
        if (status) status.textContent = 'Сохранено';
        await loadAdminSettings();
    } catch (error) {
        if (status) status.textContent = error.message;
    }
}

async function clearAdminSetting(key) {
    const status = adminSettings.querySelector(`[data-setting-status="${CSS.escape(key)}"]`);
    if (status) status.textContent = 'Сброс...';
    try {
        await apiJson('/api/admin/settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key, action: 'clear'}),
        });
        if (status) status.textContent = 'Сброшено';
        delete _adminSettingsDraft[key];
        _adminSettingsDirty.delete(key);
        await loadAdminSettings();
    } catch (error) {
        if (status) status.textContent = error.message;
    }
}

function initTooltips() {
    document.addEventListener('click', (evt) => {
        const target = evt.target;
        const open = document.querySelector('.tooltip-popover');
        if (!(target instanceof HTMLElement)) {
            return;
        }
        const button = target.closest?.('.help-icon');
        if (!button) {
            if (open && !open.contains(target)) {
                open.remove();
            }
            return;
        }
        evt.preventDefault();
        evt.stopPropagation();
        if (open) {
            open.remove();
        }
        const pop = document.createElement('div');
        pop.className = 'tooltip-popover';
        const key = button.getAttribute('data-setting-key') || '';
        const env = button.getAttribute('data-setting-env') || '';
        const type = button.getAttribute('data-setting-type') || '';
        const description = button.getAttribute('data-setting-description') || '';
        const allowed = button.getAttribute('data-setting-allowed') || '';
        const secret = (button.getAttribute('data-setting-secret') || '') === '1';
        const restart = (button.getAttribute('data-setting-restart') || '') === '1';
        const restartHint = button.getAttribute('data-setting-restart-hint') || '';

        const wrap = document.createElement('div');
        wrap.className = 'setting-tooltip';

        const title = document.createElement('div');
        title.className = 'setting-tooltip__title';
        title.textContent = key;
        wrap.appendChild(title);

        const addRow = (label, value) => {
            if (!value) return;
            const row = document.createElement('div');
            row.className = 'setting-tooltip__row';
            const strong = document.createElement('strong');
            strong.textContent = label;
            const span = document.createElement('span');
            span.textContent = value;
            row.appendChild(strong);
            row.appendChild(span);
            wrap.appendChild(row);
        };

        addRow('ENV', env);
        addRow('Тип', type);
        addRow('Описание', description);
        addRow('Допустимо', allowed);
        if (restart) {
            addRow('Применение', restartHint || 'Требуется перезапуск приложения.');
        }

        if (secret) {
            const note = document.createElement('div');
            note.className = 'setting-tooltip__note';
            note.textContent = 'Значение скрыто, т.к. это секрет.';
            wrap.appendChild(note);
        }

        pop.appendChild(wrap);
        document.body.appendChild(pop);
        const rect = button.getBoundingClientRect();
        const popRect = pop.getBoundingClientRect();
        const left = Math.max(12, Math.min(window.innerWidth - popRect.width - 12, rect.left));
        const top = Math.min(window.innerHeight - popRect.height - 12, rect.bottom + 8);
        pop.style.left = `${left}px`;
        pop.style.top = `${top}px`;
    });
    document.addEventListener('keydown', (evt) => {
        if (evt.key !== 'Escape') return;
        document.querySelector('.tooltip-popover')?.remove();
    });
}

function renderAdminList(items, formatter) {
    if (!items.length) {
        return '<span>Нет данных</span>';
    }
    return `<ul class="admin-list">${items.map((item) => `<li>${escapeHtml(formatter(item))}</li>`).join('')}</ul>`;
}

function renderAdminRiskList(items) {
    if (!items.length) {
        return '<span>Критичных рисков не найдено</span>';
    }
    return `<ul class="admin-list">${items.map((item) => `
        <li><strong>${escapeHtml(item.title || 'Риск')}</strong>: ${escapeHtml(item.details || item.level || '')}</li>
    `).join('')}</ul>`;
}

function exportCurrentChat() {
    const messages = [...messagesContainer.querySelectorAll('.message')].map((node) => {
        const role = node.classList.contains('user-message') ? 'Вы' : 'Ассистент';
        const text = node.querySelector('.message-content')?.innerText || '';
        return `## ${role}\n\n${text.trim()}`;
    }).join('\n\n');
    const blob = new Blob([messages], {type: 'text/markdown;charset=utf-8'});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `chat-${currentChatId || 'draft'}.md`;
    link.click();
    URL.revokeObjectURL(link.href);
}

function showInlineError(message) {
    addMessage(message, 'bot');
}

function formatBytes(bytes) {
    const size = Number(bytes || 0);
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value) {
    if (!value) {
        return '';
    }
    try {
        return new Date(value).toLocaleString('ru-RU', {dateStyle: 'short', timeStyle: 'short'});
    } catch (_) {
        return value;
    }
}

function clipText(value, limit) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    return text.length > limit ? `${text.slice(0, limit - 3)}...` : text;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
}
