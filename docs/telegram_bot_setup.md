# Настройка Telegram-бота wiki_4

Интеграция использует официальный Bot API Telegram: polling-worker сам забирает обновления (`getUpdates`) и отвечает через `sendMessage` / `editMessageText`. Публичный HTTPS-адрес не требуется.

## 1. Получение токена у @BotFather

1. Откройте Telegram и найдите контакт `@BotFather`.
2. Отправьте команду `/newbot`.
3. Укажите имя бота и уникальный username (должен заканчиваться на `Bot`, например `WikiQA_Bot`).
4. Скопируйте токен вида:

```text
123456789:ABCdefGHIjklMNOpqrsTUVwxyz
```

## 2. Заполните `.env`

Минимальные значения:

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_INTERNAL_API_URL=http://127.0.0.1:5000
```

Если основной API защищён переменной `API_KEY`, добавьте тот же ключ:

```env
TELEGRAM_INTERNAL_API_KEY=your-api-key
```

Дополнительные настройки (значения по умолчанию):

```env
# Интервал polling (секунды)
TELEGRAM_POLL_INTERVAL_SECONDS=2
# Путь к файлу offset
TELEGRAM_OFFSET_PATH=./data/telegram_update_offset.json
# Время жизни кода привязки (секунды)
TELEGRAM_LINK_CODE_TTL_SECONDS=86400
# Интервал обновления placeholder при стриминге (миллисекунды)
TELEGRAM_STREAM_EDIT_INTERVAL_MS=800
# Максимальная длина сообщения Telegram (legacy/fallback HTML)
TELEGRAM_MAX_MESSAGE_LENGTH=4096
# Rich Messages (Bot API 10.1+): таблицы и GFM в ответах агента
TELEGRAM_RICH_MESSAGES=true
TELEGRAM_RICH_MAX_CHARS=32000
```

## 3. Запустите приложение и worker

В одном терминале запустите Flask-приложение обычным способом:

```powershell
python web_app.py
```

Во втором терминале запустите polling-worker:

```powershell
python scripts/telegram_bot_worker.py
```

Для разовой проверки без постоянного цикла:

```powershell
python scripts/telegram_bot_worker.py --once
```

Worker хранит подтверждённый `offset` в `TELEGRAM_OFFSET_PATH`, по умолчанию `./data/telegram_update_offset.json`.

## 4. Привязка аккаунта пользователем

1. Авторизуйтесь в веб-интерфейсе wiki_4.
2. Перейдите в профиль или раздел настроек Telegram и нажмите **Сгенерировать код**.
3. Скопируйте 6-значный код.
4. Напишите боту: `/start <код>` (например, `/start 123456`).
5. Бот подтвердит привязку: **Аккаунт привязан! Ваш ID: X, роль: user**.

Код действует в течение `TELEGRAM_LINK_CODE_TTL_SECONDS` секунд (по умолчанию 24 часа). Пока код не использован и не истёк, повторный запрос возвращает тот же код (не инвалидирует его).

После успешного `/start <код>` привязка сохраняется в базе. При перезапуске веб-приложения и worker бот восстанавливает её автоматически — повторный `/start` не нужен.

## 5. Доступные команды бота

| Команда | Описание |
|---------|----------|
| `/start <код>` | Привязать аккаунт wiki_4 по коду из веб-интерфейса |
| `/reset` | Сбросить текущий диалог и начать новый чат |
| `/mode <режим>` | Изменить режим ответа (см. [Режимы ответа](#режимы-ответа)) |
| `/history` | Информация о доступности истории чатов |
| `/help` | Список доступных команд |

Если пользователь **не привязан**, любой текст (кроме `/start`) будет проигнорирован с уведомлением:

> Аккаунт не привязан. Отправьте `/start <код>`

## 6. Режимы ответа

Режимы передаются в поле `answer_mode` при запросе к `/api/chat/stream` и влияют на форматирование ответа LLM:

| Режим | Описание |
|-------|----------|
| `обычный` | Стандартный подробный ответ (по умолчанию) |
| `кратко` | Краткий ответ в 1-2 предложения |
| `подробно` | Развёрнутый ответ с примерами |
| `по_источникам` | Ответ структурирован по найденным источникам |
| `по_шагам` | Пошаговая инструкция |
| `инструкция` | Инструкция для сотрудника с чёткими действиями |

## 7. Ограничения

- **Rich Messages (по умолчанию):** ответы агента отправляются через `sendRichMessage` с GFM markdown — таблицы, заголовки, списки, блоки кода и другие элементы Bot API 10.1+. Лимит до ~32000 символов (`TELEGRAM_RICH_MAX_CHARS`, по умолчанию 32000; лимит Bot API — 32768).
- **Стриминг Rich Messages:** во время генерации ответа worker обновляет эфемерный превью через `sendRichMessageDraft` (интервал — `TELEGRAM_STREAM_EDIT_INTERVAL_MS`). Финальный ответ всегда отправляется через `sendRichMessage`.
- **Legacy/fallback:** если `TELEGRAM_RICH_MESSAGES=false` или Rich API возвращает ошибку, используется классический путь: placeholder + `editMessageText` + `sendMessage` с `parse_mode=HTML`. В этом режиме действует лимит `TELEGRAM_MAX_MESSAGE_LENGTH` (4096 символов); длинные ответы обрезаются до разумного разделителя (`\n\n`, `\n`, `. `, ` `) или разбиваются на части «Часть N/M».
- **Rate limit:** при стриминге (draft или `editMessageText`) обновления вызываются с интервалом `TELEGRAM_STREAM_EDIT_INTERVAL_MS` (по умолчанию 800 мс). Если Telegram вернёт HTTP 429, worker читает `retry_after` и повторяет запрос.
- **Форматирование (legacy):** в fallback-пути текст экранируется для `parse_mode=HTML`. Все `<`, `>` и `&` заменяются HTML-сущностями.

## 8. Troubleshooting

### Бот не отвечает

1. Убедитесь, что `TELEGRAM_ENABLED=true` в `.env`.
2. Проверьте, что `TELEGRAM_BOT_TOKEN` задан и совпадает с токеном от @BotFather.
3. Убедитесь, что Flask-приложение доступно по `TELEGRAM_INTERNAL_API_URL`.
4. Проверьте offset-файл (`data/telegram_update_offset.json`): если он содержит слишком старый offset, удалите файл — worker начнёт с самых свежих обновлений.
5. Запустите worker с флагом `--once` и проверьте вывод:

```powershell
python scripts/telegram_bot_worker.py --once
```

### Привязка не работает

- Убедитесь, что код ещё не истёк (TTL — `TELEGRAM_LINK_CODE_TTL_SECONDS` секунд).
- Проверьте, что код вводится ровно 6 цифр после `/start`.
- Сгенерируйте новый код в веб-интерфейсе.

