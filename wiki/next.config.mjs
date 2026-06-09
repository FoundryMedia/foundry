/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",

  // S3 static hosting — no trailing slashes, clean paths
  trailingSlash: false,

  // All assets served from the same bucket origin
  assetPrefix: undefined,

  images: {
    unoptimized: true, // Required for static export
  },
};

export default nextConfig;
