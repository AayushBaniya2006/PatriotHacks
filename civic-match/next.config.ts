import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep the Postgres driver out of the server bundle — pg uses dynamic requires
  // that break when bundled.
  serverExternalPackages: ["pg"],
};

export default nextConfig;
