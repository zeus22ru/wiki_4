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
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ message: message })
        });
        
        const data = await response.json();
        
        // Убираем индикатор печати
        hideTypingIndicator();
        
        if (response.ok) {
            // Добавляем ответ бота
            addMessage(data.answer, 'bot');
            
            // Сохраняем источники
            if (data.sources && data.sources.length > 0) {
                currentSources = data.sources;
                // Добавляем кнопку для показа источников
                addSourcesButton();
            }
        } else {
            addMessage(`Ошибка: ${data.error}`, 'bot');
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

// Форматирование сообщения
function formatMessage(text) {
    // Экранируем HTML
    let formatted = text
        .replace(/&/g, '&')
        .replace(/</g, '<')
        .replace(/>/g, '>');
    
    // Преобразуем переносы строк в параграфы
    const paragraphs = formatted.split('\n\n');
    return paragraphs.map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');
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
function startNewChat() {
    // Очищаем все сообщения кроме приветственного
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
    
    // Очищаем источники
    currentSources = [];
    closeSourcesPanel();
    
    // Фокус на поле ввода
    messageInput.focus();
}

// Обработка Enter (отправка сообщения)
messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        messageForm.dispatchEvent(new Event('submit'));
    }
});
