# Shared schemas

JSON Schema файлы для типов, разделяемых между сервисами:
- **backend** (Python через `datamodel-code-generator` → Pydantic)
- **realtime** (TypeScript через `json-schema-to-typescript`)
- **frontend** (TypeScript)

## Текущие схемы

Заполнится в Phase 3 (Недели 5–7):

- `jwt_payload.schema.json` — payload short-lived JWT для WS-handshake
- `run_finish.schema.json` — payload callback от Colyseus → FastAPI при завершении рана

## Codegen

```bash
# Python (Pydantic models)
cd backend
uv run datamodel-codegen \
  --input ../shared/schemas \
  --output src/wotk/schemas/generated.py

# TypeScript (interfaces)
cd realtime  # или frontend
npx json-schema-to-typescript \
  ../shared/schemas/jwt_payload.schema.json > src/schemas/jwt_payload.ts
```

CI должен проверять, что сгенерированные файлы in-sync с источниками (см. `.github/workflows/ci.yml`).
