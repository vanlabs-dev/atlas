import type { Metadata, Viewport } from "next";
import { Motion } from "@/components/motion";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Atlas: every Bittensor subnet, watched", template: "%s | Atlas" },
  description:
    "Atlas is a self-hosted system on a Raspberry Pi that clones every Bittensor subnet's code, watches the chain, and shows what changed.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#133621" },
    { media: "(prefers-color-scheme: light)", color: "#f3f6ef" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: "document.documentElement.classList.add('js')" }} />
        <link rel="preconnect" href="https://api.fontshare.com" />
        <link rel="preconnect" href="https://cdn.fontshare.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://api.fontshare.com/v2/css?f[]=general-sans@400,500,700&display=swap"
        />
      </head>
      <body className="min-h-svh antialiased">
        <Motion>{children}</Motion>
      </body>
    </html>
  );
}
