# БочкарИИ — handoff для реализации Option D

## Статус

Дизайн утверждён пользователем. Производственный интерфейс ещё не менялся: в проекте есть только кликабельные прототипы. Начинать реализацию следует с тестов и сохранения существующих DOM/API-контрактов.

## Авторитетный визуальный источник

- Основной: [`option-d-diadoc-tile-workspace.html`](option-d-diadoc-tile-workspace.html)
- Дополнительные исследования, не являющиеся альтернативой выбранному дизайну:
  - [`option-e-motion-feedback-workspace.html`](option-e-motion-feedback-workspace.html)
  - [`option-d-diadoc-tile-workspace.html`](option-d-diadoc-tile-workspace.html) содержит интерактивные демонстрационные обработчики; их нельзя переносить в production вместо существующей логики `static/script.js`.

## Неизменяемые продуктовые условия

- Русскоязычный on-prem RAG-ассистент «БочкарИИ».
- Сохраняются: история диалогов, потоковые ответы, цитаты/источники, markdown/Mermaid, feedback, проверка ответа, экспорт, вложения, гостевой/пользовательский/admin доступ, база знаний, переиндексация, admin settings, Telegram и issue-report.
- Нельзя менять API-контракты и удалять production DOM hooks без синхронного изменения `static/script.js` и тестов.

## Выбранная визуальная система

- Фирменная палитра: золото `#A88656`, светлое золото `#D6BC8A`, графит `#212529`, белый `#FFFFFF`.
- Рабочие нейтрали: canvas `#F4F5F6`, line `#DDE1E5`, muted `#68717B`; mint `#D9F2EB` — только для вторичных иконок/действий.
- Базовая композиция: внешний двухколоночный shell `250px | main`; внутри main — `workspace | 294px sources`.
- На desktop источники видимы постоянно. До `980px` они превращаются в доступный drawer; до `620px` sidebar открывается по явной кнопке, а не исчезает без замены.
- Плитки нужны только для пустого состояния и крупных навигационных действий. Ответы, таблицы, списки документов и настройки остаются плотными рабочими поверхностями.
- Единое лёгкое скругление `--radius: 4px` на всех контролах и карточках — без «таблеток» и смешанных радиусов.
- Тёмная тема сохраняется: все добавленные токены обязаны иметь `[data-theme="dark"]` аналоги.

## Старт в новом диалоге

1. Прочитать [`option-d-implementation-plan.md`](option-d-implementation-plan.md) полностью.
2. Сверить текущий код с прототипом и убедиться, что выбран именно Option D.
3. Выполнить первый task по TDD; не начинать с визуального CSS без DOM-contract test.
4. После каждого визуального этапа проверять desktop/mobile и существующие workflows.

## Главные риски

- `static/style.css` содержит конкурирующие legacy и visual-refresh блоки; не добавлять третий слой переопределений.
- `#sourcesPanel` сейчас overlay внутри `#chatPanel`; Option D требует desktop grid column и mobile drawer fallback.
- `static/script.js` жёстко зависит от IDs/classes в `templates/index.html`.
- `clipboard.js` наблюдает `.message-content`; при restyle ответа этот hook обязан остаться.
- Текущие 768px правила sidebar конфликтуют; финальная схема должна использовать согласованные breakpoints `980px` и `620px`.

## Обязательная финальная проверка

```powershell
pytest
node "C:\Users\ZeuS\.agents\skills\impeccable\scripts\detect.mjs" --json templates/index.html static/style.css static/css/theme.css static/css/components.css
```

Затем снять и проверить desktop/mobile screenshots, оформить `DESIGN.md` из фактически построенной системы и только после этого считать работу завершённой.
