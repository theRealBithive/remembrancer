FROM node:22-alpine AS deps
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile


FROM node:22-alpine AS builder
WORKDIR /app
RUN corepack enable
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# No NEXT_PUBLIC_* build args on purpose. Every component here is a Server
# Component, so SITE_URL and SITE_NAME are read at render time instead of baked
# into the bundle -- which is what lets one published image serve any domain.
ENV NEXT_TELEMETRY_DISABLED=1

# Django is unreachable at build time, so the index prerenders empty. The deploy
# runs `manage.py revalidate_all` afterwards to fill the cache.
RUN pnpm build


FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1

RUN addgroup -g 10001 -S nodejs && adduser -u 10001 -S nextjs -G nodejs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# The ISR cache lives here and is mounted as a volume. Without that, a redeploy
# during a federated Mastodon post means a cold cache and the whole preview-fetch
# herd lands on Django -- the exact thing static rendering was chosen to prevent.
RUN mkdir -p .next/cache && chown -R nextjs:nodejs .next

USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0

CMD ["node", "server.js"]
