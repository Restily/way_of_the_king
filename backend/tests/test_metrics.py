"""Юнит-тесты для wotk.core.metrics (W6-052)."""

from __future__ import annotations

import pytest

import wotk.core.metrics as metrics_mod
from wotk.core.metrics import export_prometheus, inc, reset_all


@pytest.fixture(autouse=True)
def _clean_counters() -> None:
    """Очищаем счётчики до и после каждого теста."""
    reset_all()
    yield
    reset_all()


def test_inc_single_counter() -> None:
    """inc() увеличивает счётчик на 1."""
    inc("my_counter_total")
    inc("my_counter_total")
    output = export_prometheus()
    assert "my_counter_total 2" in output


def test_inc_with_labels() -> None:
    """inc() с labels создаёт отдельные series."""
    inc("dungeon_completed_total", dungeon_id="crypt_normal", difficulty="0")
    inc("dungeon_completed_total", dungeon_id="crypt_normal", difficulty="0")
    inc("dungeon_completed_total", dungeon_id="crypt_hard", difficulty="1")
    output = export_prometheus()
    assert 'dungeon_completed_total{difficulty="0",dungeon_id="crypt_normal"} 2' in output
    assert 'dungeon_completed_total{difficulty="1",dungeon_id="crypt_hard"} 1' in output


def test_export_prometheus_type_header() -> None:
    """export_prometheus() включает # TYPE header для каждой метрики."""
    inc("test_metric_total")
    output = export_prometheus()
    assert "# TYPE test_metric_total counter" in output


def test_export_prometheus_multiple_metrics() -> None:
    """Несколько разных метрик — каждая со своим # TYPE."""
    inc("alpha_total")
    inc("beta_total")
    output = export_prometheus()
    assert "# TYPE alpha_total counter" in output
    assert "# TYPE beta_total counter" in output


def test_export_prometheus_ends_with_newline() -> None:
    """Prometheus exposition format обязан заканчиваться переносом строки."""
    inc("x_total")
    output = export_prometheus()
    assert output.endswith("\n")


def test_export_prometheus_empty() -> None:
    """При нет счётчиков — возвращает только одну пустую строку."""
    output = export_prometheus()
    assert output == "\n"


def test_labels_sorted_in_output() -> None:
    """Labels в Prometheus строке всегда отсортированы по имени."""
    inc("sorted_test", z_label="z", a_label="a")
    output = export_prometheus()
    # a_label должен быть перед z_label.
    assert 'a_label="a",z_label="z"' in output


def test_reset_all_clears_counters() -> None:
    """reset_all() очищает все счётчики."""
    inc("temp_total")
    reset_all()
    output = export_prometheus()
    assert "temp_total" not in output


def test_inc_is_cumulative() -> None:
    """Каждый inc() добавляет 1 к предыдущему значению."""
    for _ in range(5):
        inc("cumulative_total", env="test")
    output = export_prometheus()
    assert 'cumulative_total{env="test"} 5' in output
