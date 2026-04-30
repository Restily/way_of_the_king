"""Loot/XP/Gold drops при kill моба.

on_mob_killed — pure-функция. Не пишет в БД (caller использует
loot_db.materialize_item для items + apply_xp для xp + balance update для gold).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from wotk.game.loot import (
    AffixDefinition as LootAffixDefinition,
)
from wotk.game.loot import (
    GeneratedItem,
    Rarity,
    generate_item,
    roll_quality_pct,
)
from wotk.game.mobs import MobDef


@dataclass(frozen=True, slots=True)
class KillRewards:
    """Награды за kill одного моба.

    :ivar xp_gained: XP для apply_xp.
    :ivar gold_gained: Gold (в "копейках") для balance.gold +=.
    :ivar items: Сгенерированные предметы. Caller материализует через
        :func:`wotk.game.loot_db.materialize_item`.
    """

    xp_gained: int
    gold_gained: int
    items: tuple[GeneratedItem, ...]


# Default rarity weights — placeholder; в W5 переедут в dungeon.config.
DEFAULT_RARITY_WEIGHTS: dict[Rarity, int] = {
    Rarity.COMMON: 60,
    Rarity.MAGIC: 25,
    Rarity.RARE: 12,
    Rarity.EPIC: 2,
    Rarity.LEGENDARY: 1,
}

#: Базовая вероятность что моб дропнет item (placeholder).
BASE_DROP_CHANCE = 0.35


def _roll_rarity(rng: random.Random, weights: dict[Rarity, int]) -> Rarity:
    """Weighted random pick из rarity weights."""
    total = sum(weights.values())
    pick = rng.randint(1, total)
    cum = 0
    for r, w in weights.items():
        cum += w
        if pick <= cum:
            return r
    return Rarity.COMMON


def on_mob_killed(
    rng: random.Random,
    *,
    mob_def: MobDef,
    killer_hero_level: int,
    affix_pool: tuple[LootAffixDefinition, ...],
    base_id: int,
    base_slot: int,
    base_tags: list[str] | None = None,
    drop_chance: float = BASE_DROP_CHANCE,
    rarity_weights: dict[Rarity, int] | None = None,
    boss_multiplier: float = 1.0,
) -> KillRewards:
    """Вычислить награды от kill моба.

    Loot drop определяется ``rng.random() < drop_chance`` — не каждый kill
    даёт item. XP и gold всегда даются.

    W6-013: когда ``mob_def.is_boss`` (или явно задан ``boss_multiplier > 1``):

    * ``drop_chance`` форсируется в 1.0 (100% drop).
    * Rarity форсируется в ``max(rolled, Rarity.RARE)`` — гарантирован rare+.
    * ``gold_gained`` и ``xp_gained`` множатся на ``boss_multiplier`` (2.0).

    :param rng: RNG (caller владеет seed'ом).
    :param mob_def: Убитый mob.
    :param killer_hero_level: Уровень hero для ilvl расчёта.
    :param affix_pool: Pool аффиксов (см. loot_db.load_affix_pool).
    :param base_id: ID base item для drop (caller выбрал из dungeon loot table).
    :param base_slot: Slot value для filter аффиксов.
    :param base_tags: Tags для spawn_weights override (PoE-style).
    :param drop_chance: Вероятность что вообще что-то дропнет.
    :param rarity_weights: Override default rarity distribution.
    :param boss_multiplier: Множитель gold/xp для босса (2.0 для crypt_lich).
    :returns: :class:`KillRewards`.
    """
    is_boss = mob_def.is_boss
    weights = rarity_weights or DEFAULT_RARITY_WEIGHTS
    items: list[GeneratedItem] = []

    # W6-013: боссы всегда дропают, гарантирован rare+
    effective_drop_chance = 1.0 if is_boss else drop_chance

    if rng.random() < effective_drop_chance:
        rarity = _roll_rarity(rng, weights)
        if is_boss:
            rarity = max(rarity, Rarity.RARE)
        item = generate_item(
            rng,
            base_id=base_id,
            slot=base_slot,
            ilvl=killer_hero_level,
            rarity=rarity,
            base_tags=base_tags or [],
            affix_pool=affix_pool,
        )
        items.append(item)

    gold_gained = rng.randint(mob_def.gold_drop_min, mob_def.gold_drop_max)
    xp_gained = mob_def.xp_drop

    # W6-013: apply boss_multiplier to gold and xp
    if boss_multiplier != 1.0:
        gold_gained = int(gold_gained * boss_multiplier)
        xp_gained = int(xp_gained * boss_multiplier)

    return KillRewards(
        xp_gained=xp_gained,
        gold_gained=gold_gained,
        items=tuple(items),
    )


# Suppress unused
_ = roll_quality_pct

__all__ = [
    "BASE_DROP_CHANCE",
    "DEFAULT_RARITY_WEIGHTS",
    "KillRewards",
    "on_mob_killed",
]
