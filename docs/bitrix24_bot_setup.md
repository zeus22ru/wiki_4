# Настройка чат-бота Битрикс24

Интеграция использует актуальную платформу чат-ботов `imbot.v2` в режиме `fetch`: наша программа сама забирает события из Битрикс24 и отвечает через REST API. Публичный HTTPS-адрес для локального Flask-сервера не нужен.

## 1. Создайте входящий вебхук

В Битрикс24 откройте `Разработчикам` → `Другое` → `Входящий вебхук`.

Выдайте вебхуку права:

- `imbot` — регистрация бота, получение событий и отправка сообщений от имени бота.

Скопируйте URL вида:

```text
https://example.bitrix24.ru/rest/1/xxxxxxxxxxxxxxxx/
```

## 2. Заполните `.env`

Минимальные значения:

```env
BITRIX24_ENABLED=true
BITRIX24_WEBHOOK_URL=https://example.bitrix24.ru/rest/1/xxxxxxxxxxxxxxxx/
BITRIX24_BOT_TOKEN=your-random-secret-token
BITRIX24_INTERNAL_API_URL=http://127.0.0.1:5000
```

Если основной API защищён переменной `API_KEY`, добавьте тот же ключ:

```env
BITRIX24_INTERNAL_API_KEY=your-api-key
```

## 3. Зарегистрируйте бота

Запустите:

```powershell
python scripts/register_bitrix24_bot.py --name "Wiki QA Bot" --work-position "База знаний"
```

Скрипт выведет `BITRIX24_BOT_ID` и `BITRIX24_BOT_TOKEN`. Запишите их в `.env`:

```env
BITRIX24_BOT_ID=456
BITRIX24_BOT_TOKEN=your-random-secret-token
```

Повторный запуск с тем же `--code` вернёт уже существующего бота на стороне Битрикс24.

## 4. Запустите приложение и worker

В одном терминале запустите Flask-приложение обычным способом:

```powershell
python web_app.py
```

Во втором терминале запустите polling-worker:

```powershell
python scripts/bitrix24_bot_worker.py
```

Для разовой проверки без постоянного цикла:

```powershell
python scripts/bitrix24_bot_worker.py --once
```

Worker хранит подтверждённый `nextOffset` в `BITRIX24_EVENT_OFFSET_PATH`, по умолчанию `./data/bitrix24_event_offset.json`.

## 5. Проверьте работу

1. Откройте личный чат с ботом в Битрикс24.
2. Напишите вопрос по базе знаний.
3. Worker получит событие `ONIMBOTV2MESSAGEADD`.
4. Вопрос уйдёт в локальный `POST /api/chat`.
5. Ответ вернётся в тот же диалог через `imbot.v2.Chat.Message.send`.

Если бот не отвечает, сначала проверьте `GET /api/health`, затем логи Flask-приложения и worker.
