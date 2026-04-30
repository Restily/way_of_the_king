"""In-process Prometheus-ready metric counters (W6-052).

Thread-safe dict-based counters. No external dependency — W7 может
поменять на ``prometheus_client`` без изменения call-sites.

Usage::

    from wotk.core.metrics import inc
    inc('dungeon_completed_total', dungeon_id='crypt_normal', difficulty='0')

:func:`export_prometheus` возвращает Prometheus exposition format для
``GET /metrics`` endpoint.
"""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Final

_COUNTERS: dict[tuple[str, frozenset[tuple[str, str]]], int] = defaultdict(int)
_LOCK: Final[Lock] = Lock()


def inc(name: str, **labels: str) -> None:
    """Атомарно инкрементировать named counter с произвольными labels.

    Thread-safe: использует ``threading.Lock``.

    :param name: Имя метрики (snake_case, без ``{``).
    :param labels: Произвольные label=value пары.
    """
    key = (name, frozenset(labels.items()))
    with _LOCK:
        _COUNTERS[key] += 1


def reset_all() -> None:
    """Очистить все счётчики (для тестов).

    :note: Не вызывать в production-коде.
    """
    with _LOCK:
        _COUNTERS.clear()


def export_prometheus() -> str:
    """Вернуть Prometheus exposition format со всеми накопленными counters.

    Формат:

    .. code-block:: text

        # TYPE dungeon_completed_total counter
        dungeon_completed_total{difficulty="0",dungeon_id="crypt_normal"} 3

    :returns: Строка в Prometheus text format (version 0.0.4), заканчивается ``\\n``.
    """
    lines: list[str] = []
    by_metric: dict[str, list[tuple[frozenset[tuple[str, str]], int]]] = defaultdict(list)

    with _LOCK:
        snapshot = dict(_COUNTERS)

    for (name, labels), value in snapshot.items():
        by_metric[name].append((labels, value))

    for name, entries in sorted(by_metric.items()):
        lines.append(f"# TYPE {name} counter")
        for labels, value in entries:
            if labels:
                label_str = ",".join(
                    f'{k}="{v}"' for k, v in sorted(labels)
                )
                lines.append(f"{name}{{{label_str}}} {value}")
            else:
                lines.append(f"{name} {value}")

    return "\n".join(lines) + "\n"
