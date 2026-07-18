# frontend/Dockerfile
#
# Multi-stage build:
#   dev        — Vite dev server with HMR; docker-compose.yml builds this
#                (target: dev) and bind-mounts src/ for live reload.
#   build      — compiles the static production bundle.
#   production — nginx serving the bundle; default target, used by
#                docker-compose.prod.yml. Ships no node_modules or build
#                tooling, which keeps the image small and scanner-clean.

FROM node:20-alpine AS dev

# Patch base-image OS packages and npm's bundled dependencies (tar, glob,
# sigstore, …) — they lag the base image cut and dominate scanner findings.
RUN apk upgrade --no-cache && npm install -g npm@11

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

ENV VITE_API_URL=/api

EXPOSE 3000

# Start the Vite dev server (host=0.0.0.0 set in vite.config.ts)
CMD ["npm", "run", "dev"]


FROM dev AS build
RUN npm run build


FROM nginx:alpine AS production

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html

EXPOSE 3000
