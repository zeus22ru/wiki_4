/**
 * Clipboard Manager
 * Управление копированием текста сообщений
 */

class ClipboardManager {
    constructor() {
        this.init();
    }

    /**
     * Инициализация менеджера буфера обмена
     */
    init() {
        // Добавляем кнопки копирования к существующим сообщениям
        this.addCopyButtonsToExistingMessages();

        // Наблюдаем за новыми сообщениями
        this.observeNewMessages();

        // Добавляем глобальный обработчик для кнопок копирования
        document.addEventListener('click', (e) => {
            if (e.target.closest('.copy-button')) {
                this.handleCopyClick(e.target.closest('.copy-button'));
            }
        });
    }

    /**
     * Добавить кнопки копирования к существующим сообщениям
     */
    addCopyButtonsToExistingMessages() {
        const messages = document.querySelectorAll('.message-content');
        messages.forEach(message => {
            if (!message.querySelector('.copy-button')) {
                this.addCopyButton(message);
            }
        });
    }

    /**
     * Добавить кнопку копирования к сообщению
     */
    addCopyButton(messageContent) {
        const copyButton = document.createElement('button');
        copyButton.className = 'copy-button';
        copyButton.setAttribute('aria-label', 'Копировать текст');
        copyButton.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
        `;
        messageContent.appendChild(copyButton);
    }

    /**
     * Наблюдать за новыми сообщениями
     */
    observeNewMessages() {
        const messagesContainer = document.getElementById('messages');
        if (!messagesContainer) return;

        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === 1) { // Element node
                        // Проверяем, является ли добавленный узел сообщением
                        if (node.classList && node.classList.contains('message')) {
                            const messageContent = node.querySelector('.message-content');
                            if (messageContent) {
                                this.addCopyButton(messageContent);
                            }
                        }
                        // Проверяем дочерние элементы
                        const messages = node.querySelectorAll && node.querySelectorAll('.message-content');
                        if (messages) {
                            messages.forEach(message => {
                                if (!message.querySelector('.copy-button')) {
                                    this.addCopyButton(message);
                                }
                            });
                        }
                    }
                });
            });
        });

        observer.observe(messagesContainer, {
            childList: true,
            subtree: true
        });
    }

    /**
     * Обработчик клика по кнопке копирования
     */
    async handleCopyClick(button) {
        const messageContent = button.closest('.message-content');
        if (!messageContent) return;

        // Получаем текст без кнопки копирования
        const textToCopy = this.getTextToCopy(messageContent);

        try {
            // Пытаемся скопировать в буфер обмена
            await this.copyToClipboard(textToCopy);
            
            // Показываем уведомление
            showToast('✅ Текст скопирован', 'success');
            
            // Анимация кнопки
            this.animateButton(button);
        } catch (error) {
            console.error('Ошибка копирования:', error);
            showToast('❌ Не удалось скопировать текст', 'error');
        }
    }

    /**
     * Получить текст для копирования (без HTML тегов)
     */
    getTextToCopy(messageContent) {
        // Создаём клон элемента
        const clone = messageContent.cloneNode(true);
        
        // Удаляем кнопку копирования из клона
        const copyButton = clone.querySelector('.copy-button');
        if (copyButton) {
            copyButton.remove();
        }
        
        // Получаем текст
        return clone.innerText || clone.textContent;
    }

    /**
     * Скопировать текст в буфер обмена
     */
    async copyToClipboard(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
        } else {
            // Fallback для старых браузеров
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            try {
                document.execCommand('copy');
            } finally {
                document.body.removeChild(textarea);
            }
        }
    }

    /**
     * Анимация кнопки при успешном копировании
     */
    animateButton(button) {
        button.style.transform = 'scale(1.2)';
        button.style.color = 'var(--success-color)';
        
        setTimeout(() => {
            button.style.transform = 'scale(1)';
            button.style.color = '';
        }, 200);
    }

    /**
     * Копировать весь чат
     */
    async copyAllMessages() {
        const messages = document.querySelectorAll('.message-content');
        let fullText = '';
        
        messages.forEach((message, index) => {
            const isUser = message.closest('.user-message');
            const prefix = isUser ? 'Вы: ' : 'Бот: ';
            fullText += prefix + this.getTextToCopy(message) + '\n\n';
        });

        try {
            await this.copyToClipboard(fullText.trim());
            showToast('✅ Весь чат скопирован', 'success');
        } catch (error) {
            console.error('Ошибка копирования чата:', error);
            showToast('❌ Не удалось скопировать чат', 'error');
        }
    }

    /**
     * Копировать последнее сообщение бота
     */
    async copyLastBotMessage() {
        const botMessages = document.querySelectorAll('.bot-message .message-content');
        if (botMessages.length === 0) {
            showToast('❌ Нет сообщений бота', 'error');
            return;
        }

        const lastMessage = botMessages[botMessages.length - 1];
        const text = this.getTextToCopy(lastMessage);

        try {
            await this.copyToClipboard(text);
            showToast('✅ Ответ бота скопирован', 'success');
        } catch (error) {
            console.error('Ошибка копирования:', error);
            showToast('❌ Не удалось скопировать', 'error');
        }
    }
}

/**
 * Показать уведомление (toast)
 */
function showToast(message, type = 'success') {
    // Удаляем существующий toast
    const existingToast = document.querySelector('.toast');
    if (existingToast) {
        existingToast.remove();
    }

    // Создаём новый toast
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    // Показываем toast
    requestAnimationFrame(() => {
        toast.classList.add('show');
    });

    // Скрываем через 3 секунды
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, 3000);
}

// Создаём глобальный экземпляр
let clipboardManager;

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    clipboardManager = new ClipboardManager();
});

// Экспорт для использования в других модулях
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { ClipboardManager, showToast };
}
