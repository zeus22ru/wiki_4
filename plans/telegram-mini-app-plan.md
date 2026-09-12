# План Telegram Mini App для «БочкарИИ»

## Цель MVP

Дать привязанному пользователю быстрый мобильный доступ к корпоративной базе знаний прямо внутри Telegram: вопрос, потоковый ответ, история диалогов, источники и оценка ответа. Админка, редактирование базы и расширенные RAG-настройки остаются в основном веб-интерфейсе.

## Архитектура

1. Telegram открывает `/telegram-app` и передаёт `Telegram.WebApp.initData`.
2. `POST /api/telegram/webapp/auth` проверяет HMAC и свежесть `auth_date` по bot token.
3. Проверенный Telegram ID сопоставляется с существующей записью `telegram_links`.
4. Сервер создаёт подписанную Flask-сессию. После этого Mini App использует существующие `/api/chats`, `/api/chat/stream` и `/api/chats/feedback` без передачи Telegram ID из браузера.
5. Бот и polling-worker продолжают работать без изменений.

## Этапы и делегирование

- Backend/security-аудит — дешёвый субагент: готово; выявлен обязательный HMAC auth и риск доверия к ID из браузера.
- Mobile UX/API mapping — дешёвый субагент: готово; выбран одноэкранный mobile-first UI с bottom sheets.
- QA/risk review — дешёвый субагент: готово; сформированы проверки подписи, TTL, IDOR и deployment checklist.
- Интеграция и правки исходников — основной агент: HMAC middleware, auth route, Mini App UI, конфигурация, документация.
- Проверка — основной агент: unit/API tests и регрессия Telegram suite.

## Границы MVP

Входит: безопасный вход, привязанный аккаунт, список и просмотр чатов, новый вопрос, SSE, источники, feedback, Telegram theme/safe areas.

Не входит: регистрация из Telegram, вложения, админка, платежи, push-уведомления, attachment menu, отдельная база пользователей.

## Развёртывание

1. Опубликовать приложение по HTTPS.
2. Задать `TELEGRAM_WEBAPP_ENABLED=true`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_WEBAPP_URL`, `TELEGRAM_BOT_TOKEN`.
3. В BotFather выбрать Bot Settings → Configure Mini App / Menu Button и указать публичный URL `/telegram-app`.
4. Проверить запуск, привязку `/start <код>`, загрузку истории, новый вопрос и источники на Android/iOS Telegram.

## Следующий релиз

Вложения к вопросам, остановка генерации через Telegram MainButton, deep links на конкретный чат, offline cache и staging smoke-test с тестовым ботом.
