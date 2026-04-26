FROM node:22-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM caddy:2-alpine

COPY --from=builder /app/dist /srv

# Caddy уже настроен в корневом Caddyfile проекта
EXPOSE 80
