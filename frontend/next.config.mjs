/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Proxy /api calls to the backend during development so the browser
  // never needs to know the backend URL (avoids CORS issues in dev).
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
