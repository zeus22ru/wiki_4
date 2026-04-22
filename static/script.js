// Глобальные переменные
let currentSources = [];
let isProcessing = false;

// DOM элементы
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

// Инициализация
document.addEventListener('DOMContentLoaded', () => {
    checkHealth();
    setInterval(checkHealth, 30000); // Проверка каждые 30 секунд
    
    // Обработчики событий
    messageForm.addEventListener('submit', handleSubmit);
    closeSources.addEventListener('click', closeSourcesPanel);
    newChatBtn.addEventListener('click', startNewChat);
    
    // Фокус на поле ввода
    messageInput.focus();
});

// Проверка здоровья системы
async function checkHealth() {
    try {
        const response = await fetch('/api/health');
        const data = await response.json();
        
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

/** Классический POST /api/chat (если /api/chat/stream недоступен — 404, старый бэкенд или прокси). */
async function sendChatClassic(message) {
    const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ message: message }),
    });
    const data = await response.json();
    hideTypingIndicator();
    if (response.ok) {
        addMessage(data.answer, 'bot');
        if (data.sources && data.sources.length > 0) {
            currentSources = data.sources;
            addSourcesButton();
        }
    } else {
        const errText = data.error ? data.error : `Ошибка ${response.status}`;
        addMessage(errText, 'bot');
    }
}

// Обработка отправки сообщения
async function handleSubmit(e) {
    e.preventDefault();
    
    const message = messageInput.value.trim();
    
    if (!message || isProcessing) {
        return;
    }
    
    // Добавляем сообщение пользователя
    addMessage(message, 'user');
    messageInput.value = '';
    
    // Показываем индикатор печати
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
            body: JSON.stringify({ message: message }),
        });

        // Нет маршрута стрима (старая версия приложения, Apache без rewrite для вложенного пути и т.п.)
        if (response.status === 404) {
            console.warn(
                '[БочкарИИ] POST /api/chat/stream недоступен (404) — используется /api/chat без потока. ' +
                    'Перезапустите Flask с актуальным web_app.py или настройте прокси на /api/chat/stream.'
            );
            await sendChatClassic(message);
            return;
        }

        hideTypingIndicator();

        if (!response.ok) {
            let errText = `Ошибка ${response.status}`;
            try {
                const errData = await response.json();
                if (errData.error) {
                    errText = errData.error;
                }
            } catch (_) {
                /* не JSON */
            }
            addMessage(errText, 'bot');
            return;
        }

        if (!response.body || !response.body.getReader) {
            addMessage('Поток ответа недоступен в этом браузере', 'bot');
            return;
        }

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
            streamShell.appendChild(avatar);
            streamShell.appendChild(streamContent);
            messagesContainer.appendChild(streamShell);
            scrollToBottom();
        };

        const processSseBlock = (block) => {
            const lines = block.split('\n').map((l) => l.replace(/\r$/, ''));
            for (const line of lines) {
                if (!line.startsWith('data:')) {
                    continue;
                }
                const jsonStr = line.startsWith('data: ') ? line.slice(6) : line.slice(5).trimStart();
                let payload;
                try {
                    payload = JSON.parse(jsonStr);
                } catch (_) {
                    continue;
                }
                if (payload.type === 'delta') {
                    accumulated += payload.text || '';
                    ensureStreamShell();
                    streamContent.textContent = accumulated;
                    scrollToBottom();
                } else if (payload.type === 'done') {
                    const finalText = payload.answer != null ? payload.answer : accumulated;
                    ensureStreamShell();
                    const html = formatMessage(finalText);
                    streamContent.innerHTML = html;
                    streamContent.classList.remove('streaming-in-progress');
                    if (payload.sources && payload.sources.length > 0) {
                        currentSources = payload.sources;
                        addSourcesButton();
                    }
                } else if (payload.type === 'error') {
                    const msg = payload.message || 'Ошибка потока';
                    ensureStreamShell();
                    streamContent.textContent = msg;
                    streamContent.classList.remove('streaming-in-progress');
                }
            }
        };

        /** Уступка циклу событий: иначе несколько delta за один read сливаются в один кадр отрисовки. */
        const yieldForPaint = () =>
            new Promise((resolve) => {
                requestAnimationFrame(() => resolve());
            });

        while (true) {
            const { done, value } = await reader.read();
            if (done) {
                break;
            }
            buffer += decoder.decode(value, { stream: true });
            const chunks = buffer.split('\n\n');
            buffer = chunks.pop() || '';
            for (const part of chunks) {
                if (part.trim()) {
                    processSseBlock(part);
                    await yieldForPaint();
                }
            }
        }
        if (buffer.trim()) {
            processSseBlock(buffer);
        }
    } catch (error) {
        hideTypingIndicator();
        addMessage('Произошла ошибка при отправке запроса', 'bot');
    } finally {
        isProcessing = false;
        sendButton.disabled = false;
        messageInput.focus();
    }
}

