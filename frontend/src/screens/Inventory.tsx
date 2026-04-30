/**
 * Inventory screen — grid 6×8 + equipped slots panel.
 *
 * UX (W5-051):
 *   - long-press (500ms) / right-click → LongPressMenu с Equip/Unequip/Compare/Cancel
 *   - Compare (W5-052) → CompareTooltip side-by-side vs equipped item того же slot'а
 *   - Tap-once → выбрать item (показать tooltip), как раньше
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  type ItemDTO,
  equipItem,
  getInventory,
  unequipItem,
} from '../api/inventory';
import { CompareTooltip } from '../components/CompareTooltip';
import {
  LongPressMenuOverlay,
  type LongPressMenuState,
  useLongPress,
} from '../components/LongPressMenu';

const INVENTORY_COLS = 6;
const INVENTORY_ROWS = 8;
const INVENTORY_CAP = INVENTORY_COLS * INVENTORY_ROWS;

const SLOT_NAMES = ['HELMET', 'CHEST', 'WEAPON', 'OFFHAND', 'BOOTS', 'RING'];
const RARITY_NAMES = ['common', 'magic', 'rare', 'epic', 'legendary'];

export interface InventoryProps {
  onExit: () => void;
}

export function Inventory({ onExit }: InventoryProps) {
  const { t } = useTranslation();
  const [items, setItems] = useState<ItemDTO[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  // W5-051: состояние long-press меню.
  const [menuState, setMenuState] = useState<LongPressMenuState | null>(null);
  // W5-052: id item'а открытого в compare mode.
  const [compareId, setCompareId] = useState<number | null>(null);

  const refresh = async () => {
    try {
      setError(null);
      const r = await getInventory();
      setItems(r.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'fetch_failed');
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const handleItemClick = async (item: ItemDTO) => {
    if (busy !== null) return;
    if (selectedId !== item.id) {
      setSelectedId(item.id);
      return;
    }
    setBusy(item.id);
    try {
      if (item.equipped_on !== null) {
        await unequipItem(item.id);
      } else {
        await equipItem(item.id, item.base_slot);
      }
      await refresh();
      setSelectedId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'action_failed');
    } finally {
      setBusy(null);
    }
  };

  /** Обработчик выбора действия в long-press меню (W5-051). */
  const handleMenuAction = async (
    action: 'equip' | 'unequip' | 'compare' | 'cancel',
    itemId: number,
  ) => {
    setMenuState(null);
    if (action === 'cancel') return;
    if (action === 'compare') {
      setCompareId(itemId);
      return;
    }
    if (busy !== null || !items) return;
    const item = items.find((it) => it.id === itemId);
    if (!item) return;
    setBusy(itemId);
    try {
      if (action === 'unequip') {
        await unequipItem(itemId);
      } else {
        await equipItem(itemId, item.base_slot);
      }
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'action_failed');
    } finally {
      setBusy(null);
    }
  };

  if (items === null) {
    return (
      <div className="screen screen--centered">
        <p>{t('welcome.loading')}</p>
      </div>
    );
  }

  const { equippedBySlot, inventoryByPos } = useMemo(() => {
    const eq: Record<number, ItemDTO> = {};
    const inv: Record<number, ItemDTO> = {};
    for (const it of items) {
      if (it.equipped_on !== null && it.equipped_slot !== null) {
        eq[it.equipped_slot] = it;
      } else if (it.inventory_position !== null) {
        inv[it.inventory_position] = it;
      }
    }
    return { equippedBySlot: eq, inventoryByPos: inv };
  }, [items]);

  const selected = useMemo(
    () =>
      selectedId !== null
        ? items.find((it) => it.id === selectedId) ?? null
        : null,
    [items, selectedId],
  );

  // W5-052: item для compare.
  const compareItem = useMemo(
    () => (compareId !== null ? items.find((it) => it.id === compareId) ?? null : null),
    [items, compareId],
  );

  // W5-052: найти equipped item того же slot'а для сравнения.
  const compareEquipped = useMemo(() => {
    if (!compareItem) return null;
    return equippedBySlot[compareItem.base_slot] ?? null;
  }, [compareItem, equippedBySlot]);

  return (
    <div className="screen inventory">
      <header className="screen__header inventory__header">
        <button type="button" className="inventory__back" onClick={onExit}>
          {t('inventory.back')}
        </button>
        <h1 className="inventory__title">{t('inventory.title')}</h1>
      </header>

      {error && <p className="error">{error}</p>}

      {/* Equipped slots */}
      <section className="equipped">
        <h2 className="equipped__title">{t('inventory.equipped')}</h2>
        <div className="equipped__grid">
          {SLOT_NAMES.map((name, slotIdx) => {
            const item = equippedBySlot[slotIdx];
            const isSelected = item != null && item.id === selectedId;
            return (
              <ItemCell
                key={name}
                item={item ?? null}
                isSelected={isSelected}
                busy={busy}
                label={t(`inventory.slot.${name.toLowerCase()}`)}
                onClick={() => item && void handleItemClick(item)}
                onLongPress={() =>
                  item &&
                  setMenuState({ itemId: item.id, isEquipped: item.equipped_on !== null })
                }
                rarityNames={RARITY_NAMES}
              />
            );
          })}
        </div>
      </section>

      {/* Inventory grid */}
      <section className="bag">
        <h2 className="bag__title">
          {t('inventory.bag')} ({Object.keys(inventoryByPos).length}/{INVENTORY_CAP})
        </h2>
        <div
          className="bag__grid"
          style={{ gridTemplateColumns: `repeat(${INVENTORY_COLS}, 1fr)` }}
        >
          {Array.from({ length: INVENTORY_CAP }, (_, pos) => {
            const item = inventoryByPos[pos];
            const isSelected = item != null && item.id === selectedId;
            return (
              <BagCell
                key={pos}
                item={item ?? null}
                isSelected={isSelected}
                busy={busy}
                onClick={() => item && void handleItemClick(item)}
                onLongPress={() =>
                  item &&
                  setMenuState({ itemId: item.id, isEquipped: item.equipped_on !== null })
                }
                rarityNames={RARITY_NAMES}
              />
            );
          })}
        </div>
      </section>

      {selected && !menuState && !compareItem && (
        <ItemTooltip
          item={selected}
          onClose={() => setSelectedId(null)}
        />
      )}

      {/* W5-051: long-press menu overlay. */}
      {menuState && (
        <LongPressMenuOverlay
          state={menuState}
          onAction={(action, itemId) => void handleMenuAction(action, itemId)}
        />
      )}

      {/* W5-052: compare tooltip overlay. */}
      {compareItem && (
        <CompareTooltip
          item={compareItem}
          equippedItem={compareEquipped}
          onClose={() => setCompareId(null)}
        />
      )}
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

interface ItemCellProps {
  item: ItemDTO | null;
  isSelected: boolean;
  busy: number | null;
  label: string;
  onClick: () => void;
  onLongPress: () => void;
  rarityNames: string[];
}

/**
 * Ячейка equipped slot — поддерживает long-press (W5-051).
 */
function ItemCell({ item, isSelected, busy, label, onClick, onLongPress, rarityNames }: ItemCellProps) {
  const { handlers } = useLongPress(onLongPress);
  return (
    <button
      type="button"
      className={[
        'slot',
        item ? `slot--filled rarity--${rarityNames[item.rarity]}` : 'slot--empty',
        isSelected ? 'slot--selected' : '',
      ].filter(Boolean).join(' ')}
      disabled={!item || busy !== null}
      onClick={onClick}
      {...handlers}
    >
      <span className="slot__label">{label}</span>
      {item && <span className="slot__name">{item.base_kind}</span>}
    </button>
  );
}

interface BagCellProps {
  item: ItemDTO | null;
  isSelected: boolean;
  busy: number | null;
  onClick: () => void;
  onLongPress: () => void;
  rarityNames: string[];
}

/**
 * Ячейка bag grid — поддерживает long-press (W5-051).
 */
function BagCell({ item, isSelected, busy, onClick, onLongPress, rarityNames }: BagCellProps) {
  const { handlers } = useLongPress(onLongPress);
  return (
    <button
      type="button"
      className={[
        'cell',
        item ? `cell--filled rarity--${rarityNames[item.rarity]}` : 'cell--empty',
        isSelected ? 'cell--selected' : '',
      ].filter(Boolean).join(' ')}
      disabled={!item || busy !== null}
      onClick={onClick}
      {...handlers}
    >
      {item && <span className="cell__ilvl">{item.ilvl}</span>}
    </button>
  );
}

interface TooltipProps {
  item: ItemDTO;
  onClose: () => void;
}

function ItemTooltip({ item, onClose }: TooltipProps) {
  const { t } = useTranslation();
  return (
    <aside className={`tooltip rarity--${RARITY_NAMES[item.rarity]}`}>
      <button
        type="button"
        className="tooltip__close"
        onClick={onClose}
        aria-label="Close"
      >
        ×
      </button>
      <h3 className="tooltip__name">{item.base_kind}</h3>
      <p className="tooltip__meta">
        T{item.rarity + 1} · ilvl {item.ilvl}
      </p>
      {item.affixes.length > 0 && (
        <ul className="tooltip__affixes">
          {item.affixes.map((a) => (
            <li key={a.id} className="tooltip__affix">
              <span className="tooltip__affix-tier">T{a.t}</span>
              <span className="tooltip__affix-mod">
                {a.mod_type ?? `affix_${a.id}`}
              </span>
              <span className="tooltip__affix-value">+{a.value}</span>
              <span className="tooltip__affix-quality">
                ({Math.round(((a.value - a.vmin) / Math.max(1, a.vmax - a.vmin)) * 100)}%)
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="tooltip__hint">
        {item.equipped_on
          ? t('inventory.tap_again_unequip')
          : t('inventory.tap_again_equip')}
      </p>
    </aside>
  );
}
