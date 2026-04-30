/** Inventory + equip/unequip endpoints. */
import { apiFetch } from './client';

export interface ItemDTO {
  id: number;
  base_id: number;
  base_kind: string;
  base_slot: number;
  rarity: number;
  ilvl: number;
  affixes: Array<{
    id: number;
    value: number;
    t: number;
    vmin: number;
    vmax: number;
    mod_type?: string;
  }>;
  equipped_on: number | null;
  equipped_slot: number | null;
  inventory_position: number | null;
}

export interface InventoryResponse {
  items: ItemDTO[];
  total: number;
}

export interface CombatStats {
  hp: number;
  mana: number;
  atk: number;
  def_: number;
  crit_chance_pct: number;
  crit_damage_pct: number;
  attack_speed_mult: number;
  movement_speed_mult: number;
  resist_fire_pct: number;
  resist_cold_pct: number;
  resist_lightning_pct: number;
}

export function getInventory(): Promise<InventoryResponse> {
  return apiFetch<InventoryResponse>('/api/v1/inventory');
}

export function equipItem(itemId: number, slot: number): Promise<ItemDTO> {
  return apiFetch<ItemDTO>(`/api/v1/items/${itemId}/equip`, {
    method: 'POST',
    body: { slot },
  });
}

export function unequipItem(itemId: number): Promise<ItemDTO> {
  return apiFetch<ItemDTO>(`/api/v1/items/${itemId}/unequip`, {
    method: 'POST',
  });
}

export function getCombatStats(): Promise<CombatStats> {
  return apiFetch<CombatStats>('/api/v1/me/combat-stats');
}
