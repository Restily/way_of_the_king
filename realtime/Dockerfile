FROM node:25-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM node:25-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=builder /app/build ./build

# Не root
RUN addgroup -g 1000 wotk && adduser -D -u 1000 -G wotk wotk
USER wotk

EXPOSE 2567

CMD ["node", "build/index.js"]
