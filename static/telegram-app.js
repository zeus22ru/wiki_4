(() => {
    'use strict';

    const tg = window.Telegram?.WebApp;
    const state = {chatId: null, chats: [], busy: false, controller: null};
    const $ = (id) => document.getElementById(id);
    const bootState = $('bootState');
    const errorState = $('errorState');
    const chatState = $('chatState');
    const messages = $('messages');
    const input = $('messageInput');
    const sendButton = $('sendButton');

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

    function markdown(text) {
        if (window.marked) {
            marked.setOptions({breaks: true, gfm: true});
            const html = marked.parse(text || '');
            return window.DOMPurify ? DOMPurify.sanitize(html) : escapeHtml(text);
        }
        return escapeHtml(text).replace(/\n/g, '<br>');
    }

    function scrollDown() { messages.scrollTop = messages.scrollHeight; }

    function addMessage(role, text, details = {}) {
        $('welcomeState')?.remove();
        const row = document.createElement('article');
        row.className = `tg-message tg-message--${role}`;
        const bubble = document.createElement('div');
        bubble.className = 'tg-message__bubble';
        if (role === 'assistant') bubble.innerHTML = markdown(text);
        else bubble.textContent = text;
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
        closeSheets();
        const data = await api(`/api/chats/${chatId}`);
        state.chatId = chatId;
        messages.replaceChildren();
        (data.messages || []).forEach((message) => addMessage(
            message.role === 'assistant' ? 'assistant' : 'user',
            message.content || '',
            {sources: message.sources || [], messageId: message.role === 'assistant' ? message.id : null},
        ));
        input.focus();
    }

    function newChat() {
        closeSheets();
        state.chatId = null;
        messages.innerHTML = '<div class="tg-welcome" id="welcomeState"><span class="tg-welcome__badge">Новый диалог</span><h1>Чем помочь?</h1><p>Задайте вопрос по корпоративной базе знаний.</p></div>';
        input.focus();
    }

    function setBusy(busy) {
        state.busy = busy;
        input.disabled = busy;
        sendButton.disabled = busy;
        sendButton.textContent = busy ? '…' : '➤';
        if (busy) tg?.enableClosingConfirmation?.(); else tg?.disableClosingConfirmation?.();
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
        if (state.busy) return;
        addMessage('user', text);
        input.value = '';
        input.style.height = '';
        const target = addMessage('assistant', 'Ищу информацию…');
        target.bubble.classList.add('tg-thinking');
        setBusy(true);
        state.controller = new AbortController();
        try {
            const response = await fetch('/api/chat/stream', {
                method: 'POST', credentials: 'same-origin', signal: state.controller.signal,
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: text, chat_id: state.chatId, answer_mode: 'default'}),
            });
            if (!response.ok) {
                let data = {}; try { data = await response.json(); } catch (_) { /* ignore */ }
                throw new Error(data.error || `Ошибка ${response.status}`);
            }
            await readSse(response, target);
            loadChats().catch(() => {});
        } catch (error) {
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

        if (!tg?.initData) {
            showError('Откройте приложение в Telegram', 'Эта страница получает безопасные данные входа только внутри Telegram.');
            return;
        }
        try {
            const auth = await api('/api/telegram/webapp/auth', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({init_data: tg.initData}),
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
        if (text.length >= 3) sendMessage(text);
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