// Добавление сообщения в чат
function addMessage(text, type) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}-message`;
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = type === 'user' ? '👤' : '🤖';
    
    const content = document.createElement('div');
    content.className = 'message-content';
    
    // Форматируем текст (простая разметка)
    const formattedText = formatMessage(text);
    content.innerHTML = formattedText;
    
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(content);
    
    messagesContainer.appendChild(messageDiv);
    scrollToBottom();
    
    return messageDiv;
}

// Форматирование сообщения с поддержкой Markdown
function formatMessage(text) {
    // Настройка marked.js
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,      // Переносы строк в <br>
            gfm: true,         // GitHub Flavored Markdown
            highlight: function(code, lang) {
                // Подсветка кода через highlight.js
                if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
                    try {
                        return hljs.highlight(code, { language: lang }).value;
                    } catch (e) {
                        console.error('Ошибка подсветки кода:', e);
                    }
                }
                // Если язык не указан или не поддерживается, пытаемся автоопределение
                if (typeof hljs !== 'undefined') {
                    try {
                        return hljs.highlightAuto(code).value;
                    } catch (e) {
                        console.error('Ошибка автоопределения кода:', e);
                    }
                }
                return code;
            }
        });
        
        // Рендерим Markdown
        const html = marked.parse(text);
        return `<div class="markdown-content">${html}</div>`;
    } else {
        // Fallback если marked.js не загружен
        console.warn('marked.js не загружен, используется простое форматирование');
        let formatted = text
            .replace(/&/g, '&')
            .replace(/</g, '<')
            .replace(/>/g, '>');
        
        const paragraphs = formatted.split('\n\n');
        return paragraphs.map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');
    }
}

// Показать индикатор печати
function showTypingIndicator() {
    const typingDiv = document.createElement('div');
    typingDiv.className = 'message bot-message';
    typingDiv.id = 'typingIndicator';
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = '🤖';
    
    const content = document.createElement('div');
    content.className = 'message-content';
    
    const indicator = document.createElement('div');
    indicator.className = 'typing-indicator';
    indicator.innerHTML = '<span></span><span></span><span></span>';
    
    content.appendChild(indicator);
    typingDiv.appendChild(avatar);
    typingDiv.appendChild(content);
    
    messagesContainer.appendChild(typingDiv);
    scrollToBottom();
}

// Скрыть индикатор печати
function hideTypingIndicator() {
    const typingIndicator = document.getElementById('typingIndicator');
    if (typingIndicator) {
        typingIndicator.remove();
    }
}

// Добавить кнопку показа источников
function addSourcesButton() {
    const lastMessage = messagesContainer.lastElementChild;
    if (!lastMessage || !lastMessage.classList.contains('bot-message')) {
        return;
    }
    
    const content = lastMessage.querySelector('.message-content');
    
    // Проверяем, есть ли уже кнопка
    if (content.querySelector('.show-sources-btn')) {
        return;
    }
    
    const button = document.createElement('button');
    button.className = 'show-sources-btn';
    button.textContent = `📚 Показать источники (${currentSources.length})`;
    button.addEventListener('click', openSourcesPanel);
    
    content.appendChild(button);
}

// Открыть панель источников
function openSourcesPanel() {
    sourcesList.innerHTML = '';
    
    currentSources.forEach(source => {
        const sourceItem = document.createElement('div');
        sourceItem.className = 'source-item';
        
        const title = document.createElement('div');
        title.className = 'source-title';
        title.textContent = source.title;
        
        const path = document.createElement('div');
        path.className = 'source-path';
        path.textContent = source.path;
        
        const relevance = document.createElement('div');
        relevance.className = 'source-relevance';
        relevance.textContent = `Релевантность: ${source.relevance}`;
        
        sourceItem.appendChild(title);
        sourceItem.appendChild(path);
        sourceItem.appendChild(relevance);
        
        sourcesList.appendChild(sourceItem);
    });
    
    sourcesPanel.classList.add('open');
}

// Закрыть панель источников
function closeSourcesPanel() {
    sourcesPanel.classList.remove('open');
}

// Прокрутка вниз
function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// Начать новый чат
async function startNewChat() {
    // Очищаем сообщения
    messagesContainer.innerHTML = '';
    
    // Добавляем приветственное сообщение
    const welcomeDiv = document.createElement('div');
    welcomeDiv.className = 'message bot-message';
    welcomeDiv.innerHTML = `
        <div class="message-avatar">🤖</div>
        <div class="message-content">
            <p>Привет! Я AI-ассистент по базе знаний компании. Задайте мне любой вопрос, и я постараюсь найти ответ в документации.</p>
        </div>
    `;
    messagesContainer.appendChild(welcomeDiv);
}

// Обработка Enter (отправка сообщения)
messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        messageForm.dispatchEvent(new Event('submit'));
    }
});

// Экранирование HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
