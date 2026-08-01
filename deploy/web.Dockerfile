# Caddy serving the built UI and proxying /api to the backend on one origin.
# Build context is the repo root.
#
# The UI is compiled here rather than mounted, so the image is the artefact:
# what was tested is what ships, and there is no Node runtime in the result.

# ---------------------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /build

# Manifests first. This layer is cached until a dependency actually changes,
# so editing a component does not reinstall node_modules.
COPY frontend/package.json frontend/package-lock.json ./
# `npm ci` not `npm install`: it installs exactly the lockfile and fails if the
# lockfile and manifest disagree, which is the behaviour a build should have.
RUN npm ci

COPY frontend/ ./
# Runs `tsc -b && vite build` -- a type error fails the image build rather than
# shipping and failing in the browser.
RUN npm run build

# ---------------------------------------------------------------------------
FROM caddy:2-alpine

COPY --from=build /build/dist /srv
COPY deploy/Caddyfile /etc/caddy/Caddyfile

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --quiet --spider http://127.0.0.1/ || exit 1
