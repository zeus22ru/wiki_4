(() => {
    'use strict';

    const tg = window.Telegram?.WebApp;
    const state = {chatId: null, chats: [], busy: false, uploading: false, attachments: [], controller: null};
    let mermaidInitialized = false;
    let mermaidTheme = null;
    let markedConfigured = false;
    const $ = (id) => document.getElementById(id);
    const bootState = $('bootState');
    const errorState = $('errorState');
    const chatState = $('chatState');
    const messages = $('messages');
    const input = $('messageInput');
    const sendButton = $('sendButton');
    const attachmentInput = $('attachmentInput');
    const maxAttachments = Number($('messageForm').dataset.attachmentMaxCount) || 3;
    const maxAttachmentBytes = Number($('messageForm').dataset.attachmentMaxBytes) || 5242880;

    function attachmentStatus(text) {
        $('attachmentStatus').textContent = text;
        $('attachmentStatus').hidden = !text;
    }

    function renderAttachments(container, items, removable = false) {
        items.forEach((item) => {
            const card = document.createElement('div');
            card.className = 'tg-attachment';
            const link = document.createElement('a');
            link.href = `/api/chat/attachments/${encodeURIComponent(item.id)}`;
            link.target = '_blank';
            link.rel = 'noopener';
            if (item.kind === 'image') {
                const img = document.createElement('img');
                img.src = link.href;
                img.alt = item.filename || 'Изображение';
                img.loading = 'lazy';
                img.addEventListener('load', scrollDown, {once: true});
                img.addEventListener('error', () => { link.textContent = item.filename || 'Изображение недоступно'; }, {once: true});
                link.appendChild(img);
            } else {
                link.textContent = item.filename || 'Вложение';
            }
            card.appendChild(link);
            if (removable) {
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.textContent = '×';
                remove.setAttribute('aria-label', `Убрать ${item.filename || 'изображение'}`);
                remove.disabled = state.busy || state.uploading;
                remove.addEventListener('click', () => {
                    state.attachments = state.attachments.filter((entry) => entry.id !== item.id);
                    renderPendingAttachments();
                });
                card.appendChild(remove);
            }
            container.appendChild(card);
        });
    }

    function renderPendingAttachments() {
        const preview = $('attachmentPreview');
        preview.replaceChildren();
        preview.hidden = !state.attachments.length;
        renderAttachments(preview, state.attachments, true);
    }

    async function uploadImages(files) {
        if (state.busy || state.uploading || $('attachButton').hidden || !files.length) return;
        state.uploading = true;
        setBusy(false);
        attachmentStatus('Загрузка изображений…');
        const errors = [];
        try {
            for (const file of files) {
                if (state.attachments.length >= maxAttachments) {
                    errors.push(`Можно прикрепить не более ${maxAttachments} изображений.`);
                    break;
                }
                if (!/\.(png|jpe?g|webp|gif)$/i.test(file.name)) {
                    errors.push(`${file.name}: выберите PNG, JPEG, WebP или GIF.`);
                    continue;
                }
                if (file.size > maxAttachmentBytes) {
                    errors.push(`${file.name}: размер превышает ${Math.round(maxAttachmentBytes / 1048576 * 10) / 10} МБ.`);
                    continue;
                }
                const body = new FormData();
                body.append('files', file);
                try {
                    const data = await api('/api/chat/attachments', {method: 'POST', body});
                    if (!data.attachments?.length) throw new Error('Файл не загружен. Попробуйте ещё раз.');
                    state.attachments.push(...data.attachments);
                    renderPendingAttachments();
                } catch (error) {
                    errors.push(`${file.name}: ${error.message}`);
                }
            }
        } finally {
            state.uploading = false;
            attachmentInput.value = '';
            setBusy(false);
            attachmentStatus(errors.join(' '));
        }
    }

    function telegramInitData() {
        if (tg?.initData) return tg.initData;

        // Telegram also appends the signed launch payload to the URL fragment.
        // This fallback supports desktop clients where the WebApp bridge is not
        // ready when the application script is evaluated. The server validates
        // the payload HMAC before creating a session.
        const fragment = window.location.hash.startsWith('#')
            ? window.location.hash.slice(1)
            : window.location.hash;
        return new URLSearchParams(fragment).get('tgWebAppData') || '';
    }

    function applyTelegramTheme() {
        document.documentElement.dataset.theme = tg?.colorScheme === 'dark' ? 'dark' : 'light';
        if (tg?.themeParams?.bg_color) {
            document.querySelector('meta[name="theme-color"]')?.setAttribute('content', tg.themeParams.bg_color);
        }
    }

    async function api(url, options = {}) {
        const response = await fetch(url, {credentials: 'same-origin', ...options});
        let data = {};
        try { data = await response.json(); } catch (_) { data = {}; }
        if (!response.ok) {
            const error = new Error(data.error || `Ошибка ${response.status}`);
            error.code = data.code;
            error.status = response.status;
            throw error;
        }
        return data;
    }

    function showError(title, text, showBotLink = false) {
        bootState.hidden = true;
        chatState.hidden = true;
        errorState.hidden = false;
        $('errorTitle').textContent = title;
        $('errorText').textContent = text;
        const botLink = $('openBotLink');
        const username = document.body.dataset.botUsername;
        botLink.hidden = !showBotLink || !username;
        if (!botLink.hidden) botLink.href = `https://t.me/${encodeURIComponent(username)}`;
    }

    function escapeHtml(text) {
        const node = document.createElement('div');
        node.textContent = text || '';
        return node.innerHTML;
    }

    function ensureMarkedConfigured() {
        if (markedConfigured || !window.marked) {
            return;
        }
        marked.setOptions({breaks: true, gfm: true});
        markedConfigured = true;
    }

    function markdown(text) {
        if (window.marked) {
            ensureMarkedConfigured();
            const html = marked.parse(text || '');
            // Без DOMPurify HTML не вставляем — только экранированный текст.
            return window.DOMPurify ? DOMPurify.sanitize(html) : escapeHtml(text);
        }
        return escapeHtml(text).replace(/\n/g, '<br>');
    }

    function looksLikeMermaid(code) {
        const text = String(code || '').trim();
        return /^(?:graph|flowchart)\s|^(?:sequenceDiagram|classDiagram|stateDiagram|erDiagram|journey|gantt|mindmap|timeline|quadrantChart|sankey-beta)\b/.test(text);
    }

    function mermaidCodeBlocks(container) {
        return [...container.querySelectorAll('pre > code')].filter((code) => {
            const language = String(code.className || '').toLowerCase();
            return language.includes('language-mermaid') || language.includes('lang-mermaid') || looksLikeMermaid(code.textContent);
        });
    }

    function ensureMermaid() {
        if (!window.mermaid) return false;
        const theme = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'default';
        if (mermaidInitialized && mermaidTheme === theme) return true;
        try {
            mermaid.initialize({
                startOnLoad: false,
                securityLevel: 'strict',
                suppressErrorRendering: true,
                theme,
            });
            mermaidInitialized = true;
            mermaidTheme = theme;
            return true;
        } catch (_) {
            return false;
        }
    }

    function replaceStreamingMermaidWithPlaceholder(container) {
        mermaidCodeBlocks(container).forEach((code) => {
            const placeholder = document.createElement('div');
            placeholder.className = 'tg-mermaid-placeholder';
            placeholder.setAttribute('role', 'status');
            placeholder.textContent = 'Формирование диаграммы…';
            code.parentElement.replaceWith(placeholder);
        });
    }

    function renderMermaidIn(container) {
        const blocks = mermaidCodeBlocks(container);
        if (!blocks.length) return;

        if (!ensureMermaid()) {
            blocks.forEach((code) => {
                const fallback = document.createElement('div');
                fallback.className = 'tg-mermaid-error';
                fallback.textContent = 'Диаграмма временно недоступна.';
                code.parentElement.replaceWith(fallback);
            });
            return;
        }

        blocks.forEach((code, index) => {
            const raw = String(code.textContent || '').trim();
            const diagram = document.createElement('div');
            diagram.className = 'tg-mermaid';
            diagram.setAttribute('role', 'img');
            diagram.setAttribute('aria-label', 'Диаграмма');
            code.parentElement.replaceWith(diagram);
            const renderId = `tg-mmd-${Date.now()}-${index}-${Math.random().toString(16).slice(2)}`;

            const showError = () => {
                diagram.className = 'tg-mermaid-error';
                diagram.removeAttribute('role');
                diagram.removeAttribute('aria-label');
                diagram.textContent = 'Не удалось построить диаграмму.';
            };

            const render = (source, allowFix) => {
                Promise.resolve()
                    .then(() => mermaid.render(`${renderId}-${allowFix ? 'raw' : 'fixed'}`, source))
                    .then((result) => {
                        const svg = result?.svg || result;
                        if (typeof svg !== 'string' || !svg.trim().startsWith('<svg')) throw new Error('invalid_svg');
                        diagram.innerHTML = svg;
                        scrollDown();
                    })
                    .catch((error) => {
                        if (!allowFix) {
                            showError();
                            return;
                        }
                        api('/api/mermaid/fix', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({code: source, parse_error: String(error?.message || error || '')}),
                        })
                            .then((data) => {
                                const fixed = String(data?.code || '').trim();
                                if (!fixed || fixed === source) throw new Error('not_fixed');
                                render(fixed, false);
                            })
                            .catch(showError);
                    });
            };

            render(raw, true);
        });
    }

    function scrollDown() { messages.scrollTop = messages.scrollHeight; }

    function addMessage(role, text, details = {}) {
        $('welcomeState')?.remove();
        const row = document.createElement('article');
        row.className = `tg-message tg-message--${role}`;
        const bubble = document.createElement('div');
        bubble.className = 'tg-message__bubble';
        if (role === 'assistant') {
            bubble.innerHTML = markdown(text);
            renderMermaidIn(bubble);
        }
        else bubble.textContent = text;
        if (details.attachments?.length) {
            const attachments = document.createElement('div');
            attachments.className = 'tg-attachments tg-message-attachments';
            renderAttachments(attachments, details.attachments);
            bubble.appendChild(attachments);
        }
        row.appendChild(bubble);
        messages.appendChild(row);

        if (role === 'assistant' && (details.sources?.length || details.messageId)) {
            const controls = document.createElement('div');
            controls.className = 'tg-message__meta';
            if (details.sources?.length) {
                const sourceButton = document.createElement('button');
                sourceButton.type = 'button';
                sourceButton.textContent = `Источники · ${details.sources.length}`;
                sourceButton.addEventListener('click', () => openSources(details.sources));
                controls.appendChild(sourceButton);
            }
            if (details.messageId) {
                ['up', 'down'].forEach((rating) => {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.textContent = rating === 'up' ? '👍' : '👎';
                    button.addEventListener('click', () => sendFeedback(button, rating, details.messageId));
                    controls.appendChild(button);
                });
            }
            bubble.appendChild(controls);
        }
        scrollDown();
        return {row, bubble};
    }

    async function sendFeedback(button, rating, messageId) {
        try {
            await api('/api/chats/feedback', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({session_id: state.chatId, message_id: messageId, rating}),
            });
            button.disabled = true;
            tg?.HapticFeedback?.notificationOccurred('success');
        } catch (_) { tg?.HapticFeedback?.notificationOccurred('error'); }
    }

    function openSources(sources) {
        const list = $('sourceList');
        list.replaceChildren();
        sources.forEach((source, index) => {
            const item = document.createElement('article');
            item.className = 'tg-source';
            const title = document.createElement('strong');
            title.textContent = `${index + 1}. ${source.title || source.source || 'Источник'}`;
            const path = document.createElement('span');
            path.textContent = source.section_path || source.path || '';
            item.append(title, path);
            list.appendChild(item);
        });
        $('sourcesSheet').hidden = false;
        tg?.BackButton?.show();
    }

    function closeSheets() {
        document.querySelectorAll('.tg-sheet').forEach((sheet) => { sheet.hidden = true; });
        tg?.BackButton?.hide();
    }

    async function loadChats() {
        const data = await api('/api/chats?limit=30');
        state.chats = data.chats || [];
        const list = $('chatList');
        list.replaceChildren();
        if (!state.chats.length) {
            const empty = document.createElement('p'); empty.textContent = 'История пока пуста.'; list.appendChild(empty);
        }
        state.chats.forEach((chat) => {
            const button = document.createElement('button');
            button.type = 'button';
            const title = document.createElement('strong'); title.textContent = chat.title || 'Диалог';
            const date = document.createElement('span');
            date.textContent = chat.updated_at ? new Date(chat.updated_at).toLocaleString('ru-RU') : '';
            button.append(title, date);
            button.addEventListener('click', () => openChat(chat.id));
            list.appendChild(button);
        });
    }

    async function openChat(chatId) {
        if (state.busy || state.uploading) return;
        closeSheets();
        setBusy(true);
        try {
        const data = await api(`/api/chats/${chatId}`);
        state.chatId = chatId;
        state.attachments = [];
        attachmentStatus('');
        messages.replaceChildren();
        (data.messages || []).forEach((message) => addMessage(
            message.role === 'assistant' ? 'assistant' : 'user',
            message.content || '',
            {sources: message.sources || [], messageId: message.role === 'assistant' ? message.id : null, attachments: message.metadata?.attachments || []},
        ));
        } catch (error) {
            attachmentStatus(error.message || 'Не удалось открыть диалог');
        } finally {
            setBusy(false);
        }
        input.focus();
    }

    function newChat() {
        if (state.busy || state.uploading) return;
        closeSheets();
        state.chatId = null;
        state.attachments = [];
        input.value = '';
        renderPendingAttachments();
        attachmentStatus('');
        messages.innerHTML = '<div class="tg-welcome" id="welcomeState"><span class="tg-welcome__badge">Новый диалог</span><h1>Чем помочь?</h1><p>Задайте вопрос по корпоративной базе знаний.</p></div>';
        input.focus();
    }

    function setBusy(busy) {
        state.busy = busy;
        input.disabled = busy;
        const locked = busy || state.uploading;
        sendButton.disabled = locked;
        $('attachButton').disabled = locked;
        attachmentInput.disabled = locked;
        $('historyButton').disabled = locked;
        $('newChatButton').disabled = locked;
        sendButton.textContent = locked ? '…' : '➤';
        renderPendingAttachments();
        if (locked) tg?.enableClosingConfirmation?.(); else tg?.disableClosingConfirmation?.();
    }

    async function readSse(response, target) {
        if (!response.body) throw new Error('Потоковые ответы не поддерживаются');
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '', answer = '', completed = false;

        const processBlock = (block) => {
            block.split('\n').forEach((line) => {
                if (!line.startsWith('data:')) return;
                let payload;
                try { payload = JSON.parse(line.slice(5).trim()); } catch (_) { return; }
                if (payload.type === 'delta') {
                    answer += payload.text || '';
                    target.bubble.innerHTML = markdown(answer);
                    replaceStreamingMermaidWithPlaceholder(target.bubble);
                    scrollDown();
                } else if (payload.type === 'status' && !answer) {
                    target.bubble.innerHTML = `<span class="tg-thinking">${escapeHtml(payload.message || 'Готовлю ответ…')}</span>`;
                } else if (payload.type === 'done') {
                    completed = true;
                    state.chatId = payload.chat_id || state.chatId;
                    target.row.remove();
                    addMessage('assistant', payload.answer || answer, {sources: payload.sources || [], messageId: payload.message_id});
                    tg?.HapticFeedback?.notificationOccurred('success');
                } else if (payload.type === 'error') {
                    completed = true;
                    target.bubble.textContent = payload.message || 'Ошибка ответа';
                    target.row.classList.add('tg-message--error');
                }
            });
        };

        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, {stream: true});
            const blocks = buffer.split('\n\n');
            buffer = blocks.pop() || '';
            blocks.filter(Boolean).forEach(processBlock);
        }
        if (buffer.trim()) processBlock(buffer);
        if (!completed) throw new Error('Соединение прервано до завершения ответа');
    }

    async function sendMessage(text) {
        if (state.busy || state.uploading) return;
        const attachments = [...state.attachments];
        if (!attachments.length && text.length < 3) return;
        const userMessage = addMessage('user', text, {attachments});
        state.attachments = [];
        attachmentStatus('');
        input.value = '';
        input.style.height = '';
        const target = addMessage('assistant', 'Ищу информацию…');
        target.bubble.classList.add('tg-thinking');
        setBusy(true);
        state.controller = new AbortController();
        let accepted = false;
        try {
            const response = await fetch('/api/chat/stream', {
                method: 'POST', credentials: 'same-origin', signal: state.controller.signal,
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: text, chat_id: state.chatId, answer_mode: 'default', attachment_ids: attachments.map((item) => item.id)}),
            });
            if (!response.ok) {
                let data = {}; try { data = await response.json(); } catch (_) { /* ignore */ }
                throw new Error(data.error || `Ошибка ${response.status}`);
            }
            accepted = true;
            await readSse(response, target);
            loadChats().catch(() => {});
        } catch (error) {
            if (!accepted) {
                state.attachments = attachments;
                input.value = text;
                userMessage.row.remove();
            }
            target.bubble.textContent = error.name === 'AbortError' ? 'Ответ остановлен.' : (error.message || 'Не удалось получить ответ');
            tg?.HapticFeedback?.notificationOccurred('error');
        } finally {
            state.controller = null;
            setBusy(false);
            input.focus();
        }
    }

    async function initialize() {
        applyTelegramTheme();
        tg?.onEvent?.('themeChanged', applyTelegramTheme);
        tg?.BackButton?.onClick(closeSheets);
        tg?.ready?.();
        tg?.expand?.();

        const initData = telegramInitData();
        if (!initData) {
            showError('Откройте приложение в Telegram', 'Эта страница получает безопасные данные входа только внутри Telegram.');
            return;
        }
        try {
            const auth = await api('/api/telegram/webapp/auth', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({init_data: initData}),
            });
            $('serviceStatus').textContent = auth.telegram_user?.first_name ? `В сети · ${auth.telegram_user.first_name}` : 'В сети';
            bootState.hidden = true;
            errorState.hidden = true;
            chatState.hidden = false;
            $('historyButton').disabled = false;
            await loadChats();
        } catch (error) {
            const needsLink = error.code === 'telegram_not_linked';
            showError(
                needsLink ? 'Нужна привязка аккаунта' : 'Не удалось войти',
                needsLink ? 'Откройте обычный веб-интерфейс БочкарИИ, получите код Telegram и отправьте боту команду /start с этим кодом.' : error.message,
                needsLink,
            );
        }
    }

    $('messageForm').addEventListener('submit', (event) => {
        event.preventDefault();
        const text = input.value.trim();
        if (text.length >= 3 || state.attachments.length) sendMessage(text);
    });
    $('attachButton').addEventListener('click', () => attachmentInput.click());
    attachmentInput.addEventListener('change', () => uploadImages([...attachmentInput.files]));
    input.addEventListener('paste', (event) => {
        const images = [...(event.clipboardData?.files || [])].filter((file) => file.type.startsWith('image/'));
        if (images.length && !$('attachButton').hidden) {
            event.preventDefault();
            uploadImages(images);
        }
    });
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = `${Math.min(input.scrollHeight, 128)}px`;
    });
    input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault(); $('messageForm').requestSubmit();
        }
    });
    document.addEventListener('click', (event) => {
        const prompt = event.target.closest('[data-prompt]')?.dataset.prompt;
        if (prompt) { input.value = prompt; input.focus(); }
        if (event.target.closest('[data-close-sheet]')) closeSheets();
    });
    $('historyButton').addEventListener('click', async () => {
        await loadChats().catch(() => {}); $('historySheet').hidden = false; tg?.BackButton?.show();
    });
    $('continueChatButton').addEventListener('click', async () => {
        if (!state.chats.length) return;
        await openChat(state.chats[0].id);
    });
    $('newChatButton').addEventListener('click', newChat);
    $('retryButton').addEventListener('click', () => { location.reload(); });
    $('openBotLink').addEventListener('click', (event) => {
        if (tg?.openTelegramLink) { event.preventDefault(); tg.openTelegramLink(event.currentTarget.href); }
    });

    initialize();
})();
