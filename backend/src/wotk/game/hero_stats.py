"""Hero combat stats c учётом equipped items + affix snapshot.

Объединяет :func:`wotk.game.stats.compute_derived_stats` с парсингом
``item.affixes`` snapshot и aggregation бонусов от equipped items.

Pure-функция: принимает hero + list[equipped Item-snapshots], возвращает
:class:`DerivedStats` для combat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wotk.domain.enums import EquipmentSlot
from wotk.game.stats import (
    BaseStats,
    DerivedStats,
    StatBonuses,
    WeaponDmg,
    compute_derived_stats,
)


@dataclass(frozen=True, slots=True)
class EquippedItemSnapshot:
    """Срез item'а для stats agg.

    :ivar slot: EquipmentSlot.value.
    :ivar base_stats: ``item_base.base_stats`` JSONB (open shape).
    :ivar affixes: ``item.affixes`` snapshot list ``[{id, value, t, vmin, vmax, mod_type?}]``.
        ``mod_type`` опционален — если отсутствует, требуется affix_def lookup
        (caller обязан populate this поле перед передачей сюда).
    """

    slot: int
    base_stats: dict[str, Any]
    affixes: list[dict[str, Any]]


def _apply_affix_to_bonuses(
    affix: dict[str, Any], bonuses_acc: dict[str, float]
) -> None:
    """Apply один affix snapshot к accumulator dict.

    Поддерживаемые mod_type:
    * flat_str/dex/int — добавляется к base_stats accumulator (str/dex/int)
    * flat_hp / flat_mana — атомарный bonus
    * flat_atk / flat_phys_dmg — bonus.atk
    * pct_atk — bonus.atk *= (1 + pct/100) — отложенно (см. final pass)
    * pct_def — bonus.def_ *= (1 + pct/100)
    * pct_crit — bonus.crit_chance += value
    * pct_resist_fire/cold/lightning — bonus.resist_*
    """
    mod_type = affix.get("mod_type")
    value = affix.get("value", 0)
    if mod_type is None:
        return  # snapshot без mod_type — caller должен populate

    if mod_type == "flat_str":
        bonuses_acc["str"] = bonuses_acc.get("str", 0) + value
    elif mod_type == "flat_dex":
        bonuses_acc["dex"] = bonuses_acc.get("dex", 0) + value
    elif mod_type == "flat_int":
        bonuses_acc["int"] = bonuses_acc.get("int", 0) + value
    elif mod_type == "flat_hp":
        bonuses_acc["hp"] = bonuses_acc.get("hp", 0) + value
    elif mod_type == "flat_mana":
        bonuses_acc["mana"] = bonuses_acc.get("mana", 0) + value
    elif mod_type in ("flat_atk", "flat_phys_dmg"):
        bonuses_acc["atk"] = bonuses_acc.get("atk", 0) + value
    elif mod_type == "pct_atk":
        bonuses_acc["pct_atk"] = bonuses_acc.get("pct_atk", 0) + value
    elif mod_type == "pct_def":
        bonuses_acc["pct_def"] = bonuses_acc.get("pct_def", 0) + value
    elif mod_type == "pct_crit":
        bonuses_acc["crit_chance"] = bonuses_acc.get("crit_chance", 0) + value
    elif mod_type == "pct_resist_fire":
        bonuses_acc["resist_fire"] = bonuses_acc.get("resist_fire", 0) + value
    elif mod_type == "pct_resist_cold":
        bonuses_acc["resist_cold"] = bonuses_acc.get("resist_cold", 0) + value
    elif mod_type == "pct_resist_lightning":
        bonuses_acc["resist_lightning"] = (
            bonuses_acc.get("resist_lightning", 0) + value
        )


def compute_hero_combat_stats(
    *,
    base_stats: BaseStats,
    level: int,
    equipped: list[EquippedItemSnapshot],
) -> DerivedStats:
    """Финальные combat stats hero с учётом equipped items + affix snapshot.

    Порядок применения:
    1. Aggregate flat bonuses (str/dex/int от affixes + base_stats от item_base)
    2. base_stats hero += flat str/dex/int от affixes
    3. compute_derived_stats(base_stats, level, weapon_dmg, bonuses)
    4. Применить pct_atk / pct_def на финальный atk/def

    :param base_stats: hero.base_stats (str/dex/int).
    :param level: hero.level.
    :param equipped: list of :class:`EquippedItemSnapshot`.
    :returns: :class:`DerivedStats` для combat.
    """
    acc: dict[str, float] = {}
    weapon_min = 0
    weapon_max = 0

    for item in equipped:
        # base_stats armor → def + hp_bonus; weapon → min/max dmg
        bs = item.base_stats
        if "def" in bs:
            acc["def_"] = acc.get("def_", 0) + bs["def"]
        if "hp_bonus" in bs:
            acc["hp"] = acc.get("hp", 0) + bs["hp_bonus"]
        if item.slot == EquipmentSlot.WEAPON.value:
            weapon_min = bs.get("min_dmg", 0)
            weapon_max = bs.get("max_dmg", 0)

        for affix in item.affixes:
            _apply_affix_to_bonuses(affix, acc)

    # Append flat str/dex/int bonuses к hero base_stats.
    # (Это меняет downstream формулы в compute_derived_stats — HP/Mana/etc.)
    final_base: BaseStats = {
        "str": base_stats["str"] + int(acc.get("str", 0)),
        "dex": base_stats["dex"] + int(acc.get("dex", 0)),
        "int": base_stats["int"] + int(acc.get("int", 0)),
    }

    bonuses = StatBonuses(
        hp=int(acc.get("hp", 0)),
        mana=int(acc.get("mana", 0)),
        atk=int(acc.get("atk", 0)),
        def_=int(acc.get("def_", 0)),
        crit_chance=float(acc.get("crit_chance", 0)),
        resist_fire=int(acc.get("resist_fire", 0)),
        resist_cold=int(acc.get("resist_cold", 0)),
        resist_lightning=int(acc.get("resist_lightning", 0)),
    )

    armor_value = int(acc.get("def_", 0))
    derived = compute_derived_stats(
        base_stats=final_base,
        level=level,
        weapon=WeaponDmg(min_dmg=weapon_min, max_dmg=weapon_max),
        armor_value=armor_value,
        bonuses=bonuses,
    )

    # Pct multipliers — apply AFTER baseline derivation.
    pct_atk = acc.get("pct_atk", 0)
    pct_def = acc.get("pct_def", 0)
    if pct_atk or pct_def:
        # DerivedStats frozen → создаём новый
        from dataclasses import replace

        derived = replace(
            derived,
            atk=int(derived.atk * (1.0 + pct_atk / 100.0)),
            def_=int(derived.def_ * (1.0 + pct_def / 100.0)),
        )

    return derived


__all__ = ["EquippedItemSnapshot", "compute_hero_combat_stats"]
