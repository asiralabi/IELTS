# syntax=docker/dockerfile:1

# AI IELTS Instructor & Examiner — frontend (Next.js 16, standalone output).

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Next inlines NEXT_PUBLIC_* into the browser bundle at BUILD time, so this is
# baked, not configurable at run time. The default is relative on purpose: the
# same image then works behind a LAN address, a tunnel URL or a real domain
# with no rebuild, because the browser resolves /api against whatever origin it
# loaded the page from. Pass an absolute URL only when the backend is on a
# different origin than the frontend.
ARG NEXT_PUBLIC_API_URL=/api
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001
# `standalone` is a self-contained server plus the node_modules it actually
# reached; static/ and public/ are not in it and have to come across separately.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
