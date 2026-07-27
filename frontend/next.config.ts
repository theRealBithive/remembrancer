import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the docker image.
  output: "standalone",

  // Covers are resized by Django at sync time (full + ~300px thumb), so there is
  // nothing left for the Next optimizer to do. Keeps sharp out of the image and
  // avoids the optimizer round-tripping through the public hostname during ISR.
  images: { unoptimized: true },

  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
