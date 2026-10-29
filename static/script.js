let _ragChatDefaults = {top_k: 5, min_score: 0, max_citations: 5};
let currentSources = [];
let currentCitations = [];
let currentChatId = null;
let isProcessing = false;
let currentAuth = {authenticated: false, role: 'guest', user: null};
const SOURCE_REFERENCE_PATTERN = /\[Источник:\s*([^\]]+)\]/g;
const ACTIVE_CHAT_STORAGE_KEY = 'wiki4.activeChatId';
const CHAT_MESSAGE_MIN_LENGTH = 1;
const CHAT_MESSAGE_MAX_LENGTH = 5000;
const CHAT_ATTACHMENT_MAX_COUNT = 3;
const CHAT_ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024;
const CHAT_TOP_K_MIN = 1;
const CHAT_TOP_K_MAX = 10;
const CHAT_MIN_SCORE_MIN = 0;
const CHAT_MIN_SCORE_MAX = 1;
const WELCOME_MESSAGE = 'Привет! Я AI-ассистент по базе знаний компании. Задайте мне любой вопрос, и я постараюсь найти ответ в документации.';
const STREAM_RENDER_DEBUG = false;
const STREAM_RENDER_DEBUG_STORAGE_KEY = 'wiki4.streamRenderDebug';
const FRONTEND_OPTIMIZATION_DEBUG_STORAGE_KEY = 'wiki4.frontendOptimizationDebug';
let activeStreamController = null;
let activeStreamRequestId = 0;
let reindexPollTimer = null;
let _mermaidInitialized = false;
let _mermaidTheme = null;
let _mermaidLightbox = null;
let _mermaidLightboxCurrentSvg = null;
let _markedConfigured = false;
let _chatListRequestSeq = 0;

