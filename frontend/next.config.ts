import type { NextConfig } from "next";

/**
 * The origin the browser calls for the API. With the bundled proxy the base is
 * relative ("/api") and 'self' already covers it.
 */
function apiOrigin(): string | null {
  const raw = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
  try {
    return new URL(raw).origin;
  } catch {
    return null;
  }
}

const isProd = process.env.NODE_ENV === "production";
const api = apiOrigin();
// Listening audio is served from a Vercel Blob store via a redirect.
const blob = "https://*.public.blob.vercel-storage.com";

/**
 * A Content-Security-Policy that stops the page from loading scripts from
 * anywhere else or sending data anywhere but the API. 'unsafe-inline' stays on
 * script-src because Next.js and next-themes inline small bootstrap scripts
 * into statically prerendered pages; a nonce would force every page to render
 * per request.
 */
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isProd ? "" : " 'unsafe-eval'"}`,
  "style-src 'self' 'unsafe-inline'",
  `img-src 'self' data: blob:${api ? ` ${api}` : ""} ${blob}`,
  `media-src 'self' blob: data:${api ? ` ${api}` : ""} ${blob}`,
  // The blob origin is here too: the audio is fetched with fetch(), and the API
  // answers with a redirect to the blob store, which connect-src governs.
  `connect-src 'self'${api ? ` ${api}` : ""} ${blob}${isProd ? "" : " ws: wss:"}`,
  "font-src 'self' data:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  // No upgrade-insecure-requests: the Caddy image is also served over plain
  // HTTP on a LAN, where it would rewrite every asset to https and break.
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
  // The speaking module needs the microphone; nothing needs the rest.
  { key: "Permissions-Policy", value: "microphone=(self), camera=(), geolocation=(), payment=(), usb=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  // Emit .next/standalone: the server plus only the node_modules it actually
  // reaches. `npm run dev` and `npm run start` are unaffected; this exists so
  // the container image stays small.
  output: "standalone",
  // Do not advertise the framework and version to scanners.
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
