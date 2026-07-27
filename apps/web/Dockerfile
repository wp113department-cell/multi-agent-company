# Build context MUST be the repo root (see docker-compose.yml's frontend
# service: `context: .`, `dockerfile: apps/web/Dockerfile`) — this is a pnpm
# workspace, so pnpm-lock.yaml/pnpm-workspace.yaml/the root package.json all
# live outside apps/web and are required for `pnpm install` to resolve
# workspace dependencies correctly.

FROM node:22-slim AS base
WORKDIR /repo
RUN corepack enable

# ---- deps: install once, cached unless lockfiles change ----
FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json
RUN pnpm install --frozen-lockfile

# ---- build ----
FROM base AS build
COPY --from=deps /repo/node_modules ./node_modules
COPY --from=deps /repo/apps/web/node_modules ./apps/web/node_modules
COPY . .
RUN pnpm --filter @gridiron/web run build

# ---- runtime ----
FROM base AS runtime
ENV NODE_ENV=production
# Root package.json (packageManager: pnpm@11.9.0) and pnpm-workspace.yaml
# are required here too, not just at install time: `pnpm --filter` run from
# WORKDIR /repo resolves the pinned pnpm version and workspace membership
# from these files. Without them, corepack tries to fetch the latest pnpm
# from the registry at container start instead of using the already-cached,
# pinned version — found via an actual container run, not assumed.
COPY package.json pnpm-workspace.yaml ./
COPY --from=build /repo/apps/web/.next ./apps/web/.next
COPY --from=build /repo/apps/web/package.json ./apps/web/package.json
COPY --from=build /repo/apps/web/next.config.mjs ./apps/web/next.config.mjs
COPY --from=deps /repo/node_modules ./node_modules
COPY --from=deps /repo/apps/web/node_modules ./apps/web/node_modules

EXPOSE 3000
CMD ["pnpm", "--filter", "@gridiron/web", "run", "start"]
