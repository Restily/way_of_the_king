# CLAUDE.md — оркестрация моделей в WOTK

Этот проект использует **трёхуровневое model-routing** через subagent-делегирование. Главный агент (Opus) автоматически роутит работу в зависимости от типа задачи. Это снижает токен-cost и время отклика без потери качества.

## Routing rules

**Главный агент = Opus 4.7** — оставайся им для:
- Архитектурных решений (новые модули, границы абстракций)
- Code review (`/simplify`, `/security-review`)
- Дебага нетривиальных багов с cross-module эффектами
- Принятия trade-off'ов (когда нужно выбрать между подходами)
- Финального summary'я и общения с пользователем

**Делегируй в `implementer` (Sonnet 4.6)** через `Agent(subagent_type='implementer')` для:
- Имплементации тикетов из `docs/WEEK-X-PLAN.md` / `WEEK-X-TICKETS.md` где архитектура уже описана
- Добавления новой SQLAlchemy модели по образцу существующих
- Написания нового FastAPI endpoint'а в стиле `api/v1/`
- Расширения тестов в `test_*.py` под существующий паттерн
- Pixi-компонентов в стиле `Player.ts` / `scene.ts`
- React-экранов в стиле существующих `screens/`
- Любой задачи где архитектура решена и работа = механический translation плана в код

**Делегируй в `quick-fix` (Haiku 4.5)** через `Agent(subagent_type='quick-fix')` для:
- Переименования символа в нескольких файлах
- Добавления i18n ключа в ru.json + en.json
- Исправления опечатки
- Bump константы
- Добавления missing import / удаления dead import
- Обновления одной строки docstring
- Свопа method call на уже extracted helper

## Когда НЕ делегировать (оставайся Opus'ом)

- Задача требует **чтения >5 файлов** для понимания контекста
- Решение **меняет shape долгосрочной архитектуры**
- Security-sensitive (auth, crypto, secrets)
- DB schema changes affecting multiple modules
- Когда нужно **сравнить два подхода** и выбрать
- Финальная проверка / итоговый summary пользователю
- Любая работа с памятью пользователя (`~/.claude/projects/.../memory/`)

## Параллельность

Когда возможно — отправляй несколько subagent-вызовов **в одном сообщении** (multi-tool-call в одном assistant turn). Пример: `implementer` пишет 3 endpoint'а независимо → 3 параллельных Agent-вызова.

## Контракт subagent'а

`implementer` и `quick-fix` обязаны **escalate back** если:
- Сталкиваются с архитектурным решением
- Нужно изменить convention
- Тесты падают непонятно почему
- Spec contradicts существующему коду

В таком случае Opus принимает решение, потом снова делегирует.

## Cost / latency expectations

- **Opus 4.7**: главный туда-сюда + ~5-10% объёма кода (только архитектурные/security куски)
- **Sonnet 4.6**: ~70-80% объёма кода (рутинная имплементация по плану)
- **Haiku 4.5**: ~10-15% (тривиальные правки)

Это даёт примерно 3-4x экономию токенов vs "всё на Opus" при той же quality для известных паттернов.

---

## Project conventions (для всех моделей)

- **Gold = integer 1:1** (без sub-units)
- **Docstrings reST** на каждой Python функции/классе/модуле (user-feedback memory)
- **Migrations вручную** (не autogenerate)
- **i18n ключ всегда в обоих ru.json + en.json**
- **Tests**: `_helpers.setup_user_with_funds` + `sign_internal_body` вместо inline-копий
- **Локально-доступные тикеты**: см. [docs/PENDING-W1-W4.md](docs/PENDING-W1-W4.md) — что заблокировано, что открыто
- **Что строится сейчас**: см. [docs/WEEK-5-PLAN.md](docs/WEEK-5-PLAN.md)
