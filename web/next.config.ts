import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // When this build ran. Data already past the stale bound at build stays
  // stale, so the server HTML can carry the label before any script runs.
  env: { SITE_BUILT_AT: new Date().toISOString() },
  cacheComponents: true,
  partialPrefetching: true,
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
