let currentSources = [];
let currentCitations = [];
let currentChatId = null;
let isProcessing = false;
const SOURCE_REFERENCE_PATTERN = /\[Источник:\s*([^\]]+)\]/g;

const messagesContainer = document.getElementById('messages');
const messageForm = document.getElementById('messageForm');
const messageInput = document.getElementById('messageInput');
const sendButton = document.getElementById('sendButton');
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const sourcesPanel = document.getElementById('sourcesPanel');
const sourcesList = document.getElementById('sourcesList');
const closeSources = document.getElementById('closeSources');
const newChatBtn = document.getElementById('newChatBtn');
const sidebarNewChatBtn = document.getElementById('sidebarNewChatBtn');
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
const reindexBtn = document.getElementById('reindexBtn');
const jobStatus = document.getElementById('jobStatus');
const refreshAdminBtn = document.getElementById('refreshAdminBtn');
const adminOverview = document.getElementById('adminOverview');

document.addEventListener('DOMContentLoaded', () => {
    checkHealth();
    loadChats();
    setInterval(checkHealth, 30000);

    messageForm.addEventListener('submit', handleSubmit);
    closeSources.addEventListener('click', closeSourcesPanel);
    newChatBtn.addEventListener('click', startNewChat);
    sidebarNewChatBtn.addEventListener('click', startNewChat);
    clearChatsBtn.addEventListener('click', clearAllChats);
    chatSearchInput.addEventListener('input', debounce(() => loadChats(chatSearchInput.value.trim()), 250));
    exportChatBtn.addEventListener('click', exportCurrentChat);
    refreshDocumentsBtn.addEventListener('click', loadDocuments);
    reindexBtn.addEventListener('click', startReindex);
    uploadForm.addEventListener('submit', uploadDocument);
    refreshAdminBtn.addEventListener('click', loadAdminOverview);
    document.querySelectorAll('.tab-btn').forEach((btn) => {
        btn.addEventListener('click', () => switchPanel(btn.dataset.panel));
    });

    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            messageForm.dispatchEvent(new Event('submit'));
        }
    });

    messageInput.focus();
});

async function apiJson(url, options = {}) {
    const response = await fetch(url, options);
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

function debounce(fn, delay) {
    let timer = null;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
    };
}

function switchPanel(panelId) {
    document.querySelectorAll('.tab-btn').forEach((btn) => {
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
                addFeedbackControls(messageEl, msg.id);
            }
        });
        loadChats(chatSearchInput.value.trim());
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
        top_k: Number(topKInput.value || 5),
        min_score: Number(minScoreInput.value || 0),
    };
}

async function readStream(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let streamShell = null;
    let streamContent = null;
    let accumulated = '';

    const ensureStreamShell = () => {
        if (streamShell) {
            return;
        }
        streamShell = document.createElement('div');
        streamShell.className = 'message bot-message';
        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.textContent = '🤖';
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
                streamContent.textContent = accumulated;
                scrollToBottom();
            } else if (payload.type === 'status') {
                if (!accumulated) {
                    ensureStreamShell();
                    streamContent.innerHTML = `<div class="thinking-status">${escapeHtml(payload.message || 'Готовлю ответ')}<span class="thinking-dots">...</span></div>`;
                    scrollToBottom();
                }
            } else if (payload.type === 'done') {
                const finalText = payload.answer != null ? payload.answer : accumulated;
                currentChatId = payload.chat_id || currentChatId;
                ensureStreamShell();
                streamContent.innerHTML = formatMessage(finalText);
                streamContent.classList.remove('streaming-in-progress');
                linkifySourceReferences(streamShell, payload.sources || [], payload.citations || []);
                addSourcesButton(streamShell, payload.sources || [], payload.citations || []);
                addFeedbackControls(streamShell, payload.message_id);
            } else if (payload.type === 'error') {
                ensureStreamShell();
                streamContent.textContent = payload.message || 'Ошибка потока';
                streamContent.classList.remove('streaming-in-progress');
            }
        });
    };

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
                await new Promise((resolve) => requestAnimationFrame(resolve));
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

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = type === 'user' ? '👤' : '🤖';

    const content = document.createElement('div');
    content.className = 'message-content';
    if (type === 'bot') {
        content.innerHTML = formatMessage(text);
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
        <div class="message-avatar">🤖</div>
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
    button.textContent = `📚 Источники (${Math.max(sources.length, citations.length)})`;
    button.addEventListener('click', () => {
        currentSources = sources;
        currentCitations = citations;
        openSourcesPanel();
    });
    content.appendChild(button);
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
        const sourceItem = document.createElement('div');
        sourceItem.className = 'source-item';
        if (i === focusIndex) {
            sourceItem.classList.add('source-item--active');
        }
        if (source.path && source.path !== 'N/A') {
            sourceItem.tabIndex = 0;
            sourceItem.setAttribute('role', 'button');
            sourceItem.title = 'Открыть документ';
            sourceItem.addEventListener('click', () => openDocumentFromSource(source));
            sourceItem.addEventListener('keydown', (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    openDocumentFromSource(source);
                }
            });
        }
        sourceItem.innerHTML = `
            <div class="source-title">${escapeHtml(source.title || citation.source || 'Без названия')}</div>
            <div class="source-path">${escapeHtml(source.path || source.source || citation.chunk_id || 'N/A')}</div>
            <div class="source-relevance">Релевантность: ${escapeHtml(String(source.relevance || citation.score || 'n/a'))}</div>
            <p class="source-snippet">${escapeHtml(citation.text || source.text || '')}</p>
        `;
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

