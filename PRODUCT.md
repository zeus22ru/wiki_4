# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: сотрудники технической группы сопровождения (техподдержка) во время работы по тикету — нужен быстрый, проверяемый ответ из корпоративной базы знаний, а не общий чат с ИИ.

Other: гости (чат без регистрации), зарегистрированные пользователи (история, feedback, Telegram), администраторы (база знаний, индексация, настройки/диагностика). Внешние каналы: Bitrix24 и Telegram поверх того же RAG API.

## Product Purpose

БочкарИИ — локальный RAG-ассистент по корпоративной базе знаний. Даёт ответы с цитатами и источниками из индексированных документов, чтобы сопровождение не искало одно и то же по wiki, чатам и файлам.

Success: сотрудник за минуты получает ответ, который можно проверить по источникам, и продолжает работу по тикету.

## Positioning

Не открытый чатбот и не browse-only wiki: grounded answers из локального корпуса (часто XWiki + загрузки) с citations, hybrid search, режимами ответа под ops-работу, admin reindex loop и on-prem LLM (Ollama / LM Studio).

## Operating Context

Одностраничное рабочее приложение: сайдбар чатов + workspace ответов + панель источников; админ-вкладки «База знаний» и «Админка»; модалки auth, issue report, Telegram link. Используется за рабочим столом во время сопровождения, часто параллельно с тикетной системой.

## Capabilities and Constraints

Confirmed: multi-chat, streaming answers, стили ответа, вложения, sources/citations, feedback, Markdown export; admin upload/reindex/preview; overview/settings; guest/user/admin roles; Bitrix/Telegram workers.

Redesign constraints (confirmed): сохранить имя «БочкарИИ», русскоязычный UI, on-prem/локальный LLM positioning, текущий набор функций (чат, источники, админка документов и настроек). Объём редизайна: весь рабочий интерфейс (чат + сайдбар + админка).

## Brand Commitments

Product name: БочкарИИ. Voice/UI language: Russian. Visual identity is not locked for redesign — incumbent warm brown/cream in code is evidence only, not a binding brand commitment for a replacement world.

## Evidence on Hand

- `README.md`, `docs/user_guide.md`, `docs/presentation/`
- Pitch: `outputs/wiki4-tech-support-pitch.pptx`
- Screenshots: `docs/images/`, `outputs/presentation_screenshots/`
- Incumbent UI: `templates/index.html`, `static/css/theme.css`, `static/style.css`
- Do not fabricate customers, benchmarks, or pricing.

## Product Principles

1. Ответ должен быть проверяемым: источники и цитаты — часть продукта, не украшение.
2. Скорость во время тикета важнее демонстрации «умности» модели.
3. Локальность и управляемость (on-prem, админ-контроль базы) — часть обещания.
4. Один рабочий контур: чат, источники и админка базы должны читаться как одна система.
5. Не подменять корпоративную правду общим шаблонным AI-chrome.
