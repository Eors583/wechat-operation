FROM node:22.22-alpine AS development
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.19.0 --activate
COPY . .
RUN pnpm install --frozen-lockfile
RUN pnpm --dir src-capacitor install --frozen-lockfile
EXPOSE 9000
CMD ["pnpm", "dev"]

FROM development AS build
RUN pnpm build

FROM nginx:1.27-alpine AS production
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/spa /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
