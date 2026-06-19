# GitHub Issues: обратная связь из БочкарИИ

Краткая инструкция: как устроена отправка issue, что настроить и как проверить, что всё работает.

---

## Зачем это нужно

Гость или пользователь **без GitHub-аккаунта** может сообщить о проблеме прямо из интерфейса БочкарИИ. Приложение создаёт issue в GitHub **от имени сервисного бот-аккаунта** через токен на сервере.

Пользователь **не видит** токен и **не логинится** в GitHub.

---

## Как это работает

```
Гость → кнопка в UI → POST /api/issues (Flask)
                              ↓
                    GitHub REST API + GITHUB_TOKEN из .env
                              ↓
                    Issue в репозитории (например chatbz/wiki-feedback)
```

| Режим | Когда | Что происходит |
|-------|--------|----------------|
| **Демо (заглушка)** | Нет `GITHUB_TOKEN` или `GITHUB_REPO` | Issue «создаётся» локально, номер фейковый, в GitHub ничего не попадает |
| **Боевой** | Токен и репо заданы, доступ есть | Issue реально появляется на GitHub |

---

## Где в интерфейсе

| Место | Действие |
|-------|----------|
| Шапка, иконка ⚠ | Общая проблема (UI, идея, баг) |
| Под ответом бота — «Сообщить об ошибке» | Issue с контекстом диалога (вопрос, ответ, источники) |

После успешной отправки — toast «Issue #N создан» (или «принято (демо)» в заглушке).

---

## Что нужно на GitHub (один раз)

### 1. Отдельный аккаунт

Создайте аккаунт только для репортов, например `chatbz`. **Логин и пароль в приложение не кладутся** — только токен.

### 2. Репозиторий для issues