function recoverMermaidInAnswer(streamText, finalText) {
    const final = String(finalText || '');
    const stream = String(streamText || '');
    if (/```mermaid/i.test(final)) {
        return final;
    }
    const block = stream.match(/```mermaid[\s\S]*?```/i)?.[0];
    if (!block) {
        return final;
    }
    const intro = (final.split(/```/)[0] || stream.split(/```/)[0] || '').trim();
    const sources = final.match(/\n\n\*\*Источники:\*\*[\s\S]*$/)?.[0]?.trim() || '';
    return [intro, block, sources].filter(Boolean).join('\n\n');
}
let _chatListCache = [];
let _chatListSearch = '';

const messagesContainer = document.getElementById('messages');
const messageForm = document.getElementById('messageForm');
const messageInput = document.getElementById('messageInput');
const sendButton = document.getElementById('sendButton');
const attachButton = document.getElementById('attachButton');
const attachmentFileInput = document.getElementById('attachmentFileInput');
const attachmentPreview = document.getElementById('attachmentPreview');
let pendingAttachments = [];
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const serviceStatus = document.getElementById('serviceStatus');
const sourcesPanel = document.getElementById('sourcesPanel');
const sourcesList = document.getElementById('sourcesList');
const mainShell = document.querySelector('.main-shell');
const SOURCES_EMPTY_IDLE = 'Источники появятся после ответа';
const SOURCES_EMPTY_NONE = 'Источники не найдены';
const SOURCES_PANEL_COLLAPSED_KEY = 'wiki4.sourcesPanelCollapsed';
const sourcesDrawerMedia = window.matchMedia('(max-width: 980px)');
const closeSources = document.getElementById('closeSources');
let sourcesReveal = document.getElementById('sourcesReveal');
const sidebarNewChatBtn = document.getElementById('sidebarNewChatBtn');
const workspaceSidebar = document.getElementById('workspaceSidebar');
const sidebarToggle = document.getElementById('sidebarToggle');
const emptyTiles = document.getElementById('emptyTiles');
const chatContainer = document.querySelector('.chat-container');
const continueTileHint = document.getElementById('continueTileHint');
const ragAdvancedToggle = document.getElementById('ragAdvancedToggle');
const ragAdvancedPanel = document.getElementById('ragAdvancedPanel');
const clearChatsBtn = document.getElementById('clearChatsBtn');
const chatList = document.getElementById('chatList');
const chatSearchInput = document.getElementById('chatSearchInput');
const answerModeSelect = document.getElementById('answerModeSelect');
const followupSuggestionsToggle = document.getElementById('followupSuggestionsToggle');
const relatedDocsToggle = document.getElementById('relatedDocsToggle');
const CHAT_SHOW_FOLLOWUPS_KEY = 'chatShowFollowups';
const CHAT_SHOW_RELATED_DOCS_KEY = 'chatShowRelatedDocs';
const topKInput = document.getElementById('topKInput');
const minScoreInput = document.getElementById('minScoreInput');
const exportChatBtn = document.getElementById('exportChatBtn');
const uploadForm = document.getElementById('uploadForm');
const documentFileInput = document.getElementById('documentFileInput');
let _sourcesFocusRestore = null;
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
const adminSettingsFloat = document.getElementById('adminSettingsFloat');
const adminSettingsFloatInfo = document.getElementById('adminSettingsFloatInfo');
const saveAdminSettingsDraftFloatBtn = document.getElementById('saveAdminSettingsDraftFloatBtn');
const resetAdminSettingsDraftFloatBtn = document.getElementById('resetAdminSettingsDraftFloatBtn');
const adminSettingsPanel = document.getElementById('adminSettingsPanel');
const adminOverviewTab = document.getElementById('adminOverviewTab');
const adminSettingsTab = document.getElementById('adminSettingsTab');
const adminUsersTab = document.getElementById('adminUsersTab');
const adminUsersPanel = document.getElementById('adminUsersPanel');
const adminUsersSearch = document.getElementById('adminUsersSearch');
const adminUsersRoleFilter = document.getElementById('adminUsersRoleFilter');
const adminUsersStatusFilter = document.getElementById('adminUsersStatusFilter');
const refreshAdminUsersBtn = document.getElementById('refreshAdminUsersBtn');
const createAdminUserBtn = document.getElementById('createAdminUserBtn');
const adminUsersSummary = document.getElementById('adminUsersSummary');
const adminUsersList = document.getElementById('adminUsersList');
const adminUsersPager = document.getElementById('adminUsersPager');
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
const issueReportOpenBtn = document.getElementById('issueReportOpenBtn');
const issueModal = document.getElementById('issueModal');
const issueBackdrop = document.getElementById('issueBackdrop');
const issueCloseBtn = document.getElementById('issueCloseBtn');
const issueCancelBtn = document.getElementById('issueCancelBtn');
const issueForm = document.getElementById('issueForm');
const issueType = document.getElementById('issueType');
const issueTitleInput = document.getElementById('issueTitleInput');
const issueDescription = document.getElementById('issueDescription');
const issueContact = document.getElementById('issueContact');
const issueHp = document.getElementById('issueHp');
const issueMessage = document.getElementById('issueMessage');
const issueModeHint = document.getElementById('issueModeHint');
const issueSubmitBtn = document.getElementById('issueSubmitBtn');
let issueStatus = {enabled: true, stub: true, types: []};
let issueDraft = {sessionId: null, messageId: null};
/**
 * Option D avatars — Lucide-style stroke SVGs (16–18px), square 36×36 / radius 4px.
 * User: person outline. Assistant: book-open (KB answers) — not robot art / not AI sparkle fill.
 */
const USER_AVATAR_GLYPH = `
<svg class="message-avatar__glyph" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/>
  <circle cx="12" cy="7" r="4"/>
</svg>`;
const BOT_AVATAR_GLYPH = `
<svg class="message-avatar__glyph" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M12 7v14"/>
  <path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>
</svg>`;

function createMessageAvatar(type) {
    const avatar = document.createElement('div');
    const isBot = type === 'bot';
    avatar.className = isBot
        ? 'message-avatar message-avatar--bot'
        : 'message-avatar message-avatar--user';
    avatar.setAttribute('role', 'img');
    avatar.setAttribute('aria-label', isBot ? 'AI-ассистент' : 'Вы');
    avatar.innerHTML = isBot ? BOT_AVATAR_GLYPH : USER_AVATAR_GLYPH;
    return avatar;
}

function ensureMermaidInitialized() {
    if (typeof mermaid === 'undefined') {
        return false;
    }
    const theme = document.documentElement?.getAttribute('data-theme') === 'dark' ? 'dark' : 'default';
    if (_mermaidInitialized && _mermaidTheme === theme) {
        return true;
    }
    try {
        mermaid.initialize({
            startOnLoad: false,
            securityLevel: 'strict',
            // Не даём Mermaid рисовать "бомбу" при ошибках синтаксиса — покажем fallback сами.
            suppressErrorRendering: true,
            theme,
        });
        _mermaidInitialized = true;
        _mermaidTheme = theme;
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
        const renderId = `mmd-${Date.now()}-${Math.random().toString(16).slice(2)}-${idx}`;

        const showFallback = (raw) => {
            node.classList.add('mermaid-error');
            node.innerHTML = `<pre class="mermaid-error__pre"><code>${escapeHtml(raw)}</code></pre>`;
        };

        const renderWithCode = (code, allowServerFix) => {
            const trimmed = String(code || '').trim();
            if (!trimmed) {
                showFallback(code);
                return;
            }
            node.textContent = trimmed;
            node.classList.remove('mermaid-error');

            const fail = (reason) => {
                if (!allowServerFix) {
                    showFallback(trimmed);
                    return;
                }
                fetch('/api/mermaid/fix', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({code: trimmed, parse_error: String(reason || '')}),
                })
                    .then((resp) => (resp.ok ? resp.json() : null))
                    .then((data) => {
                        const fixed = (data && data.code) ? String(data.code).trim() : '';
                        if (fixed && fixed !== trimmed) {
                            renderWithCode(fixed, false);
                            return;
                        }
                        showFallback(trimmed);
                    })
                    .catch(() => showFallback(trimmed));
            };

            try {
                if (typeof mermaid.render === 'function') {
                    const maybe = mermaid.render(`${renderId}-${allowServerFix ? 'a' : 'b'}`, trimmed);
                    Promise.resolve(maybe)
                        .then((res) => {
                            const svg = res && (res.svg || res);
                            if (typeof svg !== 'string' || !svg.trim().startsWith('<svg')) {
                                fail('invalid_svg');
                                return;
                            }
                            node.classList.remove('mermaid-error');
                            node.innerHTML = svg;
                        })
                        .catch((err) => fail(`render_rejected:${err?.message || err || ''}`));
                    return;
                }

                if (typeof mermaid.run === 'function') {
                    mermaid.run({nodes: [node]});
                } else if (typeof mermaid.init === 'function') {
                    mermaid.init(undefined, [node]);
                } else {
                    fail('no_render_api');
                }
            } catch (_) {
                fail('render_exception');
            }
        };

        renderWithCode(nodesRawText.get(node) || node.textContent || '', true);
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
    initializeIssues();
    checkHealth();
    initEmptyTiles();
    initSidebarToggle();
    // Start on Option D empty tiles (welcome bubble is legacy).
    if (messagesContainer) {
        const onlyWelcome = [...messagesContainer.querySelectorAll('.message')].every(
            (node) => node.classList.contains('welcome-message') || node.classList.contains('system-message')
        );
        if (onlyWelcome) {
            messagesContainer.innerHTML = '';
        }
        syncEmptyTilesState();
    }
    loadChats().then(restoreActiveChatAfterReload);
    syncRagToolbarDefaults();
    initChatSuggestionToggles();
    setInterval(checkHealth, 30000);

    messageForm.addEventListener('submit', handleSubmit);
    initSourcesCollapse();
    closeSources.addEventListener('click', () => {
        if (isSourcesDrawerMode()) {
            closeSourcesPanel();
            return;
        }
        setSourcesCollapsed(true, {focusReveal: true});
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && sourcesPanel?.classList.contains('open') && isSourcesDrawerMode()) {
            closeSourcesPanel();
        }
    });
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
        refreshAdminSettingsBtn.addEventListener('click', () => loadAdminSettings({force: true}));
    }
    if (saveAdminSettingsDraftBtn) {
        saveAdminSettingsDraftBtn.addEventListener('click', saveAdminSettingsDraft);
    }
    if (saveAdminSettingsDraftFloatBtn) {
        saveAdminSettingsDraftFloatBtn.addEventListener('click', saveAdminSettingsDraft);
    }
    if (resetAdminSettingsDraftBtn) {
        resetAdminSettingsDraftBtn.addEventListener('click', resetAdminSettingsDraft);
    }
    if (resetAdminSettingsDraftFloatBtn) {
        resetAdminSettingsDraftFloatBtn.addEventListener('click', resetAdminSettingsDraft);
    }
    if (adminUsersSearch) {
        adminUsersSearch.addEventListener('input', debounce(() => loadAdminUsers(1), 250));
    }
    if (adminUsersRoleFilter) {
        adminUsersRoleFilter.addEventListener('change', () => loadAdminUsers(1));
    }
    if (adminUsersStatusFilter) {
        adminUsersStatusFilter.addEventListener('change', () => loadAdminUsers(1));
    }
    if (refreshAdminUsersBtn) {
        refreshAdminUsersBtn.addEventListener('click', () => loadAdminUsers());
    }
    if (createAdminUserBtn) {
        createAdminUserBtn.addEventListener('click', () => openUserEditor(null));
    }
    if (adminUsersList) {
        adminUsersList.addEventListener('click', onAdminUsersListClick);
    }
    initUserEditorModal();
    initUserPasswordModal();
    initOwnPasswordModal();
    authOpenBtn.addEventListener('click', () => openAuthModal('login'));
    logoutBtn.addEventListener('click', logout);
    authBackdrop.addEventListener('click', closeAuthModal);

    // Telegram link button
    const telegramLinkBtn = document.getElementById('telegramLinkBtn');
    if (telegramLinkBtn) {
        telegramLinkBtn.addEventListener('click', openTelegramLinkModal);
    }
    const telegramLinkBackdrop = document.getElementById('telegramLinkBackdrop');
    if (telegramLinkBackdrop) {
        telegramLinkBackdrop.addEventListener('click', closeTelegramLinkModal);
    }
    const telegramLinkCloseBtn = document.getElementById('telegramLinkCloseBtn');
    if (telegramLinkCloseBtn) {
        telegramLinkCloseBtn.addEventListener('click', closeTelegramLinkModal);
    }
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
    window.AdminPipelineUI?.init({
        change: (key, value) => {
            setAdminSettingsDraftValue(key, value);
            if (_adminSettingsCache) renderAdminSettings(_adminSettingsCache, adminSettingsSearch?.value || '');
        },
        save: saveAdminSettingsDraft,
        reset: resetAdminSettingsDraft,
        reload: () => loadAdminSettings({force: true}),
        openSetting: async (key) => {
            if (adminSettingsSearch) adminSettingsSearch.value = '';
            adminSettingsTab?.click();
            await loadAdminSettings();
            const input = adminSettings.querySelector(`[data-setting-input="${CSS.escape(key)}"]`);
            const group = input?.closest('.admin-settings-group');
            if (group?.classList.contains('is-collapsed')) {
                group.classList.remove('is-collapsed');
                updateAdminSettingsGroupCollapsedUi(group, false);
            }
            input?.scrollIntoView({block: 'center'});
            input?.focus();
        },
    });
    updateAdminSettingsDraftToolbar();
    initTooltips();
    initMermaidLightboxClicks();
    if (messageInput) {
        messageInput.maxLength = CHAT_MESSAGE_MAX_LENGTH;
    }
    initAttachmentControls();

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
    const telegramLinkBtn = document.getElementById('telegramLinkBtn');
    if (telegramLinkBtn) {
        telegramLinkBtn.hidden = !currentAuth.authenticated;
    }
    const changePasswordBtn = document.getElementById('changePasswordBtn');
    if (changePasswordBtn) {
        changePasswordBtn.hidden = !currentAuth.authenticated;
    }
    document.querySelectorAll('.admin-only').forEach((node) => {
        node.hidden = !isAdminRole;
    });
    if (!isAdminRole) {
        _adminSettingsRequestId += 1;
        _adminSettingsCache = null;
        _adminSettingsBaseByKey = {};
        _adminSettingsDraft = {};
        _adminSettingsDirty = new Set();
        _adminSettingsError = '';
        if (adminSettings) adminSettings.innerHTML = '';
        updateAdminSettingsDraftToolbar();
    }
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

function openTelegramLinkModal() {
    const modal = document.getElementById('telegramLinkModal');
    if (!modal) return;
    const loading = document.getElementById('telegramLinkLoading');
    const result = document.getElementById('telegramLinkResult');
    const error = document.getElementById('telegramLinkError');
    const codeEl = document.getElementById('telegramLinkCode');
    if (loading) loading.hidden = false;
    if (result) result.hidden = true;
    if (error) { error.hidden = true; error.textContent = ''; }
    modal.hidden = false;

    apiJson('/api/telegram/link', {method: 'POST'})
        .then((data) => {
            if (data && data.code) {
                codeEl.textContent = `/start ${data.code}`;
                if (loading) loading.hidden = true;
                if (result) result.hidden = false;
            } else {
                throw new Error('Не удалось получить код');
            }
        })
        .catch((err) => {
            if (loading) loading.hidden = true;
            if (error) { error.textContent = err.message || 'Ошибка'; error.hidden = false; }
        });
}

function closeTelegramLinkModal() {
    const modal = document.getElementById('telegramLinkModal');
    if (modal) modal.hidden = true;
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
    abortActiveStream();
    try {
        currentAuth = await apiJson('/api/auth/logout', {method: 'POST'});
        setCurrentChatId(null);
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

function isFrontendOptimizationDebugEnabled() {
    try {
        return localStorage.getItem(FRONTEND_OPTIMIZATION_DEBUG_STORAGE_KEY) === '1';
    } catch (_) {
        return false;
    }
}

function logFrontendOptimization(event, details = {}) {
    if (!isFrontendOptimizationDebugEnabled()) {
        return;
    }
    console.debug('[frontend-optimization]', event, details);
}

function runWhenIdle(callback, options = {}) {
    const timeout = options.timeout ?? 1500;
    const idle = window.requestIdleCallback;
    if (typeof idle === 'function') {
        return idle(callback, {timeout});
    }
    return setTimeout(() => callback({
        didTimeout: true,
        timeRemaining: () => 0,
    }), Math.min(timeout, 250));
}

function deferPostAnswerWork(messageEl, work, options = {}) {
    if (!messageEl || typeof work !== 'function') {
        return null;
    }
    const handle = runWhenIdle(() => {
        if (!messageEl.isConnected) {
            logFrontendOptimization('post-answer-skipped-detached');
            return;
        }
        work();
    }, options);
    return handle;
}

function schedulePostAnswerEnhancements(messageEl, details = {}) {
    deferPostAnswerWork(messageEl, () => loadFollowupSuggestions(messageEl, details), {timeout: 1800});
    deferPostAnswerWork(messageEl, () => loadRelatedDocuments(messageEl, details.sources || []), {timeout: 2200});
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
    document.querySelector('.main-shell')?.classList.toggle('admin-workspace-open', panelId === 'adminPanel');
    if (panelId === 'documentsPanel') {
        loadDocuments();
    }
    if (panelId === 'adminPanel') {
        loadAdminOverview();
    }
    updateAdminSettingsDraftToolbar();
}

async function checkHealth() {
    try {
        const data = await apiJson('/api/health');
        const status = String(data.status || '').toLowerCase();
        const ragOk = data.rag !== false;
        const servicesOk = Boolean(data.ollama && data.database && ragOk);

        if (status === 'ok' || (!status && servicesOk)) {
            statusDot.className = 'status-dot online';
            statusText.textContent = 'Сервис доступен';
            if (serviceStatus) serviceStatus.setAttribute('data-state', 'ok');
            return;
        }
        if (status === 'degraded' || (!status && data.database)) {
            statusDot.className = 'status-dot degraded';
            statusText.textContent = 'Частично';
            if (serviceStatus) serviceStatus.setAttribute('data-state', 'degraded');
            return;
        }
        statusDot.className = 'status-dot offline';
        statusText.textContent = 'Ошибка подключения';
        if (serviceStatus) serviceStatus.setAttribute('data-state', 'down');
    } catch (error) {
        statusDot.className = 'status-dot offline';
        statusText.textContent = 'Ошибка подключения';
        if (serviceStatus) serviceStatus.setAttribute('data-state', 'down');
    }
}

function conversationHasUserContent() {
    if (!messagesContainer) return false;
    const nodes = [...messagesContainer.querySelectorAll('.message')];
    return nodes.some((node) => {
        if (node.classList.contains('welcome-message') || node.classList.contains('system-message')) {
            return false;
        }
        if (node.classList.contains('typing-indicator')) {
            return false;
        }
        return true;
    });
}

function syncEmptyTilesState() {
    if (!emptyTiles || !chatContainer) return;
    const isEmpty = !conversationHasUserContent();
    emptyTiles.hidden = !isEmpty;
    chatContainer.classList.toggle('is-empty', isEmpty);
    chatContainer.classList.toggle('has-empty-tiles', isEmpty);
    if (continueTileHint) {
        const last = _chatListCache[0];
        continueTileHint.textContent = last?.title
            ? last.title
            : 'Откройте последний диалог из истории.';
    }
}

function handleEmptyTileAction(action) {
    switch (action) {
        case 'question':
            messageInput?.focus();
            break;
        case 'source':
            if ((currentSources && currentSources.length) || (currentCitations && currentCitations.length)) {
                openSourcesPanel();
            } else {
                messageInput.value = messageInput.value || '';
                messageInput.focus();
                messageInput.placeholder = 'Уточните тему или название документа…';
            }
            break;
        case 'continue': {
            const last = _chatListCache[0];
            if (last?.id) {
                openChat(last.id);
            } else {
                showInlineError('Нет сохранённых диалогов для продолжения');
            }
            break;
        }
        case 'library':
            if (currentAuth.role === 'admin') {
                switchPanel('documentsPanel');
            } else {
                showInlineError('Раздел «База знаний» доступен только администратору');
            }
            break;
        default:
            break;
    }
}

function initEmptyTiles() {
    if (!emptyTiles) return;
    emptyTiles.querySelectorAll('[data-tile]').forEach((tile) => {
        tile.addEventListener('click', () => handleEmptyTileAction(tile.dataset.tile));
    });
    syncEmptyTilesState();
}

function initSidebarToggle() {
    if (!sidebarToggle || !workspaceSidebar) return;
    const closeSidebar = () => {
        workspaceSidebar.classList.remove('is-open');
        sidebarToggle.setAttribute('aria-expanded', 'false');
        sidebarToggle.setAttribute('aria-label', 'Открыть список диалогов');
    };
    const openSidebar = () => {
        workspaceSidebar.classList.add('is-open');
        sidebarToggle.setAttribute('aria-expanded', 'true');
        sidebarToggle.setAttribute('aria-label', 'Закрыть список диалогов');
        chatSearchInput?.focus();
    };
    sidebarToggle.addEventListener('click', () => {
        if (workspaceSidebar.classList.contains('is-open')) {
            closeSidebar();
        } else {
            openSidebar();
        }
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && workspaceSidebar.classList.contains('is-open')) {
            closeSidebar();
            sidebarToggle.focus();
        }
    });
}

function isSourcesDrawerMode() {
    return sourcesDrawerMedia.matches;
}

function readSourcesCollapsedPreference() {
    try {
        return localStorage.getItem(SOURCES_PANEL_COLLAPSED_KEY) === '1';
    } catch (_) {
        return false;
    }
}

function applySourcesCollapsed(collapsed) {
    const hideColumn = Boolean(collapsed) && !isSourcesDrawerMode();
    mainShell?.classList.toggle('sources-collapsed', hideColumn);
    if (sourcesPanel) {
        sourcesPanel.toggleAttribute('hidden', hideColumn);
        if (hideColumn) {
            sourcesPanel.classList.remove('open');
        }
    }
    if (closeSources) {
        closeSources.setAttribute('aria-expanded', hideColumn ? 'false' : 'true');
    }
    if (sourcesReveal) {
        sourcesReveal.hidden = !hideColumn;
        sourcesReveal.setAttribute('aria-expanded', hideColumn ? 'false' : 'true');
    }
}

function setSourcesCollapsed(collapsed, {focusReveal = false} = {}) {
    try {
        localStorage.setItem(SOURCES_PANEL_COLLAPSED_KEY, collapsed ? '1' : '0');
    } catch (_) {}
    applySourcesCollapsed(collapsed);
    if (focusReveal && collapsed && !isSourcesDrawerMode()) {
        sourcesReveal?.focus();
    }
}

function ensureSourcesRevealButton() {
    if (sourcesReveal || !mainShell) {
        return sourcesReveal;
    }
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'sources-reveal';
    button.id = 'sourcesReveal';
    button.hidden = true;
    button.setAttribute('aria-controls', 'sourcesPanel');
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-label', 'Показать источники');
    button.title = 'Показать источники';
    button.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg><span>Источники</span>';
    mainShell.appendChild(button);
    sourcesReveal = button;
    return button;
}

function initSourcesCollapse() {
    ensureSourcesRevealButton();
    sourcesReveal?.addEventListener('click', () => {
        setSourcesCollapsed(false);
        closeSources?.focus();
    });
    applySourcesCollapsed(readSourcesCollapsedPreference());
    const onModeChange = () => applySourcesCollapsed(readSourcesCollapsedPreference());
    if (typeof sourcesDrawerMedia.addEventListener === 'function') {
        sourcesDrawerMedia.addEventListener('change', onModeChange);
    } else if (typeof sourcesDrawerMedia.addListener === 'function') {
        sourcesDrawerMedia.addListener(onModeChange);
    }
}

async function loadChats(search = '') {
    const seq = ++_chatListRequestSeq;
    try {
        _chatListSearch = search;
        const qs = search ? `?q=${encodeURIComponent(search)}` : '';
        const data = await apiJson(`/api/chats${qs}`);
        // Игнорируем устаревший ответ, если уже ушёл более новый запрос поиска.
        if (seq !== _chatListRequestSeq) {
            return;
        }
        _chatListCache = data.chats || [];
        renderChatList(_chatListCache);
    } catch (error) {
        if (seq !== _chatListRequestSeq) {
            return;
        }
        chatList.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    }
}

function getStoredActiveChatId() {
    try {
        const value = sessionStorage.getItem(ACTIVE_CHAT_STORAGE_KEY);
        return value && /^[\w:-]+$/.test(value) ? value : null;
    } catch (_) {
        return null;
    }
}

function rememberActiveChat(chatId) {
    try {
        if (chatId) {
            sessionStorage.setItem(ACTIVE_CHAT_STORAGE_KEY, String(chatId));
        } else {
            sessionStorage.removeItem(ACTIVE_CHAT_STORAGE_KEY);
        }
    } catch (_) {
        /* ignore storage failures */
    }
}

function setCurrentChatId(chatId) {
    currentChatId = chatId || null;
    rememberActiveChat(currentChatId);
    updateActiveChatListItem();
}

function updateActiveChatListItem() {
    if (!chatList) {
        return;
    }
    const activeId = currentChatId == null ? '' : String(currentChatId);
    chatList.querySelectorAll('.chat-list-item').forEach((item) => {
        item.classList.toggle('active', item.dataset.chatId === activeId);
    });
}

function normalizeChatListItem(chat = {}) {
    const id = chat.id || chat.chat_id;
    if (!id) {
        return null;
    }
    return {
        id,
        title: chat.title || chat.chat_title,
        updated_at: chat.updated_at || chat.updatedAt,
    };
}

function shouldUseLocalChatListUpdate() {
    return !_chatListSearch && !(chatSearchInput?.value || '').trim();
}

function upsertChatListItem(chat = {}) {
    const normalized = normalizeChatListItem(chat);
    if (!normalized || !shouldUseLocalChatListUpdate()) {
        return false;
    }
    const existing = _chatListCache.find((item) => String(item.id) === String(normalized.id));
    const nextItem = {
        ...existing,
        ...normalized,
        title: normalized.title || existing?.title || 'Новый чат',
        updated_at: normalized.updated_at || new Date().toISOString(),
    };
    const withoutCurrent = _chatListCache.filter((item) => String(item.id) !== String(normalized.id));
    _chatListCache = [nextItem, ...withoutCurrent];
    renderChatList(_chatListCache);
    logFrontendOptimization('chat-list-upsert', {chatId: normalized.id});
    return true;
}

function updateCachedChatTitle(chatId, title) {
    if (!chatId || !shouldUseLocalChatListUpdate()) {
        return false;
    }
    let updated = false;
    _chatListCache = _chatListCache.map((chat) => {
        if (String(chat.id) !== String(chatId)) {
            return chat;
        }
        updated = true;
        return {
            ...chat,
            title,
            updated_at: chat.updated_at || new Date().toISOString(),
        };
    });
    if (updated) {
        renderChatList(_chatListCache);
        logFrontendOptimization('chat-list-title', {chatId});
    }
    return updated;
}

function removeCachedChat(chatId) {
    if (!chatId || !shouldUseLocalChatListUpdate()) {
        return false;
    }
    const next = _chatListCache.filter((chat) => String(chat.id) !== String(chatId));
    if (next.length === _chatListCache.length) {
        return false;
    }
    _chatListCache = next;
    renderChatList(_chatListCache);
    logFrontendOptimization('chat-list-remove', {chatId});
    return true;
}

async function restoreActiveChatAfterReload() {
    const storedChatId = getStoredActiveChatId();
    if (!storedChatId || currentChatId) {
        return;
    }
    await openChat(storedChatId, {restore: true});
}

function renderChatList(chats) {
    chatList.innerHTML = '';
    if (!chats.length) {
        chatList.innerHTML = '<div class="empty-state">История пуста</div>';
        syncEmptyTilesState();
        return;
    }
    chats.forEach((chat) => {
        const item = document.createElement('button');
        item.className = `chat-list-item ${String(chat.id) === String(currentChatId) ? 'active' : ''}`;
        item.type = 'button';
        item.dataset.chatId = String(chat.id);
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
    syncEmptyTilesState();
}

async function openChat(chatId, options = {}) {
    abortActiveStream();
    try {
        const data = await apiJson(`/api/chats/${chatId}`);
        setCurrentChatId(data.chat.id);
        resetMessages(false);
        (data.messages || []).forEach((msg) => {
            const type = msg.role === 'assistant' ? 'bot' : 'user';
            const messageEl = addMessage(msg.content, type, {
                sources: msg.sources || [],
                citations: msg.citations || [],
                messageId: msg.id,
                attachments: (msg.metadata && msg.metadata.attachments) || [],
                images: (msg.metadata && msg.metadata.images) || [],
            });
            if (type === 'bot' && ((msg.sources || []).length || (msg.citations || []).length)) {
                addSourcesButton(messageEl, msg.sources || [], msg.citations || []);
                addVerifyButton(messageEl, {
                    answer: msg.content,
                    sources: msg.sources || [],
                    citations: msg.citations || [],
                });
                schedulePostAnswerEnhancements(messageEl, {
                    answer: msg.content,
                    sources: msg.sources || [],
                    citations: msg.citations || [],
                });
            }
            if (type === 'bot') {
                addFeedbackControls(messageEl, msg.id);
                addIssueReportButton(messageEl, msg.id);
            }
        });
        window.SolutionsUI?.setSession(data.chat.id);
        updateActiveChatListItem();
        switchPanel('chatPanel');
        syncEmptyTilesState();
        messageInput.focus();
    } catch (error) {
        if (options.restore) {
            setCurrentChatId(null);
            resetMessages(true);
            loadChats(chatSearchInput.value.trim());
            return;
        }
        showInlineError(error.message);
    }
}

async function startNewChat() {
    abortActiveStream();
    try {
        const chat = await apiJson('/api/chats', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title: 'Новый чат'}),
        });
        setCurrentChatId(chat.id);
        resetMessages(true);
        if (!upsertChatListItem(chat)) {
            loadChats(chatSearchInput.value.trim());
        }
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
        if (!updateCachedChatTitle(chat.id, title.trim())) {
            loadChats(chatSearchInput.value.trim());
        }
    } catch (error) {
        showInlineError(error.message);
    }
}

async function deleteChat(chatId) {
    if (!confirm('Удалить этот чат?')) {
        return;
    }
    if (currentChatId === chatId) {
        abortActiveStream();
    }
    try {
        await apiJson(`/api/chats/${chatId}`, {method: 'DELETE'});
        if (currentChatId === chatId) {
            setCurrentChatId(null);
            resetMessages(true);
        }
        if (!removeCachedChat(chatId)) {
            loadChats(chatSearchInput.value.trim());
        }
    } catch (error) {
        showInlineError(error.message);
    }
}

async function clearAllChats() {
    if (!confirm('Очистить все чаты? Это действие нельзя отменить.')) {
        return;
    }
    abortActiveStream();
    try {
        await apiJson('/api/chats', {method: 'DELETE'});
        setCurrentChatId(null);
        chatSearchInput.value = '';
        resetMessages(true);
        _chatListCache = [];
        _chatListSearch = '';
        renderChatList(_chatListCache);
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
    setCurrentChatId(chat.id);
    if (!upsertChatListItem(chat)) {
        loadChats(chatSearchInput.value.trim());
    }
    return currentChatId;
}

function resetMessages(withWelcome) {
    messagesContainer.innerHTML = '';
    currentSources = [];
    currentCitations = [];
    closeSourcesPanel();
    if (withWelcome) {
        // Option D: empty/new chat shows tiles instead of a welcome bubble.
        syncEmptyTilesState();
        return;
    }
    syncEmptyTilesState();
}

function removeWelcomeMessage() {
    const welcome = messagesContainer.querySelector('.welcome-message');
    if (welcome) {
        welcome.remove();
    } else {
        const first = messagesContainer.querySelector('.message.bot-message');
        const text = first?.querySelector('.message-content')?.innerText?.trim();
        if (text === WELCOME_MESSAGE) {
            first.remove();
        }
    }
    syncEmptyTilesState();
}

async function sendChatClassic(message, payload = null) {
    const data = await apiJson('/api/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload || buildChatPayload(message)),
    });
    hideTypingIndicator();
    const botMessage = addMessage(data.answer, 'bot', {
        sources: data.sources || [],
        citations: data.citations || [],
        messageId: data.message_id,
        images: data.images || [],
    });
    setCurrentChatId(data.chat_id || currentChatId);
    addSourcesButton(botMessage, data.sources || [], data.citations || []);
    addVerifyButton(botMessage, {
        answer: data.answer,
        sources: data.sources || [],
        citations: data.citations || [],
    });
    schedulePostAnswerEnhancements(botMessage, {
        answer: data.answer,
        sources: data.sources || [],
        citations: data.citations || [],
    });
    addFeedbackControls(botMessage, data.message_id);
    addIssueReportButton(botMessage, data.message_id);
    if (!upsertChatListItem({
        id: data.chat_id || currentChatId,
        title: data.chat_title || data.title,
        updated_at: data.updated_at,
    })) {
        loadChats(chatSearchInput.value.trim());
    }
}

function initAttachmentControls() {
    if (attachButton && attachmentFileInput) {
        attachButton.addEventListener('click', () => {
            if (!isProcessing) {
                attachmentFileInput.click();
            }
        });
        attachmentFileInput.addEventListener('change', onAttachmentFilesSelected);
    }
    if (messageInput) {
        messageInput.addEventListener('paste', onMessageInputPaste);
    }
    const dropTarget = document.querySelector('.input-area');
    if (dropTarget) {
        let dragDepth = 0;
        const setDragState = (active) => dropTarget.classList.toggle('is-drag-over', active);
        dropTarget.addEventListener('dragenter', (event) => {
            if (isProcessing || !event.dataTransfer?.types?.includes('Files')) return;
            event.preventDefault();
            dragDepth += 1;
            setDragState(true);
        });
        dropTarget.addEventListener('dragover', (event) => {
            if (isProcessing || !event.dataTransfer?.types?.includes('Files')) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = 'copy';
        });
        dropTarget.addEventListener('dragleave', (event) => {
            if (!event.relatedTarget || !dropTarget.contains(event.relatedTarget)) {
                dragDepth = 0;
                setDragState(false);
            } else {
                dragDepth = Math.max(0, dragDepth - 1);
                if (!dragDepth) setDragState(false);
            }
        });
        dropTarget.addEventListener('drop', async (event) => {
            if (isProcessing) return;
            event.preventDefault();
            dragDepth = 0;
            setDragState(false);
            await uploadAttachmentFiles(Array.from(event.dataTransfer?.files || []));
        });
    }
}

function clipboardImageFiles(clipboardData) {
    if (!clipboardData || !clipboardData.items) {
        return [];
    }
    const files = [];
    for (const item of clipboardData.items) {
        if (!item.type || !item.type.startsWith('image/')) {
            continue;
        }
        const blob = item.getAsFile();
        if (!blob) {
            continue;
        }
        const subtype = (item.type.split('/')[1] || 'png').split('+')[0];
        const ext = subtype === 'jpeg' ? 'jpg' : subtype;
        const filename = `screenshot-${Date.now()}.${ext}`;
        files.push(new File([blob], filename, {type: blob.type || item.type}));
    }
    return files;
}

async function onMessageInputPaste(event) {
    if (isProcessing) {
        return;
    }
    const imageFiles = clipboardImageFiles(event.clipboardData);
    if (!imageFiles.length) {
        return;
    }
    event.preventDefault();
    await uploadAttachmentFiles(imageFiles);
}

function renderAttachmentPreview() {
    if (!attachmentPreview) {
        return;
    }
    attachmentPreview.innerHTML = '';
    if (!pendingAttachments.length) {
        attachmentPreview.hidden = true;
        return;
    }
    attachmentPreview.hidden = false;
    pendingAttachments.forEach((item) => {
        const chip = document.createElement('div');
        chip.className = 'attachment-chip';
        chip.dataset.attachmentId = item.id;

        if (item.kind === 'image') {
            const img = document.createElement('img');
            img.className = 'attachment-chip-thumb';
            img.src = `/api/chat/attachments/${encodeURIComponent(item.id)}`;
            img.alt = item.filename || 'Изображение';
            chip.appendChild(img);
        } else {
            const label = document.createElement('span');
            label.className = 'attachment-chip-name';
            label.textContent = item.filename || 'Файл';
            chip.appendChild(label);
        }

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'attachment-chip-remove';
        removeBtn.setAttribute('aria-label', 'Удалить вложение');
        removeBtn.textContent = '×';
        removeBtn.addEventListener('click', () => {
            pendingAttachments = pendingAttachments.filter((entry) => entry.id !== item.id);
            renderAttachmentPreview();
        });
        chip.appendChild(removeBtn);
        attachmentPreview.appendChild(chip);
    });
}

async function onAttachmentFilesSelected(event) {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    await uploadAttachmentFiles(files);
}

async function uploadAttachmentFiles(files) {
    if (!files.length) {
        return;
    }

    const slotsLeft = CHAT_ATTACHMENT_MAX_COUNT - pendingAttachments.length;
    if (slotsLeft <= 0) {
        showInlineError(`Можно прикрепить не более ${CHAT_ATTACHMENT_MAX_COUNT} файлов.`);
        return;
    }

    const batch = files.slice(0, slotsLeft);
    if (files.length > slotsLeft) {
        showInlineError(`Добавлены первые ${slotsLeft} файла(ов): лимит ${CHAT_ATTACHMENT_MAX_COUNT}.`);
    }

    for (const file of batch) {
        if (file.size > CHAT_ATTACHMENT_MAX_BYTES) {
            showInlineError(`Файл «${file.name}» слишком большой (макс. 5 МБ).`);
            continue;
        }
        const formData = new FormData();
        formData.append('files', file);
        try {
            const response = await fetch('/api/chat/attachments', {
                method: 'POST',
                credentials: 'same-origin',
                body: formData,
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                showInlineError(data.error || `Не удалось загрузить «${file.name}»`);
                continue;
            }
            (data.attachments || []).forEach((item) => pendingAttachments.push(item));
        } catch (error) {
            showInlineError(`Ошибка загрузки «${file.name}»: ${error.message}`);
        }
    }
    renderAttachmentPreview();
}

function clearPendingAttachments() {
    pendingAttachments = [];
    renderAttachmentPreview();
}

function renderMessageAttachments(container, attachments) {
    if (!attachments || !attachments.length) {
        return;
    }
    const wrap = document.createElement('div');
    wrap.className = 'message-attachments';
    attachments.forEach((item) => {
        if (!item || !item.id) {
            return;
        }
        if (item.kind === 'image') {
            const img = document.createElement('img');
            img.className = 'message-attachment-image';
            img.src = `/api/chat/attachments/${encodeURIComponent(item.id)}`;
            img.alt = item.filename || 'Вложение';
            img.loading = 'lazy';
            wrap.appendChild(img);
        } else {
            const link = document.createElement('a');
            link.className = 'message-attachment-file';
            link.href = `/api/chat/attachments/${encodeURIComponent(item.id)}`;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = item.filename || 'Текстовый файл';
            wrap.appendChild(link);
        }
    });
    container.appendChild(wrap);
}

// --- Изображения из источников базы знаний (ТЗ §16.3) ------------------------

function kbImageLocationLabel(item) {
    const parts = [];
    if (item.page != null) parts.push(`стр. ${item.page}`);
    if (item.slide != null) parts.push(`слайд ${item.slide}`);
    if (item.sheet) parts.push(`лист ${item.sheet}`);
    return parts.join(', ');
}

function openKbImageModal(item) {
    const src = item.url || item.thumbnail_url;
    if (!src) return;
    const root = document.createElement('div');
    root.className = 'kb-image-lightbox';
    const backdrop = document.createElement('div');
    backdrop.className = 'kb-image-lightbox__backdrop';
    const dialog = document.createElement('div');
    dialog.className = 'kb-image-lightbox__dialog';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    const img = document.createElement('img');
    img.src = src;
    img.alt = item.caption || item.title || 'Изображение источника';
    const caption = document.createElement('div');
    caption.className = 'kb-image-lightbox__caption';
    const loc = kbImageLocationLabel(item);
    caption.textContent = [item.source_title || item.title, item.section_path, loc]
        .filter(Boolean).join(' — ');
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'kb-image-lightbox__close';
    close.setAttribute('aria-label', 'Закрыть');
    close.textContent = '×';
    const closeAll = () => {
        root.remove();
        document.body.classList.remove('kb-image-lightbox-open');
        document.removeEventListener('keydown', onKey);
    };
    const onKey = (event) => {
        if (event.key === 'Escape') closeAll();
    };
    backdrop.addEventListener('click', closeAll);
    close.addEventListener('click', closeAll);
    document.addEventListener('keydown', onKey);
    dialog.append(close, img, caption);
    root.append(backdrop, dialog);
    document.body.appendChild(root);
    document.body.classList.add('kb-image-lightbox-open');
}

function renderKnowledgeImages(messageEl, images) {
    if (!messageEl || !images || !images.length) {
        return;
    }
    const content = messageEl.querySelector('.message-content');
    if (!content || content.querySelector('.kb-images')) {
        return;
    }
    const wrap = document.createElement('div');
    wrap.className = 'kb-images';
    const heading = document.createElement('div');
    heading.className = 'kb-images__heading';
    heading.textContent = 'Изображения из источников';
    wrap.appendChild(heading);

    const grid = document.createElement('div');
    grid.className = 'kb-images__grid';
    images.forEach((item) => {
        if (!item || !(item.url || item.thumbnail_url)) return;
        const card = document.createElement('figure');
        card.className = 'kb-image-card';
        if (item.visual_type) card.dataset.visualType = item.visual_type;

        const thumb = document.createElement('img');
        thumb.className = 'kb-image-card__thumb';
        thumb.loading = 'lazy';
        thumb.src = item.thumbnail_url || item.url;
        thumb.alt = item.caption || item.title || 'Изображение источника';
        thumb.addEventListener('click', () => openKbImageModal(item));
        thumb.addEventListener('error', () => {
            if (item.url && thumb.src !== item.url) thumb.src = item.url;
        });
        card.appendChild(thumb);

        const meta = document.createElement('figcaption');
        meta.className = 'kb-image-card__meta';
        const title = document.createElement('div');
        title.className = 'kb-image-card__title';
        title.textContent = item.caption || item.title || item.source_title || 'Изображение';
        meta.appendChild(title);
        const subParts = [item.source_title, item.section_path, kbImageLocationLabel(item)].filter(Boolean);
        if (subParts.length) {
            const sub = document.createElement('div');
            sub.className = 'kb-image-card__sub';
            if (item.evidence_label) {
                const badge = document.createElement('span');
                badge.className = 'kb-image-card__badge';
                badge.textContent = item.evidence_label;
                sub.appendChild(badge);
            }
            sub.appendChild(document.createTextNode(subParts.join(' — ')));
            meta.appendChild(sub);
        }
        if (item.source_path || item.source_url) {
            const link = document.createElement('button');
            link.type = 'button';
            link.className = 'kb-image-card__source';
            link.textContent = 'Открыть источник';
            link.addEventListener('click', () => {
                if (item.source_url) {
                    window.open(item.source_url, '_blank', 'noopener');
                } else if (item.source_path) {
                    openDocumentFromSource({path: item.source_path});
                }
            });
            meta.appendChild(link);
        }
        card.appendChild(meta);
        grid.appendChild(card);
    });
    wrap.appendChild(grid);
    content.appendChild(wrap);
}

async function handleSubmit(e) {
    e.preventDefault();
    const message = messageInput.value.trim();
    if (isProcessing) {
        return;
    }
    const payload = validateChatPayload(message);
    if (!payload) {
        return;
    }

    await ensureChat();
    payload.chat_id = currentChatId;
    removeWelcomeMessage();
    const sentAttachments = [...(payload.attachment_ids || [])].map((id) => {
        return pendingAttachments.find((item) => item.id === id) || {id, kind: 'text'};
    });
    addMessage(payload.message, 'user', {attachments: sentAttachments});
    messageInput.value = '';
    clearPendingAttachments();
    const requestId = startStreamRequest();
    showTypingIndicator();
    setProcessingState(true);

    try {
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            credentials: 'same-origin',
            signal: activeStreamController.signal,
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream',
            },
            body: JSON.stringify(payload),
        });

        if (response.status === 404) {
            if (isActiveStreamRequest(requestId)) {
                await sendChatClassic(payload.message, payload);
            }
            return;
        }

        hideTypingIndicator();
        if (!isActiveStreamRequest(requestId)) {
            return;
        }
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            showInlineError(errData.error || `Ошибка ${response.status}`);
            return;
        }
        if (!response.body || !response.body.getReader) {
            showInlineError('Поток ответа недоступен в этом браузере');
            return;
        }

        await readStream(response, requestId);
    } catch (error) {
        if (error.name === 'AbortError' || !isActiveStreamRequest(requestId)) {
            return;
        }
        hideTypingIndicator();
        showInlineError(`Произошла ошибка при отправке запроса: ${error.message}`);
    } finally {
        if (isActiveStreamRequest(requestId)) {
            clearActiveStream(requestId);
            setProcessingState(false);
            messageInput.focus();
            if (shouldUseLocalChatListUpdate()) {
                updateActiveChatListItem();
            } else {
                loadChats(chatSearchInput.value.trim());
            }
        }
    }
}

function buildChatPayload(message, overrides = {}) {
    const attachmentIds = pendingAttachments.map((item) => item.id).filter(Boolean);
    return {
        message,
        chat_id: currentChatId,
        answer_mode: answerModeSelect.value,
        top_k: Number(topKInput.value),
        min_score: Number(minScoreInput.value),
        attachment_ids: attachmentIds,
        ...overrides,
    };
}

function validateChatPayload(message) {
    const hasAttachments = pendingAttachments.length > 0;
    if (!message && !hasAttachments) {
        showInlineError('Введите сообщение или прикрепите файл.');
        messageInput.focus();
        return null;
    }
    if (message && message.length < CHAT_MESSAGE_MIN_LENGTH && !hasAttachments) {
        showInlineError(`Сообщение должно быть не короче ${CHAT_MESSAGE_MIN_LENGTH} символа.`);
        messageInput.focus();
        return null;
    }
    if (message.length > CHAT_MESSAGE_MAX_LENGTH) {
        showInlineError(`Сообщение должно быть от ${CHAT_MESSAGE_MIN_LENGTH} до ${CHAT_MESSAGE_MAX_LENGTH} символов.`);
        messageInput.focus();
        return null;
    }

    const topK = Number(topKInput.value);
    if (!Number.isInteger(topK) || topK < CHAT_TOP_K_MIN || topK > CHAT_TOP_K_MAX) {
        showInlineError(`Количество источников должно быть целым числом от ${CHAT_TOP_K_MIN} до ${CHAT_TOP_K_MAX}.`);
        topKInput.focus();
        return null;
    }

    const minScore = Number(minScoreInput.value);
    if (!Number.isFinite(minScore) || minScore < CHAT_MIN_SCORE_MIN || minScore > CHAT_MIN_SCORE_MAX) {
        showInlineError('Минимальная релевантность должна быть числом от 0 до 1.');
        minScoreInput.focus();
        return null;
    }

    const allowedModes = new Set([...answerModeSelect.options].map((option) => option.value));
    const answerMode = answerModeSelect.value;
    if (!allowedModes.has(answerMode)) {
        showInlineError('Выберите допустимый стиль ответа.');
        answerModeSelect.focus();
        return null;
    }

    return buildChatPayload(message, {
        answer_mode: answerMode,
        top_k: topK,
        min_score: minScore,
    });
}

function setProcessingState(processing) {
    isProcessing = processing;
    sendButton.disabled = processing;
}

function startStreamRequest() {
    abortActiveStream();
    activeStreamRequestId += 1;
    activeStreamController = new AbortController();
    return activeStreamRequestId;
}

function isActiveStreamRequest(requestId) {
    return requestId === activeStreamRequestId && activeStreamController;
}

function clearActiveStream(requestId) {
    if (requestId !== activeStreamRequestId) {
        return;
    }
    activeStreamController = null;
}

function abortActiveStream() {
    if (activeStreamController) {
        try {
            activeStreamController.abort();
        } catch (_) {
            /* ignore abort failures */
        }
        activeStreamController = null;
        activeStreamRequestId += 1;
    }
    hideTypingIndicator();
    setProcessingState(false);
}

function isStreamRenderDebugEnabled() {
    if (STREAM_RENDER_DEBUG) {
        return true;
    }
    try {
        return localStorage.getItem(STREAM_RENDER_DEBUG_STORAGE_KEY) === '1';
    } catch (_) {
        return false;
    }
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

async function readStream(response, requestId) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let streamShell = null;
    let streamContent = null;
    let accumulated = '';
    let streamRafId = null;
    let doneReceived = false;
    const streamRenderMetrics = {
        enabled: isStreamRenderDebugEnabled(),
        startedAt: (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now(),
        renderCount: 0,
        accumulatedChars: 0,
        finalChars: 0,
    };

    const logStreamRenderMetrics = (status) => {
        if (!streamRenderMetrics.enabled) {
            return;
        }
        const now = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
        const elapsedMs = Math.max(1, now - streamRenderMetrics.startedAt);
        console.debug('[stream-render]', {
            status,
            renderCount: streamRenderMetrics.renderCount,
            rendersPerSecond: Number((streamRenderMetrics.renderCount / (elapsedMs / 1000)).toFixed(2)),
            accumulatedChars: streamRenderMetrics.accumulatedChars,
            finalChars: streamRenderMetrics.finalChars || streamRenderMetrics.accumulatedChars,
            elapsedMs: Number(elapsedMs.toFixed(1)),
        });
    };

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
        highlightCodeBlocks(streamContent);
        replaceMermaidBlocksWithPlaceholder(streamContent);
        streamRenderMetrics.renderCount += 1;
        streamRenderMetrics.accumulatedChars = accumulated.length;
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
        if (doneReceived || !isActiveStreamRequest(requestId)) {
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
                const textToRender = recoverMermaidInAnswer(accumulated, finalText);
                streamRenderMetrics.finalChars = textToRender.length;
                setCurrentChatId(payload.chat_id || currentChatId);
                ensureStreamShell();
                streamContent.innerHTML = formatMessage(textToRender);
                highlightCodeBlocks(streamContent);
                renderMermaidIn(streamContent);
                streamContent.classList.remove('streaming-in-progress');
                linkifySourceReferences(streamShell, payload.sources || [], payload.citations || []);
                addSourcesButton(streamShell, payload.sources || [], payload.citations || []);
                showSourcesForAnswer(payload.sources || [], payload.citations || []);
                renderKnowledgeImages(streamShell, payload.images || []);
                addVerifyButton(streamShell, {
                    answer: textToRender,
                    sources: payload.sources || [],
                    citations: payload.citations || [],
                });
                schedulePostAnswerEnhancements(streamShell, {
                    answer: textToRender,
                    sources: payload.sources || [],
                    citations: payload.citations || [],
                });
                addFeedbackControls(streamShell, payload.message_id);
                addIssueReportButton(streamShell, payload.message_id);
                upsertChatListItem({
                    id: payload.chat_id || currentChatId,
                    title: payload.chat_title || payload.title,
                    updated_at: payload.updated_at,
                });
                doneReceived = true;
                logStreamRenderMetrics('done');
            } else if (payload.type === 'error') {
                cancelStreamMarkdownFrame();
                ensureStreamShell();
                streamContent.textContent = payload.message || 'Ошибка потока';
                streamShell.classList.add('system-message');
                streamContent.classList.remove('streaming-in-progress');
                doneReceived = true;
                logStreamRenderMetrics('error');
            }
        });
    };

    let processedBlocksSinceYield = 0;
    while (true) {
        const {done, value} = await reader.read();
        if (!isActiveStreamRequest(requestId)) {
            try { await reader.cancel(); } catch (_) { /* ignore */ }
            return;
        }
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
    if (!doneReceived && isActiveStreamRequest(requestId)) {
        cancelStreamMarkdownFrame();
        if (streamShell) {
            streamShell.remove();
        }
        logStreamRenderMetrics('aborted');
        throw new Error('Соединение с потоком ответа прервано до завершения.');
    }
}

function addMessage(text, type, details = {}) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}-message`;
    if (details.system) {
        messageDiv.classList.add('system-message');
    }
    if (details.welcome) {
        messageDiv.classList.add('welcome-message');
    }
    if (details.messageId) {
        messageDiv.dataset.messageId = details.messageId;
    }

    const avatar = createMessageAvatar(type);

    const content = document.createElement('div');
    content.className = 'message-content';
    if (type === 'bot') {
        content.innerHTML = formatMessage(text);
        highlightCodeBlocks(content);
        renderMermaidIn(content);
    } else {
        if (text) {
            const textNode = document.createElement('div');
            textNode.className = 'message-text';
            textNode.textContent = text;
            content.appendChild(textNode);
        }
        renderMessageAttachments(content, details.attachments || []);
    }

    messageDiv.append(avatar, content);
    if (type === 'bot' && details.messageId) {
        window.SolutionsUI?.attach(messageDiv, details.messageId);
    }
    messagesContainer.appendChild(messageDiv);
    if (type === 'bot') {
        linkifySourceReferences(messageDiv, details.sources || [], details.citations || []);
        renderKnowledgeImages(messageDiv, details.images || []);
        if ((details.sources || []).length || (details.citations || []).length) {
            showSourcesForAnswer(details.sources || [], details.citations || []);
        }
    }
    syncEmptyTilesState();
    scrollToBottom();
    return messageDiv;
}

function ensureMarkedConfigured() {
    if (_markedConfigured || typeof marked === 'undefined') {
        return;
    }
    // highlight в setOptions не поддерживается marked v8+; подсветка — после рендера.
    marked.setOptions({
        breaks: true,
        gfm: true,
    });
    _markedConfigured = true;
}

function highlightCodeBlocks(container) {
    if (!container || typeof hljs === 'undefined') {
        return;
    }
    container.querySelectorAll('pre code').forEach((block) => {
        const language = String(block.className || '').toLowerCase();
        if (language.includes('mermaid') || looksLikeMermaid(block.textContent)) {
            return;
        }
        try {
            hljs.highlightElement(block);
        } catch (_) {
            /* ignore */
        }
    });
}

function formatMessage(text) {
    if (typeof marked !== 'undefined') {
        ensureMarkedConfigured();
        const html = marked.parse(text || '');
        if (typeof DOMPurify !== 'undefined') {
            return `<div class="markdown-content">${DOMPurify.sanitize(html)}</div>`;
        }
        // Без DOMPurify HTML не вставляем — только экранированный текст.
        return `<div class="markdown-content"><pre class="markdown-fallback">${escapeHtml(text || '')}</pre></div>`;
    }
    const paragraphs = escapeHtml(text || '').split('\n\n');
    return paragraphs.map((p) => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');
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
    const content = document.createElement('div');
    content.className = 'message-content';
    content.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
    typingDiv.append(createMessageAvatar('bot'), content);
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

function readLocalFlag(key) {
    try {
        return localStorage.getItem(key) === '1';
    } catch (_) {
        return false;
    }
}

function writeLocalFlag(key, enabled) {
    try {
        localStorage.setItem(key, enabled ? '1' : '0');
    } catch (_) {
        /* ignore quota / private mode */
    }
}

function isFollowupSuggestionsEnabled() {
    return Boolean(followupSuggestionsToggle?.checked);
}

function isRelatedDocsEnabled() {
    return Boolean(relatedDocsToggle?.checked);
}

function initChatSuggestionToggles() {
    if (followupSuggestionsToggle) {
        followupSuggestionsToggle.checked = readLocalFlag(CHAT_SHOW_FOLLOWUPS_KEY);
        followupSuggestionsToggle.addEventListener('change', () => {
            writeLocalFlag(CHAT_SHOW_FOLLOWUPS_KEY, followupSuggestionsToggle.checked);
        });
    }
    if (relatedDocsToggle) {
        relatedDocsToggle.checked = readLocalFlag(CHAT_SHOW_RELATED_DOCS_KEY);
        relatedDocsToggle.addEventListener('change', () => {
            writeLocalFlag(CHAT_SHOW_RELATED_DOCS_KEY, relatedDocsToggle.checked);
        });
    }
}

async function loadFollowupSuggestions(messageEl, details = {}) {
    if (!messageEl || !details.answer || messageEl.querySelector('.followup-suggestions')) {
        return;
    }
    if (!isFollowupSuggestionsEnabled()) {
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
    if (!isRelatedDocsEnabled()) {
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

function initializeIssues() {
    if (!issueForm) {
        return;
    }
    loadIssueStatus();
    issueReportOpenBtn?.addEventListener('click', () => openIssueModal());
    issueBackdrop?.addEventListener('click', closeIssueModal);
    issueCloseBtn?.addEventListener('click', closeIssueModal);
    issueCancelBtn?.addEventListener('click', closeIssueModal);
    issueForm.addEventListener('submit', submitIssue);
    document.addEventListener('keydown', (evt) => {
        if (evt.key === 'Escape' && issueModal && !issueModal.hidden) {
            closeIssueModal();
        }
    });
}

async function loadIssueStatus() {
    try {
        issueStatus = await apiJson('/api/issues/status');
        if (issueModeHint && issueStatus.write_hint) {
            issueModeHint.textContent = issueStatus.write_hint;
        } else if (issueModeHint && issueStatus.stub) {
            issueModeHint.textContent = 'Демо-режим: GitHub не настроен, issue сохраняется как заглушка.';
        }
        if (issueType && Array.isArray(issueStatus.types)) {
            issueType.innerHTML = issueStatus.types.map((item) => (
                `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`
            )).join('');
        }
        if (issueReportOpenBtn) {
            issueReportOpenBtn.hidden = issueStatus.enabled === false;
        }
    } catch (_) {
        if (issueModeHint) {
            issueModeHint.textContent = 'Не удалось проверить статус отправки issue.';
        }
    }
}

function openIssueModal(options = {}) {
    if (!issueModal || issueStatus.enabled === false) {
        return;
    }
    issueDraft = {
        sessionId: options.sessionId ?? currentChatId ?? null,
        messageId: options.messageId ?? null,
    };
    if (issueTitleInput) {
        issueTitleInput.value = options.title || '';
    }
    if (issueDescription) {
        issueDescription.value = options.description || '';
    }
    if (issueContact) {
        issueContact.value = '';
    }
    if (issueHp) {
        issueHp.value = '';
    }
    if (issueType && options.type) {
        issueType.value = options.type;
    } else if (issueType && options.messageId) {
        issueType.value = 'wrong_answer';
    }
    if (issueMessage) {
        issueMessage.textContent = '';
    }
    if (issueModeHint) {
        issueModeHint.textContent = issueStatus.stub
            ? 'Демо-режим: GitHub не настроен, issue сохраняется как заглушка.'
            : (options.messageId ? 'К диалогу будет приложен контекст ответа.' : '');
    }
    issueModal.hidden = false;
    issueTitleInput?.focus();
}

function closeIssueModal() {
    if (!issueModal) {
        return;
    }
    issueModal.hidden = true;
    issueDraft = {sessionId: null, messageId: null};
}

async function submitIssue(evt) {
    evt.preventDefault();
    if (!issueSubmitBtn) {
        return;
    }
    issueSubmitBtn.disabled = true;
    if (issueMessage) {
        issueMessage.textContent = 'Отправка...';
    }
    try {
        const payload = {
            type: issueType?.value || 'other',
            title: issueTitleInput?.value?.trim() || '',
            description: issueDescription?.value?.trim() || '',
            contact: issueContact?.value?.trim() || '',
            _gotcha: issueHp?.value || '',
        };
        if (issueDraft.sessionId != null) {
            payload.session_id = issueDraft.sessionId;
        }
        if (issueDraft.messageId != null) {
            payload.message_id = issueDraft.messageId;
        }
        const data = await apiJson('/api/issues', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        closeIssueModal();
        const toastMessage = data.stub
            ? `Обращение принято (демо) #${data.issue_number || ''}`.trim()
            : `Issue #${data.issue_number || ''} создан`;
        if (typeof showToast === 'function') {
            showToast(toastMessage, 'success');
        } else if (issueMessage) {
            issueMessage.textContent = data.message || toastMessage;
        }
    } catch (error) {
        if (issueMessage) {
            issueMessage.textContent = error.message;
        }
    } finally {
        issueSubmitBtn.disabled = false;
    }
}

function addIssueReportButton(messageEl, messageId) {
    if (!messageEl || !messageId) {
        return;
    }
    const content = messageEl.querySelector('.message-content');
    if (!content || content.querySelector('.report-issue-btn')) {
        return;
    }
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'report-issue-btn';
    button.textContent = 'Сообщить об ошибке';
    button.addEventListener('click', () => {
        openIssueModal({
            sessionId: currentChatId,
            messageId,
            type: 'wrong_answer',
            title: 'Ошибка в ответе ассистента',
        });
    });
    content.appendChild(button);
}

function showSourcesEmpty(message = SOURCES_EMPTY_IDLE) {
    if (!sourcesList) {
        return;
    }
    sourcesList.innerHTML = '';
    const empty = document.createElement('p');
    empty.className = 'empty-state';
    empty.id = 'sourcesEmpty';
    empty.textContent = message;
    sourcesList.appendChild(empty);
}

function renderSourcesList(options = {}) {
    if (!sourcesList || !sourcesPanel) {
        return 0;
    }
    const citations = currentCitations || [];
    const sources = currentSources || [];
    const max = Math.max(citations.length, sources.length);
    const focusIndex = Number.isInteger(options.focusIndex) && options.focusIndex >= 0
        ? options.focusIndex
        : findSourceIndexByTitle(options.focusTitle, sources, citations);
    if (!max) {
        showSourcesEmpty(SOURCES_EMPTY_NONE);
    } else {
        sourcesList.innerHTML = '';
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
    sourcesPanel.setAttribute('data-populated', max > 0 ? 'true' : 'false');
    return max;
}

function openSourcesPanel(options = {}) {
    if (!isSourcesDrawerMode() && readSourcesCollapsedPreference()) {
        setSourcesCollapsed(false);
    }
    renderSourcesList(options);
    sourcesPanel.classList.add('open');
    if (isSourcesDrawerMode()) {
        _sourcesFocusRestore = document.activeElement;
        closeSources?.focus();
    }
    const activeSource = sourcesList.querySelector('.source-item--active');
    if (activeSource) {
        activeSource.scrollIntoView({block: 'nearest'});
    }
}

// Автоматически показывает источники ответа в правой панели сразу после ответа модели.
// На мобильных (панель в режиме шторки) список не выдвигается, чтобы не перекрывать чат.
function showSourcesForAnswer(sources = [], citations = [], options = {}) {
    currentSources = sources || [];
    currentCitations = citations || [];
    if (isSourcesDrawerMode()) {
        return;
    }
    const max = renderSourcesList(options);
    if (max > 0 && sourcesPanel) {
        sourcesPanel.scrollTop = 0;
    }
}

function closeSourcesPanel() {
    sourcesPanel.classList.remove('open');
    if (!(currentSources && currentSources.length) && !(currentCitations && currentCitations.length)) {
        sourcesPanel.removeAttribute('data-populated');
        showSourcesEmpty(SOURCES_EMPTY_IDLE);
    }
    if (_sourcesFocusRestore && typeof _sourcesFocusRestore.focus === 'function') {
        _sourcesFocusRestore.focus();
        _sourcesFocusRestore = null;
    }
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
        clearReindexPoll();
        pollJobs();
    } catch (error) {
        setJobStatus(error.message, {state: 'failed'});
    }
}

async function pollJobs() {
    clearReindexPoll();
    try {
        const data = await apiJson('/api/documents/jobs');
        const latest = (data.jobs || [])[0];
        if (latest) {
            renderJob(latest);
            if (latest.status === 'pending' || latest.status === 'running') {
                reindexPollTimer = setTimeout(pollJobs, 2000);
            }
        }
    } catch (_) {
        /* ignore polling errors */
    }
}

function clearReindexPoll() {
    if (reindexPollTimer) {
        clearTimeout(reindexPollTimer);
        reindexPollTimer = null;
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

// ==================== Управление пользователями (админка) ====================

const _adminUsersState = {page: 1, per_page: 25, total: 0, query: '', role: '', status: ''};
let _adminUsersCache = {};

async function loadAdminUsers(page) {
    if (!adminUsersList) {
        return;
    }
    if (currentAuth.role !== 'admin') {
        adminUsersList.innerHTML = '<div class="empty-state">Раздел доступен только администратору</div>';
        return;
    }
    if (typeof page === 'number' && page > 0) {
        _adminUsersState.page = page;
    }
    _adminUsersState.query = (adminUsersSearch?.value || '').trim();
    _adminUsersState.role = adminUsersRoleFilter?.value || '';
    _adminUsersState.status = adminUsersStatusFilter?.value || '';

    adminUsersList.innerHTML = '<div class="empty-state">Загрузка пользователей...</div>';
    if (adminUsersPager) {
        adminUsersPager.innerHTML = '';
    }
    try {
        const params = new URLSearchParams({
            page: String(_adminUsersState.page),
            per_page: String(_adminUsersState.per_page),
        });
        if (_adminUsersState.query) params.set('query', _adminUsersState.query);
        if (_adminUsersState.role) params.set('role', _adminUsersState.role);
        if (_adminUsersState.status) params.set('status', _adminUsersState.status);
        const data = await apiJson(`/api/admin/users?${params.toString()}`);
        _adminUsersState.total = data.total || 0;
        _adminUsersState.page = data.page || 1;
        _adminUsersState.per_page = data.per_page || _adminUsersState.per_page;
        renderAdminUsers(data.users || []);
        renderAdminUsersPager();
    } catch (error) {
        adminUsersList.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    }
}

function renderAdminUsers(users) {
    _adminUsersCache = {};
    users.forEach((user) => {
        _adminUsersCache[user.id] = user;
    });
    if (adminUsersSummary) {
        adminUsersSummary.textContent = users.length ? `Найдено: ${_adminUsersState.total}` : '';
    }
    if (!users.length) {
        adminUsersList.innerHTML = '<div class="empty-state">Пользователи не найдены</div>';
        return;
    }
    const currentUserId = currentAuth?.user?.id;
    adminUsersList.innerHTML = users.map((user) => {
        const stats = user.stats || {};
        const isSelf = user.id === currentUserId;
        const roleLabel = user.role === 'admin' ? 'Администратор' : 'Пользователь';
        const roleClass = user.role === 'admin' ? 'admin-user-badge--admin' : '';
        const statusLabel = user.is_active ? 'Активен' : 'Заблокирован';
        const statusClass = user.is_active ? 'admin-user-badge--active' : 'admin-user-badge--blocked';
        const tg = stats.telegram_linked
            ? ` · Telegram: ${escapeHtml(stats.telegram_username || 'привязан')}`
            : '';
        const selfBadge = isSelf ? ' <span class="admin-user-badge admin-user-badge--self">это вы</span>' : '';
        return `
        <article class="admin-user-card" data-user-id="${user.id}">
            <div class="admin-user-card__main">
                <div class="admin-user-card__title">
                    <strong>${escapeHtml(user.username)}</strong>
                    <span class="admin-user-badge ${roleClass}">${roleLabel}</span>
                    <span class="admin-user-badge ${statusClass}">${statusLabel}</span>${selfBadge}
                </div>
                <div class="admin-user-card__meta">${escapeHtml(user.email)} · чатов: ${stats.chats || 0} · сообщений: ${stats.messages || 0}${tg}</div>
                <div class="admin-user-card__meta admin-user-card__meta--dim">создан: ${formatDate(user.created_at)} · изменён: ${formatDate(user.updated_at)}</div>
            </div>
            <div class="admin-user-card__actions">
                <button class="secondary-btn" type="button" data-user-action="edit" data-user-id="${user.id}">Изменить</button>
                <button class="secondary-btn" type="button" data-user-action="password" data-user-id="${user.id}">Пароль</button>
                <button class="secondary-btn" type="button" data-user-action="toggle" data-user-id="${user.id}" ${isSelf ? 'disabled' : ''}>${user.is_active ? 'Заблокировать' : 'Разблокировать'}</button>
            </div>
        </article>`;
    }).join('');
}

function renderAdminUsersPager() {
    if (!adminUsersPager) {
        return;
    }
    const totalPages = Math.max(1, Math.ceil(_adminUsersState.total / _adminUsersState.per_page));
    if (totalPages <= 1) {
        adminUsersPager.innerHTML = '';
        return;
    }
    const page = _adminUsersState.page;
    adminUsersPager.innerHTML = `
        <button class="secondary-btn" type="button" id="adminUsersPrevPage" ${page <= 1 ? 'disabled' : ''}>Назад</button>
        <span class="admin-users-pager__info">Стр. ${page} из ${totalPages}</span>
        <button class="secondary-btn" type="button" id="adminUsersNextPage" ${page >= totalPages ? 'disabled' : ''}>Вперёд</button>
    `;
    const prev = document.getElementById('adminUsersPrevPage');
    const next = document.getElementById('adminUsersNextPage');
    if (prev) prev.addEventListener('click', () => loadAdminUsers(page - 1));
    if (next) next.addEventListener('click', () => loadAdminUsers(page + 1));
}

function onAdminUsersListClick(event) {
    const btn = event.target.closest('[data-user-action]');
    if (!btn) {
        return;
    }
    const userId = Number(btn.dataset.userId);
    const action = btn.dataset.userAction;
    const user = _adminUsersCache[userId];
    if (action === 'edit') {
        openUserEditor(user);
    } else if (action === 'password') {
        openUserPasswordModal(user);
    } else if (action === 'toggle') {
        toggleUserActive(user);
    }
}

async function toggleUserActive(user) {
    if (!user) {
        return;
    }
    const nextActive = !user.is_active;
    const verb = nextActive ? 'разблокировать' : 'заблокировать';
    if (!confirm(`Вы действительно хотите ${verb} пользователя «${user.username}»?`)) {
        return;
    }
    try {
        await apiJson(`/api/admin/users/${user.id}`, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({is_active: nextActive}),
        });
        loadAdminUsers();
    } catch (error) {
        showInlineError(error.message);
    }
}

function openUserEditor(user) {
    const modal = document.getElementById('userEditorModal');
    if (!modal) {
        return;
    }
    const isEdit = !!(user && user.id);
    const currentUserId = currentAuth?.user?.id;
    const isSelf = isEdit && user.id === currentUserId;
    document.getElementById('userEditorTitle').textContent = isEdit ? 'Редактирование пользователя' : 'Новый пользователь';
    document.getElementById('userEditorId').value = isEdit ? String(user.id) : '';
    document.getElementById('userEditorUsername').value = isEdit ? (user.username || '') : '';
    document.getElementById('userEditorEmail').value = isEdit ? (user.email || '') : '';
    document.getElementById('userEditorPassword').value = '';
    document.getElementById('userEditorPassword').required = !isEdit;
    document.getElementById('userEditorPasswordLabel').hidden = isEdit;
    document.getElementById('userEditorRole').value = isEdit ? (user.role || 'user') : 'user';
    document.getElementById('userEditorRole').disabled = isSelf;
    document.getElementById('userEditorActive').checked = isEdit ? !!user.is_active : true;
    document.getElementById('userEditorActive').disabled = isSelf;
    document.getElementById('userEditorMessage').textContent = '';
    modal.hidden = false;
    setTimeout(() => document.getElementById('userEditorUsername').focus(), 0);
}

function closeUserEditor() {
    const modal = document.getElementById('userEditorModal');
    if (modal) {
        modal.hidden = true;
    }
}

async function saveUserEditor(event) {
    if (event) {
        event.preventDefault();
    }
    const idValue = document.getElementById('userEditorId').value;
    const id = idValue ? Number(idValue) : null;
    const isEdit = !!id;
    const payload = {
        username: document.getElementById('userEditorUsername').value.trim(),
        email: document.getElementById('userEditorEmail').value.trim(),
        role: document.getElementById('userEditorRole').value,
        is_active: document.getElementById('userEditorActive').checked,
    };
    if (!isEdit) {
        payload.password = document.getElementById('userEditorPassword').value;
    }
    const message = document.getElementById('userEditorMessage');
    message.textContent = 'Сохранение...';
    try {
        if (isEdit) {
            await apiJson(`/api/admin/users/${id}`, {
                method: 'PATCH',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
        } else {
            await apiJson('/api/admin/users', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
        }
        closeUserEditor();
        loadAdminUsers(isEdit ? _adminUsersState.page : 1);
    } catch (error) {
        message.textContent = error.message;
    }
}

function initUserEditorModal() {
    const modal = document.getElementById('userEditorModal');
    if (!modal) {
        return;
    }
    document.getElementById('userEditorForm').addEventListener('submit', saveUserEditor);
    document.getElementById('userEditorCloseBtn').addEventListener('click', closeUserEditor);
    document.getElementById('userEditorBackdrop').addEventListener('click', closeUserEditor);
}

function openUserPasswordModal(user) {
    const modal = document.getElementById('userPasswordModal');
    if (!modal || !user) {
        return;
    }
    document.getElementById('userPasswordUserId').value = String(user.id);
    document.getElementById('userPasswordHint').textContent = `Новый пароль для ${user.username}`;
    document.getElementById('userPasswordNew').value = '';
    document.getElementById('userPasswordMessage').textContent = '';
    modal.hidden = false;
    setTimeout(() => document.getElementById('userPasswordNew').focus(), 0);
}

function closeUserPasswordModal() {
    const modal = document.getElementById('userPasswordModal');
    if (modal) {
        modal.hidden = true;
    }
}

async function saveUserPassword(event) {
    if (event) {
        event.preventDefault();
    }
    const id = Number(document.getElementById('userPasswordUserId').value);
    const message = document.getElementById('userPasswordMessage');
    message.textContent = 'Сохранение...';
    try {
        await apiJson(`/api/admin/users/${id}/password`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({new_password: document.getElementById('userPasswordNew').value}),
        });
        closeUserPasswordModal();
    } catch (error) {
        message.textContent = error.message;
    }
}

function initUserPasswordModal() {
    const modal = document.getElementById('userPasswordModal');
    if (!modal) {
        return;
    }
    document.getElementById('userPasswordForm').addEventListener('submit', saveUserPassword);
    document.getElementById('userPasswordCloseBtn').addEventListener('click', closeUserPasswordModal);
    document.getElementById('userPasswordBackdrop').addEventListener('click', closeUserPasswordModal);
}

function openOwnPasswordModal() {
    const modal = document.getElementById('ownPasswordModal');
    if (!modal) {
        return;
    }
    document.getElementById('ownPasswordForm').reset();
    document.getElementById('ownPasswordMessage').textContent = '';
    modal.hidden = false;
    setTimeout(() => document.getElementById('ownPasswordCurrent').focus(), 0);
}

function closeOwnPasswordModal() {
    const modal = document.getElementById('ownPasswordModal');
    if (modal) {
        modal.hidden = true;
    }
}

async function saveOwnPassword(event) {
    if (event) {
        event.preventDefault();
    }
    const message = document.getElementById('ownPasswordMessage');
    message.textContent = 'Сохранение...';
    try {
        await apiJson('/api/auth/password', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                current_password: document.getElementById('ownPasswordCurrent').value,
                new_password: document.getElementById('ownPasswordNew').value,
            }),
        });
        document.getElementById('ownPasswordForm').reset();
        message.textContent = 'Пароль изменён';
        setTimeout(closeOwnPasswordModal, 1200);
    } catch (error) {
        message.textContent = error.message;
    }
}

function initOwnPasswordModal() {
    const modal = document.getElementById('ownPasswordModal');
    if (!modal) {
        return;
    }
    document.getElementById('ownPasswordForm').addEventListener('submit', saveOwnPassword);
    document.getElementById('ownPasswordCloseBtn').addEventListener('click', closeOwnPasswordModal);
    document.getElementById('ownPasswordBackdrop').addEventListener('click', closeOwnPasswordModal);
    const changePasswordBtn = document.getElementById('changePasswordBtn');
    if (changePasswordBtn) {
        changePasswordBtn.addEventListener('click', openOwnPasswordModal);
    }
}

function initAdminSubtabs() {
    const buttons = document.querySelectorAll('[data-admin-panel]');
    if (!buttons.length) {
        return;
    }
    buttons.forEach((btn) => {
        btn.setAttribute('role', 'tab');
        btn.setAttribute('aria-controls', btn.dataset.adminPanel);
        btn.setAttribute('aria-selected', String(btn.classList.contains('active')));
        btn.tabIndex = btn.classList.contains('active') ? 0 : -1;
        btn.addEventListener('keydown', (event) => {
            const tabs = [...buttons];
            const index = tabs.indexOf(btn);
            let target;
            if (event.key === 'ArrowRight') target = tabs[(index + 1) % tabs.length];
            if (event.key === 'ArrowLeft') target = tabs[(index + tabs.length - 1) % tabs.length];
            if (event.key === 'Home') target = tabs[0];
            if (event.key === 'End') target = tabs[tabs.length - 1];
            if (target) { event.preventDefault(); target.focus(); target.click(); }
        });
        btn.addEventListener('click', () => {
            const panelId = btn.getAttribute('data-admin-panel');
            buttons.forEach((b) => {
                b.classList.toggle('active', b === btn);
                b.setAttribute('aria-selected', String(b === btn));
                b.tabIndex = b === btn ? 0 : -1;
            });
            document.querySelectorAll('.admin-subpanel').forEach((panel) => {
                panel.classList.toggle('active', panel.id === panelId);
            });
            if (panelId === 'adminSettingsPanel' || panelId === 'adminPipelinePanel') {
                loadAdminSettings();
            } else if (panelId === 'adminUsersPanel') {
                loadAdminUsers(1);
            } else if (panelId === 'adminEvalsPanel') {
                loadEvals();
            }
            updateAdminSettingsDraftToolbar();
        });
    });
}

let _adminSettingsCache = null;
let _adminSettingsBaseByKey = {};
let _adminSettingsDraft = {};
let _adminSettingsDirty = new Set();
let _adminSettingsEditorEventsInitialized = false;
let _adminSettingsSaving = false;
let _adminSettingsLoadPromise = null;
let _adminSettingsRequestId = 0;
let _adminSettingsError = '';

async function loadAdminSettings({force = false} = {}) {
    if (!adminSettings) {
        return;
    }
    if (currentAuth.role !== 'admin') {
        adminSettings.innerHTML = '<div class="empty-state">Раздел доступен только администратору</div>';
        _adminSettingsCache = null;
        return;
    }
    if (_adminSettingsLoadPromise) return _adminSettingsLoadPromise;
    if (_adminSettingsCache && !force) {
        renderAdminSettings(_adminSettingsCache, (adminSettingsSearch?.value || '').trim());
        updateAdminSettingsDraftToolbar();
        return true;
    }
    const requestId = ++_adminSettingsRequestId;
    _adminSettingsError = '';
    adminSettings.innerHTML = '<div class="empty-state">Загрузка настроек...</div>';
    _adminModelsCache = null;
    _adminSettingsLoadPromise = (async () => { try {
        const data = await apiJson('/api/admin/settings/schema');
        if (requestId !== _adminSettingsRequestId || currentAuth.role !== 'admin') return false;
        _adminSettingsCache = data;
        _adminSettingsBaseByKey = indexAdminSettingsByKey(data);
        // Refreshing or switching tabs preserves the shared unsaved draft.
        for (const key of [..._adminSettingsDirty]) {
            const item = _adminSettingsBaseByKey[key];
            if (!item || (!item.secret && normalizeValueForCompare(item.type, _adminSettingsDraft[key]) === normalizeValueForCompare(item.type, item.value))) {
                delete _adminSettingsDraft[key];
                _adminSettingsDirty.delete(key);
            }
        }
        renderAdminSettings(data, (adminSettingsSearch?.value || '').trim());
        return true;
    } catch (error) {
        if (requestId !== _adminSettingsRequestId) return false;
        _adminSettingsError = error.message;
        adminSettings.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
        return false;
    } finally {
        _adminSettingsLoadPromise = null;
        updateAdminSettingsDraftToolbar();
    } })();
    updateAdminSettingsDraftToolbar();
    return _adminSettingsLoadPromise;
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
                    <span class="admin-settings-group__title">
                        <span class="admin-settings-group__chev" aria-hidden="true">▾</span>
                        <h3>${escapeHtml(group.title || '')}</h3>
                        <span class="admin-settings-group__count">${items.length} шт.</span>
                    </span>
                    <span class="admin-settings-group__hint">${isCollapsed ? 'Нажмите, чтобы развернуть' : 'Нажмите, чтобы свернуть'}</span>
                </button>
                <div class="admin-settings-group__list">
                    ${items.map(renderAdminSettingItem).join('')}
                </div>
            </section>
        `;
    }).join('');

    void enhanceAdminModelSelects();
}

const ADMIN_MODEL_SETTING_KEYS = ['OLLAMA_EMBEDDING_MODEL', 'OLLAMA_CHAT_MODEL'];
const ADMIN_MODEL_ROLE_BY_KEY = {
    OLLAMA_EMBEDDING_MODEL: 'embedding',
    OLLAMA_CHAT_MODEL: 'chat',
};
let _adminModelsCache = null;
let _adminModelsFetchPromise = null;

function getAdminSettingControlValue(key) {
    const input = adminSettings?.querySelector(`[data-setting-input="${CSS.escape(key)}"]`);
    if (input && 'value' in input) {
        return String(input.value || '');
    }
    if (Object.prototype.hasOwnProperty.call(_adminSettingsDraft, key)) {
        return String(_adminSettingsDraft[key] ?? '');
    }
    return String(_adminSettingsBaseByKey[key]?.value ?? '');
}

function renderAdminModelPickerHtml(key, models, options = {}) {
    const current = options.current !== undefined ? String(options.current || '') : getAdminSettingControlValue(key);
    const loading = !!options.loading;
    const error = options.error || '';
    const ids = Array.isArray(models) ? [...models] : [];
    if (current && !ids.includes(current)) {
        ids.unshift(current);
    }

    let optionsHtml;
    if (loading && !ids.length) {
        optionsHtml = `<option value="">Загрузка моделей…</option>`;
    } else if (!ids.length) {
        optionsHtml = `<option value="${escapeHtml(current)}">${current ? escapeHtml(current) : 'Нет моделей'}</option>`;
    } else {
        optionsHtml = ids.map((id) => {
            const selected = id === current ? ' selected' : '';
            return `<option value="${escapeHtml(id)}"${selected}>${escapeHtml(id)}</option>`;
        }).join('');
    }

    const errorHtml = error
        ? `<div class="setting-model-error">${escapeHtml(error)}</div>`
        : '';

    if (error && !ids.length) {
        return `
            <div class="setting-model-picker" data-setting-model-picker="${escapeHtml(key)}">
                <input class="setting-text" type="text" data-setting-input="${escapeHtml(key)}" value="${escapeHtml(current)}">
                <button type="button" class="setting-model-refresh" data-setting-models-refresh="${escapeHtml(key)}" title="Обновить список моделей">Обновить</button>
            </div>
            ${errorHtml}
        `;
    }

    return `
        <div class="setting-model-picker" data-setting-model-picker="${escapeHtml(key)}">
            <select class="setting-text setting-select" data-setting-input="${escapeHtml(key)}" ${loading ? 'disabled' : ''}>
                ${optionsHtml}
            </select>
            <button type="button" class="setting-model-refresh" data-setting-models-refresh="${escapeHtml(key)}" title="Обновить список моделей" ${loading ? 'disabled' : ''}>Обновить</button>
        </div>
        ${errorHtml}
    `;
}

function normalizeAdminModelsPayload(data) {
    const all = Array.isArray(data?.models) ? data.models : [];
    const chat = Array.isArray(data?.chat_models) ? data.chat_models : all;
    const embedding = Array.isArray(data?.embedding_models) ? data.embedding_models : all;
    return { all, chat, embedding };
}

function adminModelsForRole(modelsByRole, key) {
    if (!modelsByRole) return [];
    const role = ADMIN_MODEL_ROLE_BY_KEY[key];
    if (role && Array.isArray(modelsByRole[role])) {
        return modelsByRole[role];
    }
    return Array.isArray(modelsByRole.all) ? modelsByRole.all : [];
}

function applyAdminModelPickers(modelsByRole, options = {}) {
    if (!adminSettings) return;
    for (const key of ADMIN_MODEL_SETTING_KEYS) {
        const control = adminSettings.querySelector(`[data-setting-row="${CSS.escape(key)}"] .setting-item__control`);
        if (!control) continue;
        const current = getAdminSettingControlValue(key);
        control.innerHTML = renderAdminModelPickerHtml(key, adminModelsForRole(modelsByRole, key), {
            current,
            loading: !!options.loading,
            error: options.error || '',
        });
    }
}

async function enhanceAdminModelSelects(options = {}) {
    if (!adminSettings || currentAuth.role !== 'admin') {
        return;
    }
    const force = !!options.force;
    const hasTargets = ADMIN_MODEL_SETTING_KEYS.some((key) => (
        adminSettings.querySelector(`[data-setting-row="${CSS.escape(key)}"]`)
    ));
    if (!hasTargets) {
        return;
    }

    if (!force && _adminModelsCache) {
        applyAdminModelPickers(_adminModelsCache);
        return;
    }

    applyAdminModelPickers(_adminModelsCache || { all: [], chat: [], embedding: [] }, { loading: true });

    if (!force && _adminModelsFetchPromise) {
        try {
            await _adminModelsFetchPromise;
            if (_adminModelsCache) {
                applyAdminModelPickers(_adminModelsCache);
            }
        } catch (_) {
            /* error UI already applied by the in-flight fetch */
        }
        return;
    }

    _adminModelsFetchPromise = (async () => {
        const data = await apiJson('/api/admin/models');
        _adminModelsCache = normalizeAdminModelsPayload(data);
        return _adminModelsCache;
    })();

    try {
        const models = await _adminModelsFetchPromise;
        applyAdminModelPickers(models);
    } catch (error) {
        _adminModelsCache = null;
        applyAdminModelPickers(null, {
            error: error?.message || 'Не удалось получить список моделей',
        });
    } finally {
        _adminModelsFetchPromise = null;
    }
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
            if (num) {
                num.value = target.value;
                updateAdminSettingsDraftFromInput(key, num);
            }
        } else if (target.matches('input[data-setting-input]')) {
            const key = target.getAttribute('data-setting-input');
            const wrap = adminSettings.querySelector(`[data-setting-slider="${CSS.escape(key)}"]`);
            const range = wrap?.querySelector(`input[data-setting-range="${CSS.escape(key)}"]`);
            if (range && target instanceof HTMLInputElement) range.value = target.value;
        }
    });

    adminSettings.addEventListener('change', (evt) => {
        const target = evt.target;
        if (!(target instanceof HTMLElement)) return;
        if (target.matches('select[data-setting-input]')) {
            const key = target.getAttribute('data-setting-input');
            if (key) {
                updateAdminSettingsDraftFromInput(key, target);
            }
        }
    });

    adminSettings.addEventListener('click', async (evt) => {
        const target = evt.target;
        if (!(target instanceof HTMLElement)) return;

        const refreshBtn = target.closest?.('[data-setting-models-refresh]');
        if (refreshBtn) {
            evt.preventDefault();
            await enhanceAdminModelSelects({ force: true });
            return;
        }

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
    } else if (el instanceof HTMLSelectElement) {
        value = el.value;
    } else if (el instanceof HTMLInputElement) {
        value = el.value;
    } else {
        return;
    }
    setAdminSettingsDraftValue(key, value);
}

function setAdminSettingsDraftValue(key, value) {
    const base = _adminSettingsBaseByKey[key];
    if (!base || _adminSettingsSaving || currentAuth.role !== 'admin') return;
    _adminSettingsError = '';

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
    const draftText = count ? `Изменено: ${count}` : '';
    const settingsVisible = Boolean(
        adminSettingsPanel?.classList.contains('active')
        && document.getElementById('adminPanel')?.classList.contains('active'),
    );

    if (adminSettingsDraftInfo) {
        adminSettingsDraftInfo.textContent = draftText;
    }
    if (adminSettingsFloatInfo) {
        adminSettingsFloatInfo.textContent = draftText;
    }

    [saveAdminSettingsDraftBtn, saveAdminSettingsDraftFloatBtn].forEach((btn) => {
        if (btn) btn.disabled = count === 0 || _adminSettingsSaving;
    });
    [resetAdminSettingsDraftBtn, resetAdminSettingsDraftFloatBtn].forEach((btn) => {
        if (btn) btn.disabled = count === 0 || _adminSettingsSaving;
    });

    const showFloat = settingsVisible && count > 0;
    if (adminSettingsFloat) {
        adminSettingsFloat.hidden = !showFloat;
        adminSettingsFloat.classList.toggle('is-visible', showFloat);
    }
    if (adminSettingsPanel) {
        adminSettingsPanel.classList.toggle('has-floating-draft', showFloat);
    }
    if (adminSettings) adminSettings.inert = _adminSettingsSaving;
    window.AdminPipelineUI?.update({
        ready: Boolean(_adminSettingsCache),
        isAdmin: currentAuth.role === 'admin',
        visible: document.getElementById('adminPipelinePanel')?.classList.contains('active') && document.getElementById('adminPanel')?.classList.contains('active'),
        items: _adminSettingsBaseByKey,
        draft: _adminSettingsDraft,
        dirtyCount: count,
        saving: _adminSettingsSaving,
        loading: Boolean(_adminSettingsLoadPromise),
        error: _adminSettingsError,
    });
}

function setAdminSettingsDraftStatus(text) {
    if (adminSettingsDraftInfo) {
        adminSettingsDraftInfo.textContent = text;
    }
    if (adminSettingsFloatInfo) {
        adminSettingsFloatInfo.textContent = text;
    }
    window.AdminPipelineUI?.setStatus(text);
}

function setAdminSettingsSaveButtonsText(text) {
    [saveAdminSettingsDraftBtn, saveAdminSettingsDraftFloatBtn].forEach((btn) => {
        if (btn) btn.textContent = text;
    });
}

function setAdminSettingsSaveButtonsDisabled(disabled) {
    [saveAdminSettingsDraftBtn, saveAdminSettingsDraftFloatBtn].forEach((btn) => {
        if (btn) btn.disabled = disabled;
    });
}

async function resetAdminSettingsDraft() {
    if (_adminSettingsSaving) return;
    _adminSettingsError = '';
    _adminSettingsDraft = {};
    _adminSettingsDirty = new Set();
    if (_adminSettingsCache) {
        renderAdminSettings(_adminSettingsCache, (adminSettingsSearch?.value || '').trim());
    }
    updateAdminSettingsDraftToolbar();
}

async function saveAdminSettingsDraft() {
    const keys = Array.from(_adminSettingsDirty);
    if (!keys.length || _adminSettingsSaving || currentAuth.role !== 'admin') return;
    const pending = keys.map((key) => [key, _adminSettingsDraft[key]]);
    const adminId = currentAuth.user?.id;
    _adminSettingsSaving = true;
    _adminSettingsError = '';
    updateAdminSettingsDraftToolbar();
    setAdminSettingsSaveButtonsDisabled(true);
    setAdminSettingsSaveButtonsText('Сохранение...');
    let i = 0;
    try {
        for (const [key, value] of pending) {
            if (currentAuth.role !== 'admin' || currentAuth.user?.id !== adminId) throw new Error('Сессия администратора изменилась. Обновите настройки.');
            setAdminSettingsDraftStatus(`Сохранение ${i + 1}/${keys.length}...`);
            await apiJson('/api/admin/settings', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({key, value, action: 'set'}),
            });
            i += 1;
            delete _adminSettingsDraft[key];
            _adminSettingsDirty.delete(key);
            if (_adminSettingsBaseByKey[key]) _adminSettingsBaseByKey[key].value = _adminSettingsBaseByKey[key].secret ? '' : value;
        }
        const refreshed = await loadAdminSettings({force: true});
        await syncRagToolbarDefaults();
        setAdminSettingsDraftStatus(refreshed ? 'Сохранено' : 'Настройки сохранены. Не удалось обновить список; нажмите «Обновить».');
        setTimeout(() => {
            if (!_adminSettingsSaving && !_adminSettingsError) setAdminSettingsDraftStatus('');
        }, 2000);
    } catch (error) {
        _adminSettingsError = `${i ? `Сохранено ${i} из ${keys.length}. ` : ''}${error.message}`;
        setAdminSettingsDraftStatus(_adminSettingsError);
        if (i) await syncRagToolbarDefaults();
    } finally {
        _adminSettingsSaving = false;
        setAdminSettingsSaveButtonsText('Сохранить всё');
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
        await loadAdminSettings({force: true});
    } catch (error) {
        if (status) status.textContent = error.message;
    }
}

async function clearAdminSetting(key) {
    if (_adminSettingsSaving) return;
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
        await loadAdminSettings({force: true});
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
    const messages = [...messagesContainer.querySelectorAll('.message')]
    .filter((node) => (
        !node.classList.contains('system-message') &&
        !node.classList.contains('welcome-message') &&
        node.id !== 'typingIndicator'
    ))
    .map((node) => {
        const role = node.classList.contains('user-message') ? 'Вы' : 'Ассистент';
        const content = node.querySelector('.message-content')?.cloneNode(true);
        if (!content) {
            return '';
        }
        content.querySelectorAll([
            '.show-sources-btn',
            '.verify-answer-btn',
            '.report-issue-btn',
            '.feedback-controls',
            '.followup-suggestions',
            '.related-documents',
            '.verification-result',
            '.copy-button',
        ].join(',')).forEach((el) => el.remove());
        const text = content.innerText || '';
        return `## ${role}\n\n${text.trim()}`;
    }).filter(Boolean).join('\n\n');
    const blob = new Blob([messages], {type: 'text/markdown;charset=utf-8'});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `chat-${currentChatId || 'draft'}.md`;
    link.click();
    URL.revokeObjectURL(link.href);
}

function showInlineError(message) {
    addMessage(message, 'bot', {system: true});
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

const evalStartBtn = document.getElementById('evalStartBtn');
const evalImportBtn = document.getElementById('evalImportBtn');
const evalImportFile = document.getElementById('evalImportFile');
const evalCompareBtn = document.getElementById('evalCompareBtn');
const evalCaseForm = document.getElementById('evalCaseForm');
const evalAddBtn = document.getElementById('evalAddBtn');
const evalCancelEditBtn = document.getElementById('evalCancelEditBtn');
let evalEditingId = null;
let evalSelected = [];
let evalPollTimer = null;

function evalSplitList(value) {
    return String(value || '').split(/[\n,]/).map((part) => part.trim()).filter(Boolean);
}

function evalEl(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
}

async function loadEvals() {
    if (!document.getElementById('adminEvalsPanel') || currentAuth.role !== 'admin') return;
    const [casesRes, runsRes] = await Promise.all([
        apiJson('/api/admin/evals/cases'),
        apiJson('/api/admin/evals/runs'),
    ]);
    renderEvalCases(casesRes.cases || []);
    renderEvalRuns(runsRes.runs || []);
    const running = (runsRes.runs || []).find((run) => run.status === 'queued' || run.status === 'running');
    const status = document.getElementById('evalRunStatus');
    if (running) {
        if (status) status.textContent = `Идёт прогон: ${running.progress_done}/${running.progress_total}`;
        if (!evalPollTimer) {
            evalPollTimer = setInterval(() => {
                loadEvals().catch(() => {});
            }, 2000);
        }
    } else if (evalPollTimer) {
        clearInterval(evalPollTimer);
        evalPollTimer = null;
        if (status) status.textContent = 'Прогон завершён';
    }
}

function renderEvalCases(cases) {
    const root = document.getElementById('evalCases');
    if (!root) return;
    root.replaceChildren();
    const active = cases.filter((item) => item.active).length;
    if (evalStartBtn) evalStartBtn.disabled = active === 0;
    cases.forEach((item) => {
        const row = evalEl('article', `eval-case${item.active ? '' : ' is-off'}`);
        const title = evalEl('div', 'eval-case__title', item.question);
        const meta = evalEl('div', 'eval-case__meta', `${item.external_id} · ${item.label === 'unanswerable' ? 'ответа нет' : 'ответ есть'}${item.active ? '' : ' · выключен'}${item.expected_sources && item.expected_sources.length ? '' : ' · без эталона'}`);
        const edit = evalEl('button', 'secondary-btn', 'Изменить');
        edit.type = 'button';
        edit.addEventListener('click', () => openEvalCaseModal(item));
        row.append(title, meta, edit);
        root.append(row);
    });
    if (!cases.length) {
        root.append(evalEl('p', 'eval-empty', 'Вопросов пока нет'));
    }
}

function fillEvalForm(item) {
    evalEditingId = item.id;
    document.getElementById('evalQuestion').value = item.question || '';
    document.getElementById('evalLabel').value = item.label || 'answerable';
    document.getElementById('evalExpected').value = (item.expected_sources || []).join(', ');
    document.getElementById('evalEvidence').value = item.evidence_contains || '';
    document.getElementById('evalMustAny').value = (item.must_contain_any || []).join(', ');
    document.getElementById('evalMustNot').value = (item.must_not_contain || []).join(', ');
    document.getElementById('evalNotes').value = item.notes || '';
    document.getElementById('evalActive').checked = !!item.active;
    const save = document.getElementById('evalSaveBtn');
    if (save) save.textContent = 'Сохранить';
    const title = document.getElementById('evalCaseTitle');
    if (title) title.textContent = 'Изменить вопрос';
}

function resetEvalForm() {
    evalEditingId = null;
    if (evalCaseForm) evalCaseForm.reset();
    const active = document.getElementById('evalActive');
    if (active) active.checked = true;
    const save = document.getElementById('evalSaveBtn');
    if (save) save.textContent = 'Добавить';
    const title = document.getElementById('evalCaseTitle');
    if (title) title.textContent = 'Новый вопрос';
    const message = document.getElementById('evalCaseMessage');
    if (message) message.textContent = '';
}

function openEvalCaseModal(item) {
    const modal = document.getElementById('evalCaseModal');
    if (!modal) return;
    if (item) fillEvalForm(item);
    else resetEvalForm();
    const message = document.getElementById('evalCaseMessage');
    if (message) message.textContent = '';
    modal.hidden = false;
    setTimeout(() => document.getElementById('evalQuestion')?.focus(), 0);
}

function closeEvalCaseModal() {
    const modal = document.getElementById('evalCaseModal');
    if (modal) modal.hidden = true;
    resetEvalForm();
}

function renderEvalRuns(runs) {
    const root = document.getElementById('evalRuns');
    if (!root) return;
    root.replaceChildren();
    if (!runs.length) {
        root.append(evalEl('p', 'eval-empty', 'Прогонов ещё нет'));
        return;
    }
    runs.forEach((run) => {
        const row = evalEl('article', 'eval-run');
        const check = document.createElement('input');
        check.type = 'checkbox';
        check.checked = evalSelected.includes(run.id);
        check.addEventListener('change', () => toggleEvalSelect(run.id, check.checked));
        const body = evalEl('button', 'eval-run__open');
        body.type = 'button';
        const params = run.params || {};
        const headline = run.headline || {};
        body.append(
            evalEl('strong', '', `${run.started_at || ''} · ${run.status}`),
            evalEl('span', '', `${params.OLLAMA_CHAT_MODEL || 'модель'} · чанк ${params.CHUNK_SIZE ?? '—'}`),
            evalEl('span', '', `Ответ ${headline.answer || '—'} · Поиск ${headline.search || '—'}${headline.progress && run.status !== 'done' ? ` · ${headline.progress}` : ''}`),
        );
        body.addEventListener('click', () => openEvalRun(run.id));
        row.append(check, body);
        root.append(row);
    });
    if (evalCompareBtn) evalCompareBtn.disabled = evalSelected.length !== 2;
}

function toggleEvalSelect(id, checked) {
    evalSelected = evalSelected.filter((item) => item !== id);
    if (checked) evalSelected.push(id);
    if (evalSelected.length > 2) evalSelected = evalSelected.slice(-2);
    if (evalCompareBtn) evalCompareBtn.disabled = evalSelected.length !== 2;
    loadEvals();
}

const EVAL_STATUS_LABEL = {
    done: 'готово',
    running: 'идёт',
    queued: 'в очереди',
    failed: 'ошибка',
};

function evalClock(value) {
    const date = value ? new Date(value) : null;
    if (!date || Number.isNaN(date.getTime())) return '';
    return date.toLocaleString('ru-RU', {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
}

function evalWhen(run) {
    const start = run.started_at ? new Date(run.started_at) : null;
    const end = run.finished_at ? new Date(run.finished_at) : null;
    const startLabel = evalClock(run.started_at);
    if (!start || Number.isNaN(start.getTime())) return run.started_at || '';
    let range = startLabel;
    if (end && !Number.isNaN(end.getTime())) {
        range = `${startLabel}–${end.toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'})}`;
    }
    const minutes = end && !Number.isNaN(end.getTime())
        ? Math.max(1, Math.round((end.getTime() - start.getTime()) / 60000))
        : 0;
    return minutes ? `${range} · ${minutes} мин` : range;
}

function evalNeedsAttention(item) {
    return item.search_verdict === 'search_miss'
        || item.answer_verdict === 'abstained_despite_hit'
        || item.answer_verdict === 'unclear'
        || item.answer_verdict === 'refusal'
        || item.answer_verdict === 'false_answer'
        || item.answer_verdict === 'facts_mismatch'
        || item.answer_verdict === 'infra_error';
}

function evalSwatch(item) {
    if (item.search_verdict === 'search_miss' || item.answer_verdict === 'abstained_despite_hit' || item.answer_verdict === 'false_answer' || item.answer_verdict === 'facts_mismatch' || item.answer_verdict === 'infra_error') return 'bad';
    if (item.answer_verdict === 'unclear' || item.answer_verdict === 'refusal') return 'warn';
    if (item.search_verdict === 'unlabeled' || item.search_verdict === 'search_neighbors' || item.search_verdict === 'search_empty') return 'muted';
    return 'ok';
}

function evalSearchTone(verdict) {
    if (verdict === 'search_hit') return 'ok';
    if (verdict === 'search_miss' || verdict === 'infra_error') return 'bad';
    if (verdict === 'search_neighbors' || verdict === 'search_empty') return 'warn';
    return 'muted';
}

function evalAnswerTone(verdict) {
    if (verdict === 'substantive' || verdict === 'correct_abstain') return 'ok';
    if (verdict === 'unclear' || verdict === 'refusal') return 'warn';
    if (verdict === 'abstained_despite_hit' || verdict === 'false_answer' || verdict === 'facts_mismatch' || verdict === 'infra_error') return 'bad';
    return 'muted';
}

function evalFact(label, value) {
    const node = evalEl('div', 'eval-fact');
    node.append(evalEl('span', 'eval-fact__label', label), evalEl('span', 'eval-fact__value', value));
    return node;
}

function evalStat(value, label, tone) {
    const node = evalEl('div', 'eval-stat');
    const number = evalEl('strong', tone ? `is-${tone}` : '', String(value));
    node.append(number, evalEl('span', '', label));
    return node;
}

function evalBar(label, caption, segments, total) {
    const wrap = evalEl('div', 'eval-bar');
    const head = evalEl('div', 'eval-bar__head');
    head.append(evalEl('span', '', label), evalEl('span', '', caption));
    const track = evalEl('div', 'eval-bar__track');
    let used = 0;
    segments.forEach((segment) => {
        const value = Number(segment.value) || 0;
        if (value <= 0) return;
        used += value;
        const part = evalEl('span', `eval-bar__seg is-${segment.tone}`);
        part.style.flexGrow = String(value);
        part.title = segment.title || '';
        track.append(part);
    });
    const rest = Math.max(0, total - used);
    if (rest > 0) {
        const part = evalEl('span', 'eval-bar__seg is-rest');
        part.style.flexGrow = String(rest);
        track.append(part);
    }
    if (!track.childElementCount) return null;
    wrap.append(head, track);
    return wrap;
}

function evalScore(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(2) : '';
}

function renderEvalItems(host, items, filter) {
    host.replaceChildren();
    const matched = items.filter((item) => {
        if (filter === 'attention') return evalNeedsAttention(item);
        if (filter === 'miss') return item.search_verdict === 'search_miss';
        if (filter === 'abstain') return item.answer_verdict === 'abstained_despite_hit';
        return true;
    });
    const ordered = matched
        .map((item, index) => ({item, index}))
        .sort((left, right) => Number(evalNeedsAttention(right.item)) - Number(evalNeedsAttention(left.item)) || left.index - right.index);
    ordered.forEach(({item}, position) => {
        const details = document.createElement('details');
        details.className = 'eval-item';
        if (position === 0 && evalNeedsAttention(item)) details.open = true;
        const summaryNode = document.createElement('summary');
        const swatch = evalEl('span', `eval-swatch is-${evalSwatch(item)}`);
        swatch.setAttribute('aria-hidden', 'true');
        const question = evalEl('span', 'eval-item__question', item.question);
        const tags = evalEl('span', 'eval-item__tags');
        tags.append(
            evalEl('span', `is-${evalSearchTone(item.search_verdict)}`, item.search_label || ''),
            evalEl('span', `is-${evalAnswerTone(item.answer_verdict)}`, item.answer_label || ''),
        );
        summaryNode.append(swatch, question, tags);
        details.append(summaryNode);
        const body = evalEl('div', 'eval-item__body');
        const detail = item.detail || {};
        const source = detail.matched_source || (item.sources && item.sources[0]) || null;
        if (source) {
            const score = evalScore(source.score);
            const bits = [
                source.title || source.path || '',
                item.rank ? `место ${item.rank}` : '',
                score,
            ].filter(Boolean);
            body.append(evalEl('p', 'eval-item__source', `Источник: ${bits.join(' · ')}`));
        }
        if (detail.evidence_hit === true || detail.evidence_hit === false) {
            body.append(evalEl('p', 'eval-item__meta', `Эталонная фраза: ${detail.evidence_hit ? 'найдена' : 'нет в выдаче'}`));
        }
        body.append(evalEl('p', 'eval-item__answer-label', 'Ответ'));
        body.append(evalEl('pre', 'eval-answer', item.answer_excerpt || ''));
        details.append(body);
        host.append(details);
    });
}

async function openEvalRun(id) {
    const data = await apiJson(`/api/admin/evals/runs/${id}`);
    const run = data.run;
    const root = document.getElementById('evalRunDetail');
    const compare = document.getElementById('evalCompare');
    if (compare) compare.hidden = true;
    root.hidden = false;
    root.replaceChildren();
    const params = run.params || {};
    const index = run.index || {};
    const summary = run.summary || {};
    const answer = summary.answer || {};
    const search = summary.search || {};
    const items = run.items || [];
    const evaluated = summary.evaluated || items.length || 0;
    const labeled = search.labeled || 0;
    const hit1 = search.hit_at_1 || 0;
    const hitk = search.hit_at_k || 0;
    const unlabeled = search.unlabeled || 0;
    const misses = Math.max(0, labeled - hitk);
    const substantive = answer.substantive || 0;
    const unclear = answer.unclear || 0;
    const abstain = answer.abstained_despite_hit || 0;
    const attentionCount = items.filter(evalNeedsAttention).length;
    const missCount = items.filter((item) => item.search_verdict === 'search_miss').length;

    const detail = evalEl('article', 'eval-detail');
    const title = evalEl('div', 'eval-detail__title');
    title.append(evalEl('h3', '', `Прогон ${run.id}`));
    const status = evalEl('span', `eval-pill${run.status === 'done' ? ' is-on' : ''}${run.status === 'failed' ? ' is-bad' : ''}`, EVAL_STATUS_LABEL[run.status] || run.status || '');
    title.append(status);
    detail.append(title);
    const when = evalWhen(run);
    if (when) detail.append(evalEl('p', 'eval-detail__when', when));

    const facts = evalEl('div', 'eval-facts');
    const factRows = [
        ['Модель', params.OLLAMA_CHAT_MODEL],
        ['Эмбеддинг', params.OLLAMA_EMBEDDING_MODEL],
        ['Чанк', params.CHUNK_SIZE != null ? String(params.CHUNK_SIZE) : ''],
        ['Top-k', params.RAG_TOP_K != null ? String(params.RAG_TOP_K) : ''],
        ['Индекс', index.chunk_count != null ? `${index.chunk_count} чанков` : ''],
        ['Поиск', params.RETRIEVAL_MODE],
    ];
    factRows.forEach(([label, value]) => {
        if (value) facts.append(evalFact(label, value));
    });
    if (facts.childElementCount) detail.append(facts);

    const modes = [];
    if (params.RAG_MULTI_QUERY_ENABLED) modes.push('multi-query');
    if (params.RAG_HYDE_ENABLED) modes.push('HyDE');
    if (params.DEEP_RETRIEVAL_ENABLED) modes.push('deep retrieval');
    if (modes.length) {
        const modeRow = evalEl('div', 'eval-modes');
        modes.forEach((name) => modeRow.append(evalEl('span', 'eval-pill', name)));
        detail.append(modeRow);
    }
    if (params.nondeterministic && modes.length) {
        detail.append(evalEl('p', 'eval-warn', `Включены ${modes.join(' и ')}. Повтор прогона может дать другой набор чанков.`));
    }
    if (run.error) detail.append(evalEl('p', 'eval-warn', run.error));

    const stats = evalEl('div', 'eval-stats');
    if (labeled) {
        stats.append(
            evalStat(`${hitk}/${labeled}`, 'Поиск, hit@k'),
            evalStat(`${hit1}/${labeled}`, 'Поиск, hit@1'),
            evalStat(`${substantive}/${evaluated}`, 'Содержательный ответ', 'ok'),
            evalStat(abstain, 'Отказ при документе', abstain ? 'bad' : ''),
        );
    } else {
        stats.append(
            evalStat(`${substantive}/${evaluated}`, 'Содержательный ответ', 'ok'),
            evalStat(unclear, 'Неясно', unclear ? 'warn' : ''),
            evalStat(unlabeled, 'Без эталона, поиск не оценён'),
        );
    }
    detail.append(stats);

    const answerBar = evalBar(
        'Ответы',
        `${substantive} содержательных из ${evaluated}`,
        [
            {value: substantive, tone: 'ok', title: 'содержательный'},
            {value: answer.correct_abstain || 0, tone: 'ok', title: 'отказался правильно'},
            {value: answer.refusal || 0, tone: 'warn', title: 'отказ'},
            {value: abstain, tone: 'bad', title: 'отказ при документе'},
            {value: unclear, tone: 'warn', title: 'неясно'},
            {value: answer.facts_mismatch || 0, tone: 'bad', title: 'факты не сошлись'},
            {value: answer.false_answer || 0, tone: 'bad', title: 'ответил, хотя ответа нет'},
            {value: answer.infra_error || 0, tone: 'bad', title: 'ошибка'},
        ],
        evaluated,
    );
    if (answerBar) detail.append(answerBar);
    if (labeled) {
        const searchBar = evalBar(
            'Поиск',
            `hit@1 ${hit1} · hit@k ${hitk} · мимо ${misses} · без эталона ${unlabeled}`,
            [
                {value: hit1, tone: 'ok', title: 'hit@1'},
                {value: Math.max(0, hitk - hit1), tone: 'info', title: 'hit@k, не первое место'},
                {value: misses, tone: 'bad', title: 'не найден'},
                {value: unlabeled, tone: 'muted', title: 'без эталона'},
            ],
            evaluated || labeled + unlabeled,
        );
        if (searchBar) detail.append(searchBar);
    } else if (unlabeled) {
        detail.append(evalEl('p', 'eval-detail__note', 'Hit@1 и hit@k скрыты: ни у одного вопроса нет ожидаемого документа, поэтому «нашёл / не нашёл» посчитать нельзя.'));
    }

    const pin = evalEl('div', 'eval-detail__pin');
    const filtersHost = evalEl('div', 'eval-filters');
    const itemsHost = evalEl('div', 'eval-detail__items');
    const filters = [{id: 'all', label: `Все ${items.length}`}];
    if (attentionCount) filters.push({id: 'attention', label: `Проблемы ${attentionCount}`});
    if (missCount) filters.push({id: 'miss', label: `Поиск мимо ${missCount}`});
    if (abstain) filters.push({id: 'abstain', label: `Отказ при документе ${items.filter((item) => item.answer_verdict === 'abstained_despite_hit').length}`});

    function paint(filter) {
        filtersHost.replaceChildren();
        filters.forEach((entry) => {
            const button = evalEl('button', `eval-filter${entry.id === filter ? ' is-on' : ''}`, entry.label);
            button.type = 'button';
            button.setAttribute('aria-pressed', entry.id === filter ? 'true' : 'false');
            button.addEventListener('click', () => paint(entry.id));
            filtersHost.append(button);
        });
        renderEvalItems(itemsHost, items, filter);
    }

    pin.append(filtersHost);
    detail.append(pin, itemsHost);
    paint('all');
    root.append(detail);
    root.scrollIntoView({block: 'nearest'});
}

async function startEvalRun() {
    const status = document.getElementById('evalRunStatus');
    status.dataset.hold = '';
    try {
        await apiJson('/api/admin/evals/runs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
        status.textContent = 'Прогон запущен';
        delete status.dataset.hold;
        await loadEvals();
    } catch (error) {
        status.textContent = error.message || 'Не удалось запустить';
        delete status.dataset.hold;
    }
}

if (evalStartBtn) evalStartBtn.addEventListener('click', startEvalRun);
if (evalImportBtn && evalImportFile) {
    evalImportBtn.addEventListener('click', () => evalImportFile.click());
    evalImportFile.addEventListener('change', async () => {
        const file = evalImportFile.files && evalImportFile.files[0];
        evalImportFile.value = '';
        if (!file) return;
        const jsonl = await file.text();
        const status = document.getElementById('evalRunStatus');
        try {
            const result = await apiJson('/api/admin/evals/cases/import', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({jsonl}),
            });
            status.textContent = `Импорт: новых ${result.created}, обновлено ${result.updated}`;
            await loadEvals();
        } catch (error) {
            status.textContent = error.message || 'Импорт не удался';
        }
    });
}
if (evalCaseForm) {
    evalCaseForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const payload = {
            question: document.getElementById('evalQuestion').value,
            label: document.getElementById('evalLabel').value,
            expected_sources: evalSplitList(document.getElementById('evalExpected').value),
            evidence_contains: document.getElementById('evalEvidence').value,
            must_contain_any: evalSplitList(document.getElementById('evalMustAny').value),
            must_not_contain: evalSplitList(document.getElementById('evalMustNot').value),
            notes: document.getElementById('evalNotes').value,
            active: document.getElementById('evalActive').checked,
        };
        const status = document.getElementById('evalRunStatus');
        const message = document.getElementById('evalCaseMessage');
        if (message) message.textContent = 'Сохранение...';
        try {
            if (evalEditingId) {
                await apiJson(`/api/admin/evals/cases/${evalEditingId}`, {
                    method: 'PATCH',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload),
                });
            } else {
                await apiJson('/api/admin/evals/cases', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload),
                });
            }
            closeEvalCaseModal();
            if (status) status.textContent = 'Вопрос сохранён';
            await loadEvals();
        } catch (error) {
            if (message) message.textContent = error.message || 'Не удалось сохранить';
        }
    });
}
if (evalAddBtn) evalAddBtn.addEventListener('click', () => openEvalCaseModal(null));
if (evalCancelEditBtn) evalCancelEditBtn.addEventListener('click', closeEvalCaseModal);
const evalCaseCloseBtn = document.getElementById('evalCaseCloseBtn');
const evalCaseBackdrop = document.getElementById('evalCaseBackdrop');
if (evalCaseCloseBtn) evalCaseCloseBtn.addEventListener('click', closeEvalCaseModal);
if (evalCaseBackdrop) evalCaseBackdrop.addEventListener('click', closeEvalCaseModal);
document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    const modal = document.getElementById('evalCaseModal');
    if (modal && !modal.hidden) closeEvalCaseModal();
});
if (evalCompareBtn) {
    evalCompareBtn.addEventListener('click', async () => {
        if (evalSelected.length !== 2) return;
        const [a, b] = [...evalSelected].sort((left, right) => left - right);
        const report = await apiJson(`/api/admin/evals/compare?before=${a}&after=${b}`);
        const root = document.getElementById('evalCompare');
        const detail = document.getElementById('evalRunDetail');
        if (detail) detail.hidden = true;
        root.hidden = false;
        root.replaceChildren();
        root.append(evalEl('h3', '', 'Сравнение'));
        const line = evalEl('p', '');
        line.textContent = `Содержательный ответ ${report.substantive.before} → ${report.substantive.after}`;
        root.append(line);
        const before = report.before || {};
        const after = report.after || {};
        root.append(evalEl('p', '', `Было: ${before.model || ''} · чанк ${before.chunk_size ?? '—'} · ${before.started_at || ''}`));
        root.append(evalEl('p', '', `Стало: ${after.model || ''} · чанк ${after.chunk_size ?? '—'} · ${after.started_at || ''}`));
        const warnings = {
            dataset_changed: 'Между прогонами менялась корзина вопросов.',
            index_unchanged: 'Размер чанка или эмбеддинги изменились, а отпечаток индекса совпал. Корпус, похоже, не пересобирали.',
            delta_within_one: 'Сдвиг не больше одного вопроса.',
        };
        (report.warnings || []).forEach((code) => {
            if (warnings[code]) root.append(evalEl('p', 'eval-warn', warnings[code]));
        });
        if (!(report.changed || []).length) {
            root.append(evalEl('p', '', 'Вердикты вопросов не изменились.'));
            return;
        }
        (report.changed || []).forEach((item) => {
            const row = evalEl('article', 'eval-change');
            row.append(evalEl('strong', '', item.question));
            row.append(evalEl('p', '', `Поиск: ${item.search_before} → ${item.search_after}`));
            row.append(evalEl('p', '', `Ответ: ${item.answer_before} → ${item.answer_after}`));
            root.append(row);
        });
    });
}