function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

async function loadDocuments() {
    documentsList.innerHTML = '<div class="empty-state">Загрузка...</div>';
    try {
        const data = await apiJson('/api/documents');
        const docs = data.documents || [];
        if (!docs.length) {
            documentsList.innerHTML = '<div class="empty-state">Документы не найдены</div>';
            return;
        }
        documentsList.innerHTML = docs.map((doc) => `
            <div class="data-card">
                <strong>${escapeHtml(doc.filename)}</strong>
                <span>${escapeHtml(doc.path)}</span>
                <small>${escapeHtml(doc.file_type || '')} · ${formatBytes(doc.size_bytes)} · ${formatDate(doc.modified_at)}</small>
            </div>
        `).join('');
    } catch (error) {
        documentsList.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    }
}

async function uploadDocument(e) {
    e.preventDefault();
    if (!documentFileInput.files.length) {
        jobStatus.textContent = 'Выберите файл';
        return;
    }
    const formData = new FormData();
    formData.append('file', documentFileInput.files[0]);
    try {
        await apiJson('/api/documents/upload', {method: 'POST', body: formData});
        jobStatus.textContent = 'Файл загружен';
        documentFileInput.value = '';
        loadDocuments();
    } catch (error) {
        jobStatus.textContent = error.message;
    }
}

async function startReindex() {
    try {
        const data = await apiJson('/api/documents/reindex', {method: 'POST'});
        jobStatus.textContent = `${data.job.status}: ${data.job.message}`;
        pollJobs();
    } catch (error) {
        jobStatus.textContent = error.message;
    }
}

async function pollJobs() {
    try {
        const data = await apiJson('/api/documents/jobs');
        const latest = (data.jobs || [])[0];
        if (latest) {
            jobStatus.textContent = `${latest.status}: ${latest.message}`;
            if (latest.status === 'pending' || latest.status === 'running') {
                setTimeout(pollJobs, 2000);
            }
        }
    } catch (_) {
        /* ignore polling errors */
    }
}

async function loadAdminOverview() {
    adminOverview.innerHTML = '<div class="empty-state">Проверка...</div>';
    try {
        const data = await apiJson('/api/admin/overview');
        const chroma = data.health.chroma || {};
        const models = data.models || {};
        const settings = data.settings || {};
        adminOverview.innerHTML = `
            <div class="data-card"><strong>LLM</strong><span>${data.health.llm ? 'доступен' : 'недоступен'}</span></div>
            <div class="data-card"><strong>Chroma</strong><span>${chroma.ok ? `${chroma.count} чанков` : escapeHtml(chroma.error || 'ошибка')}</span></div>
            <div class="data-card"><strong>Модели</strong><span>chat: ${escapeHtml(settings.chat_model || '')}<br>embed: ${escapeHtml(settings.embedding_model || '')}</span></div>
            <div class="data-card"><strong>История</strong><span>${data.usage.chat_count} чатов</span></div>
            <div class="data-card wide"><strong>Доступные модели</strong><span>${escapeHtml((models.available || []).join(', ') || models.error || 'нет данных')}</span></div>
            <div class="data-card wide"><strong>RAG</strong><span>top_k=${settings.rag_top_k}, min_score=${settings.rag_min_score}, citations=${settings.rag_max_citations}</span></div>
        `;
    } catch (error) {
        adminOverview.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    }
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

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
}