Пример: [github.com/chatbz/wiki-feedback](https://github.com/chatbz/wiki-feedback)

- Можно **отдельный** репо (`wiki-feedback`) — рекомендуется.
- Можно issues в репо с кодом — не обязательно.

Запишите путь: `owner/repo` → `chatbz/wiki-feedback`.

### 3. Personal Access Token (PAT)

**Fine-grained token** (предпочтительно):

1. Войти в **бот-аккаунт**.
2. Аватар → **Settings** (настройки **аккаунта**, не репозитория).
3. Внизу слева → **Developer settings**.
4. **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
5. Настройки:
   - **Repository access** → **Only select repositories** → выбрать `wiki-feedback`
   - **Permissions** → **Issues** → **Read and write**
6. Сгенерировать и **скопировать токен** (`github_pat_...`). Показывается один раз.

Прямые ссылки (нужен вход в бот-аккаунт):

- [Создать fine-grained token](https://github.com/settings/personal-access-tokens/new)
- [Список токенов](https://github.com/settings/personal-access-tokens)

**Classic token** (запасной вариант): [github.com/settings/tokens/new](https://github.com/settings/tokens/new) → scope `repo` или `public_repo`.

### 4. Метка (необязательно)

В репозитории: **Issues** → **Labels** → создать `user-report`.  
Если метки нет, GitHub может вернуть 422 — тогда уберите labels из `.env` или создайте метку.

---

## Настройка `.env`

В корне проекта (`wiki_4/.env`):

```env
GITHUB_ISSUES_ENABLED=true
GITHUB_TOKEN=github_pat_ВАШ_ТОКЕН
GITHUB_REPO=chatbz/wiki-feedback
GITHUB_ISSUE_LABELS=user-report
GITHUB_ISSUES_RATE_LIMIT_PER_HOUR=3
```

| Переменная | Описание |
|------------|----------|
| `GITHUB_ISSUES_ENABLED` | `true` — включить отправку |
| `GITHUB_TOKEN` | PAT бот-аккаунта (**только на сервере**, не в git) |
| `GITHUB_REPO` | `owner/repo` |
| `GITHUB_ISSUE_LABELS` | Метки через запятую (с сервера, пользователь не задаёт) |
| `GITHUB_ISSUES_RATE_LIMIT_PER_HOUR` | Лимит на IP + guest_id (по умолчанию 3) |

После изменений **перезапустите** Flask-приложение.

---

## Проверка

### 1. Статус API

Откройте в браузере:

```
http://localhost:5000/api/issues/status
```

| Поле | Ожидание (боевой режим) |
|------|-------------------------|
| `enabled` | `true` |
| `configured` | `true` |
| `stub` | `false` |
| `repo` | `chatbz/wiki-feedback` |

Если `stub: true` — токен или репо не подхватились (пустой `.env`, не перезапустили сервер).

### 2. Интерфейс

1. Открыть БочкарИИ (можно как гость).
2. Нажать ⚠ или «Сообщить об ошибке».
3. Заполнить форму → **Отправить**.
4. Проверить [Issues в репозитории](https://github.com/chatbz/wiki-feedback/issues).

### 3. Быстрая проверка из терминала (без вывода токена)

```powershell
cd c:\xampp\htdocs\wiki_4
python -c "from config.settings import settings; from integrations.github_issues import github_issues_configured; print('repo:', settings.GITHUB_REPO); print('configured:', github_issues_configured(settings.GITHUB_TOKEN, settings.GITHUB_REPO))"
```

---

## Частые проблемы

### `404 Not Found` при отправке

Репозиторий есть в браузере, но API отвечает 404.

**Причины:**

1. Репозиторий **не создан** или опечатка в `GITHUB_REPO`.
2. Fine-grained token **не включает** этот репо (создали репо **после** выпуска токена).
3. Репозиторий **private**, а токен без доступа к нему.

**Что сделать:**

- Проверить URL: `https://github.com/chatbz/wiki-feedback` открывается.
- **Edit token** → **Only select repositories** → добавить `wiki-feedback`.
- **Issues: Read and write** → Save.
- Перезапустить приложение.

### `422 Validation Failed` (labels)

Создайте метку `user-report` в репо или очистите/измените `GITHUB_ISSUE_LABELS`.

### `401 Bad credentials`

Токен неверный, истёк или скопирован не полностью. Создайте новый PAT.

### Всё ещё «демо-режим» в UI

- Пустой `GITHUB_TOKEN` или `GITHUB_REPO` в `.env`.
- Сервер не перезапускали после правок `.env`.

### `429 Слишком много обращений`

Сработал rate limit (по умолчанию 3 issue/час на IP + guest). Подождите или увеличьте `GITHUB_ISSUES_RATE_LIMIT_PER_HOUR`.

### Ошибка после отправки, хотя репо «есть»

Чеклист:

- [ ] Репо создан на **том же аккаунте**, что и токен (`chatbz`)
- [ ] `GITHUB_REPO=chatbz/wiki-feedback` без лишних пробелов
- [ ] Токен привязан к репо `wiki-feedback`
- [ ] Приложение перезапущено
- [ ] `/api/issues/status` → `"stub": false`

---

## Безопасность

- **Не коммитьте** `.env` и **не отправляйте** токен в чат, почту, скриншоты.
- Токен только на сервере; браузер пользователя его не получает.
- Если токен утёк → **Revoke** на GitHub → создать новый.
- Fine-grained PAT — доступ **только к одному** репозиторию.

---

## Файлы в проекте

| Файл | Назначение |
|------|------------|
| `integrations/github_issues.py` | Вызов GitHub API / заглушка |
| `api/routes/issues.py` | `GET /api/issues/status`, `POST /api/issues` |
| `utils/issue_rate_limit.py` | Rate limit |
| `config/settings.py` | Переменные `GITHUB_*` |
| `templates/index.html` | Кнопка и модалка |
| `static/script.js` | Логика формы |
| `tests/test_issues.py` | Автотесты |

Маршрут `/api/issues` **не требует** `API_KEY` — доступен гостям из браузера (как `/api/auth`).

---

## Типы issue в форме

| ID | Название |
|----|----------|
| `bug` | Ошибка в интерфейсе |
| `wrong_answer` | Неверный ответ |
| `missing_info` | Нет информации в базе |
| `idea` | Идея / улучшение |
| `other` | Другое |

---

## Текущая конфигурация (пример)

Для проекта БочкарИИ:

- **GitHub-аккаунт:** `chatbz`
- **Репозиторий:** `chatbz/wiki-feedback`
- **URL issues:** https://github.com/chatbz/wiki-feedback/issues

После настройки токена и репозитория issue из интерфейса должны появляться там автоматически.
