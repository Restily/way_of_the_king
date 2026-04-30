/**
 * CompareTooltip — side-by-side сравнение affixes item'а с экипированным (W5-052).
 *
 * Показывает два столбца: выбранный item и equipped item того же base_slot.
 * Если equipped item отсутствует — второй столбец пустой (slot not equipped).
 */

import { useTranslation } from 'react-i18next';
import type { ItemDTO } from '../api/inventory';

const RARITY_NAMES = ['common', 'magic', 'rare', 'epic', 'legendary'] as const;

interface CompareTooltipProps {
  /** Выбранный item (кандидат для экипировки / просмотра). */
  item: ItemDTO;
  /** Экипированный item того же slot'а (если есть). */
  equippedItem: ItemDTO | null;
  onClose: () => void;
}

export function CompareTooltip({ item, equippedItem, onClose }: CompareTooltipProps) {
  const { t } = useTranslation();

  return (
    <aside className="inventory__compare-tooltip">
      <button
        type="button"
        className="inventory__compare-close"
        onClick={onClose}
        aria-label={t('inventory.compare.close')}
      >
        ×
      </button>
      <div className="inventory__compare-columns">
        <CompareColumn item={item} emptyText={t('inventory.compare.no_affixes')} />
        <div className="inventory__compare-divider">vs</div>
        <CompareColumn
          item={equippedItem}
          emptyText={t('inventory.compare.no_affixes')}
          slotEmptyText={t('inventory.compare.slot_empty')}
        />
      </div>
    </aside>
  );
}

interface CompareColumnProps {
  item: ItemDTO | null;
  emptyText: string;
  /** Если задан и item==null, показываем "слот пуст" вместо "no affixes". */
  slotEmptyText?: string;
}

function CompareColumn({ item, emptyText, slotEmptyText }: CompareColumnProps) {
  if (!item) {
    return (
      <div className="inventory__compare-col inventory__compare-col--empty">
        <p className="inventory__compare-empty">{slotEmptyText ?? emptyText}</p>
      </div>
    );
  }
  return (
    <div className={`inventory__compare-col rarity--${RARITY_NAMES[item.rarity]}`}>
      <h4 className="inventory__compare-col-title">{item.base_kind}</h4>
      <p className="inventory__compare-col-meta">T{item.rarity + 1} · ilvl {item.ilvl}</p>
      {item.affixes.length > 0 ? (
        <table className="inventory__compare-table">
          <tbody>
            {item.affixes.map((a) => (
              <tr key={a.id}>
                <td className="inventory__compare-tier">T{a.t}</td>
                <td className="inventory__compare-mod">{a.mod_type ?? `affix_${a.id}`}</td>
                <td className="inventory__compare-value">+{a.value}</td>
                <td className="inventory__compare-quality">
                  ({Math.round(((a.value - a.vmin) / Math.max(1, a.vmax - a.vmin)) * 100)}%)
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="inventory__compare-empty">{emptyText}</p>
      )}
    </div>
  );
}
