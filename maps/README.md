# Maps

Карты данжей в формате [Tiled](https://www.mapeditor.org/) `.tmx` (XML) либо `.json`.

## Структура

- `dungeons/crypt/` — комнаты типа Crypt
- `dungeons/forest/` — комнаты типа Forest
- `dungeons/castle/` — комнаты типа Castle
- `tilesets/` — общие тайлсеты (.tsx)

## Tiled настройки

- Tile size: **32×32** (или 64×64 — финализировать после первых ассетов)
- Layers:
  - `floor` — пол (passable)
  - `walls` — стены (collision)
  - `decor` — декорации (passable, рисуются поверх)
  - `spawns` — object layer: точки спавна мобов и игрока
  - `triggers` — object layer: порталы, сундуки, двери
- Свойства объектов на `spawns` слое:
  - `kind` — `player_spawn` / `mob_skeleton_warrior` / `boss_lich` / etc.
  - `count` — для мобов: количество в этой точке (опц.)

## Загрузка

Карты экспортируются в JSON и грузятся клиентом через `@pixi/tilemap`,
сервером (Colyseus) — для коллизий и спавн-точек.
