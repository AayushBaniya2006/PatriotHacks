import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: false,
  // Keep the Postgres driver out of the server bundle — pg uses dynamic requires
  // that break when bundled.
  serverExternalPackages: ["pg"],
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "images.unsplash.com",
      },
    ],
  },
  turbopack: {
    root: process.cwd(),
  },
};

export default nextConfig;
