import path from "node:path";
import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV !== "production";
const publicApi = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
// A relative value ("/api") means the browser only talks to this origin through the rewrite below.
const apiOrigin = publicApi.startsWith("/") ? "" : new URL(publicApi).origin;
// Same-origin proxy target (the deployed API). When set, /api/* is forwarded to it, which keeps the
// staff refresh cookie first-party and avoids third-party-cookie blocking in Safari and Chrome.
const proxyTarget = process.env.API_PROXY_TARGET?.replace(/\/$/, "");

// Next.js hydrates with inline scripts, so script-src needs 'unsafe-inline' unless a per-request nonce
// is wired through a proxy. Everything else is locked down; 'unsafe-eval' is development-only (HMR).
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: https:",
  "font-src 'self' data:",
  `connect-src 'self' ${apiOrigin}${isDev ? " ws: wss:" : ""}`.replace(/ +/g, " ").trim(),
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
];

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined, // Docker image only
  outputFileTracingRoot: path.resolve(__dirname), // this repo has other lockfiles above frontend/
  async rewrites() {
    return proxyTarget ? [{ source: "/api/:path*", destination: `${proxyTarget}/:path*` }] : [];
  },
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      // Staff pages must never be cached by shared caches or the browser back/forward cache.
      { source: "/staff/:path*", headers: [{ key: "Cache-Control", value: "no-store" }] },
    ];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
