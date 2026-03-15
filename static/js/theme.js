/**
 * Theme Manager
 * Управление темами (светлая/тёмная/auto)
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

        // Слушаем изменения системной темы
        if (window.matchMedia) {
            const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');
            darkModeQuery.addEventListener('change', () => {
                if (this.currentTheme === 'auto') {
                    this.applyTheme('auto');
                }
            });
        }
    }

    /**
     * Получить сохранённую тему из localStorage
     */
    getStoredTheme() {
        const stored = localStorage.getItem('theme');
        return stored || 'auto';
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

        if (theme === 'auto') {
            actualTheme = this.getSystemTheme();
        }

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
        const autoIcon = themeToggle.querySelector('.auto-icon');

        if (sunIcon) sunIcon.style.display = 'none';
        if (moonIcon) moonIcon.style.display = 'none';
        if (autoIcon) autoIcon.style.display = 'none';

        switch (theme) {
            case 'light':
                if (sunIcon) sunIcon.style.display = 'block';
                break;
            case 'dark':
                if (moonIcon) moonIcon.style.display = 'block';
                break;
            case 'auto':
                if (autoIcon) autoIcon.style.display = 'block';
                break;
        }
    }

    /**
     * Переключить тему (light -> dark -> auto -> light)
     */
    toggleTheme() {
        const themes = ['light', 'dark', 'auto'];
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
            dark: '🌙 Тёмная тема',
            auto: '🔄 Автоматическая тема'
        };

        showToast(messages[theme] || 'Тема изменена', 'success');
    }

    /**
     * Установить конкретную тему
     */
    setTheme(theme) {
        if (['light', 'dark', 'auto'].includes(theme)) {
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
     * Получить фактическую тему (с учётом auto)
     */
    getActualTheme() {
        if (this.currentTheme === 'auto') {
            return this.getSystemTheme();
        }
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
