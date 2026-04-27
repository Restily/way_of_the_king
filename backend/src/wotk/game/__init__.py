"""Pure-function игровая логика — без I/O, без зависимостей от FastAPI/SQLAlchemy.

Эти модули могут выполняться где угодно: на сервере, в worker pool,
в тестах. Серверная логика боя, формулы статов, дроп-таблицы.

* :mod:`wotk.game.energy` — lazy regen энергии.
* :mod:`wotk.game.leveling` — XP-кривая, level up.
* :mod:`wotk.game.stats` — расчёт производных статов.
"""
