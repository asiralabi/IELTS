import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  // Emit .next/standalone: the server plus only the node_modules it actually
  // reaches. `npm run dev` and `npm run start` are unaffected; this exists so
  // the container image is ~200MB instead of shipping the whole dependency
  // tree (three, drei and framer-motion dominate it).
  output: "standalone",
};

export default nextConfig;
