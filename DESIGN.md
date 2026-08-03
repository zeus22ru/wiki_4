# БочкарИИ — DESIGN.md (Option D)

Запись фактической визуальной системы после переноса Option D в production UI.

## Назначение

Русскоязычный on-prem RAG-ассистент «БочкарИИ»: плотный рабочий чат, постоянные источники на desktop, компактный sidebar rail. Плитки — только для пустого / нового чата.

## Палитра

| Token | Light | Dark | Role |
|---|---|---|---|
| `--primary-color` | `#A88656` | `#D6BC8A` | CTA, active underline, brand |
| `--on-primary` | `#ffffff` | `#2a2114` | текст на primary |
| `--accent-sand` | `#D6BC8A` | `#A88656` | soft brand fields |
| `--accent-mint` | `#D9F2EB` | `#2a4a40` | secondary tile/icon only |
| `--workspace-canvas` | `#F4F5F6` | `#1a1d21` | фон рабочей области |
| `--text-color` | `#212529` | `#e8eaed` | основной текст |
| `--secondary-text` | `#68717B` | `#9aa3ad` | метаданные |
| `--border-color` | `#DDE1E5` | `#343a42` | линии / рамки |
| `--status-ok` / `--status-down` | `#2f9e68` / `#c94a4a` | `#3cb878` / `#e06b6b` | health |

Единый радиус: `--radius: 4px` (без pills и смешанных 12/18/999).

## Типографика

- UI stack: `"Segoe UI", system-ui, -apple-system, Arial, sans-serif`
- Scale: `--text-xs: 12px` … `--text-2xl: 28px` (читаемый пол ≥12px)

## Компоновка

```text
.app-container          grid 250px | 1fr
├── .workspace-sidebar  brand, новый чат, поиск, список, очистка
└── .main-shell         grid 1fr | 294px
    ├── .chat-container top → underline tabs → panel
    └── #sourcesPanel   desktop column / ≤980px drawer
```

Breakpoints:
- `>=981px` — sidebar + sources column
- `621–980px` — sources drawer (`.open`), sidebar fixed
- `<=620px` — sidebar drawer (`#sidebarToggle`), workspace full width

## Состояния чата

- **Empty / new:** `#emptyTiles` видимы; сообщения очищены; класс `.is-empty` на `.chat-container`
- **Populated:** плитки `hidden`; ответы — светлые панели (white + line), user — нейтральный правый блок
- Плитки маршрутизируют: focus input / sources / `openChat(last)` / `switchPanel('documentsPanel')` (admin)

## Компоненты

- Tabs: underline, не chip
- Active chat item: full-field fill/border
- Send: «Отправить» + `aria-label`, primary gold
- Sources: compact cards; `.source-item--active` меняет карточку целиком
- Documents / admin: плотные списки и формы, без homepage-tiles

## Файлы

- `static/css/theme.css` — токены light/dark
- `static/style.css` — shell / chat / sources / tiles / responsive (Option D block в конце)
- `static/css/components.css` — controls
- `templates/index.html` — DOM shell
- `static/script.js` — empty tiles, drawer Escape/focus, health `data-state`

## Проверка

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_frontend_contract.py -q
node "C:\Users\ZeuS\.agents\skills\impeccable\scripts\detect.mjs" --json templates/index.html static/style.css static/css/theme.css static/css/components.css
```

Открыть приложение в браузере, переключить тему (`#themeToggle`), проверить empty tiles → диалог → источники на desktop.
