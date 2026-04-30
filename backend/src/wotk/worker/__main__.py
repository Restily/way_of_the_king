"""``python -m wotk.worker`` entrypoint — запуск Arq worker'а.

Эквивалентно ``arq wotk.worker.main.WorkerSettings``, но даёт удобный
unified-CLI с другими модулями (``python -m wotk.bot``, etc.).
"""

from __future__ import annotations

from arq.worker import run_worker

from wotk.worker.main import WorkerSettings


def main() -> None:
    """Synchronous entrypoint, делегирует в Arq run_worker."""
    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
