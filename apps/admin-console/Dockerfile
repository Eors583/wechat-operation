FROM node:22.22-alpine AS base
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.19.0 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./

FROM base AS development
RUN pnpm install --frozen-lockfile
COPY . .
EXPOSE 9000
CMD ["pnpm", "dev", "--", "--port", "9000"]

FROM base AS build
RUN pnpm install --frozen-lockfile
COPY . .
ENV VITE_BASE_PATH=/admin/
RUN pnpm build

FROM nginx:1.29-alpine AS production
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD wget -q -O - http://127.0.0.1/healthz || exit 1
