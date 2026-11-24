import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import "./globals.css";

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "HuGuard AI – Multi-Agent Security Auditor",
  description:
    "Autonomous, locally-running codebase and security audit powered by LangGraph and Ollama.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`dark ${jetbrainsMono.variable}`}>
      <body className="bg-surface text-gray-100 antialiased min-h-screen">
        {children}
      </body>
    </html>
  );
}
