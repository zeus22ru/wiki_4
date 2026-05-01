/**
 * Theme Manager
 * Управление темами (светлая/тёмная)
 */

class ThemeManager {
    constructor() {
        this.currentTheme = this.getStoredTheme();
        this.init();
    }

    /**
     * Инициализация менеджера тем
     */
    init() {
        // Применяем сохранённую тему
        this.applyTheme(this.currentTheme);

        // Добавляем слушатель на переключатель тем
        const themeToggle = document.getElementById('themeToggle');
        if (themeToggle) {
            themeToggle.addEventListener('click', () => this.toggleTheme());
        }

        // Системная тема используется только как стартовая, если настройка ещё не сохранена.
    }

    /**
     * Получить сохранённую тему из localStorage
     */
    getStoredTheme() {
        const stored = localStorage.getItem('theme');
        return ['light', 'dark'].includes(stored) ? stored : this.getSystemTheme();
    }

    /**
     * Сохранить тему в localStorage
     */
    saveTheme(theme) {
        localStorage.setItem('theme', theme);
        this.currentTheme = theme;
    }

    /**
     * Определить системную тему
     */
    getSystemTheme() {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return 'dark';
        }
        return 'light';
    }

    /**
     * Применить тему к документу
     */
    applyTheme(theme) {
        let actualTheme = theme;

        // Устанавливаем атрибут data-theme
        if (actualTheme === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
        } else {
            document.documentElement.removeAttribute('data-theme');
        }

        // Обновляем иконку переключателя
        this.updateThemeIcon(theme);
    }

    /**
     * Обновить иконку переключателя тем
     */
    updateThemeIcon(theme) {
        const themeToggle = document.getElementById('themeToggle');
        if (!themeToggle) return;

        const sunIcon = themeToggle.querySelector('.sun-icon');
        const moonIcon = themeToggle.querySelector('.moon-icon');

        if (sunIcon) sunIcon.style.display = 'none';
        if (moonIcon) moonIcon.style.display = 'none';

        switch (theme) {
            case 'light':
                if (sunIcon) sunIcon.style.display = 'block';
                break;
            case 'dark':
                if (moonIcon) moonIcon.style.display = 'block';
                break;
        }

        const labels = {
            light: 'Светлая тема. Переключить тему',
            dark: 'Тёмная тема. Переключить тему'
        };
        themeToggle.setAttribute('aria-label', labels[theme] || labels.light);
        themeToggle.setAttribute('title', labels[theme] || labels.light);
    }

    /**
     * Переключить тему (light -> dark -> light)
     */
    toggleTheme() {
        const themes = ['light', 'dark'];
        const currentIndex = themes.indexOf(this.currentTheme);
        const nextIndex = (currentIndex + 1) % themes.length;
        const nextTheme = themes[nextIndex];

        this.saveTheme(nextTheme);
        this.applyTheme(nextTheme);

        // Показываем уведомление
        this.showThemeNotification(nextTheme);
    }

    /**
     * Показать уведомление о смене темы
     */
    showThemeNotification(theme) {
        const messages = {
            light: '☀️ Светлая тема',
            dark: '🌙 Тёмная тема'
        };

        if (typeof showToast === 'function') {
            showToast(messages[theme] || 'Тема изменена', 'success');
        }
    }

    /**
     * Установить конкретную тему
     */
    setTheme(theme) {
        if (['light', 'dark'].includes(theme)) {
            this.saveTheme(theme);
            this.applyTheme(theme);
        }
    }

    /**
     * Получить текущую тему
     */
    getCurrentTheme() {
        return this.currentTheme;
    }

    /**
     * Получить фактическую тему
     */
    getActualTheme() {
        return this.currentTheme;
    }
}

// Создаём глобальный экземпляр
let themeManager;

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    themeManager = new ThemeManager();
});

// Экспорт для использования в других модулях
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ThemeManager;
}
