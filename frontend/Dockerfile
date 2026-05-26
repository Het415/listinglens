# ── ListingLens frontend image (Next.js 16 App Router, SSR) ───────────────────
# Multi-stage build: a fat `builder` stage with full devDeps + source, then a
# slim `runner` stage that only carries the build output + production node
# modules. Final image is ~200MB instead of ~1.5GB.
#
# Why node and not nginx
# ----------------------
# next.config.mjs has no `output: 'export'`, the app uses the App Router,
# and `@vercel/analytics` is a runtime dep — this is an SSR app. Static
# export to nginx (the pattern in the original architecture spec) would
# break server components and route handlers. Production hosting is
# Vercel; this image is for local dev parity via docker-compose.

# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

# Copy lockfile first — pinning npm to ci-mode means deterministic
# installs, and isolating this layer means edits to src/ don't bust the
# install cache.
COPY package.json package-lock.json* ./
RUN npm ci

# Build the Next.js app. NEXT_TELEMETRY_DISABLED stops the build from
# making outbound network calls to Vercel telemetry (which fail in
# air-gapped CI and just add noise).
ENV NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN npm run build

# ── Stage 2: runner ───────────────────────────────────────────────────────────
# Use a fresh slim base, copy only what `next start` needs.
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

# Non-root user. The `node` user is preinstalled in the official image.
RUN chown -R node:node /app
USER node

# .next/ — compiled output. node_modules — runtime deps only (we re-
# install with --omit=dev). package.json — needed for `npm run start`.
COPY --chown=node:node --from=builder /app/.next ./.next
COPY --chown=node:node --from=builder /app/public ./public
COPY --chown=node:node --from=builder /app/package.json /app/package-lock.json* ./
RUN npm ci --omit=dev

EXPOSE 3000
CMD ["npm", "run", "start"]
