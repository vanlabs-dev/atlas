import type { Metadata, Viewport } from "next";
import { Newsreader, Schibsted_Grotesk } from "next/font/google";
import { getBlockAnchor } from "@/data/chain";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import "./globals.css";

const newsreader = Newsreader({
  subsets: ["latin"],
  style: "normal",
  axes: ["opsz"],
  variable: "--font-newsreader",
  display: "swap",
});
const schibsted = Schibsted_Grotesk({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-schibsted",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Atlas reads all 128 Bittensor subnets", template: "%s | Atlas" },
  description:
    "Atlas is a self-hosted system on a Raspberry Pi. It reads the code of every Bittensor subnet, the chain and the market, and shows what changed.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#08090a" },
    { media: "(prefers-color-scheme: light)", color: "#f6f7f8" },
  ],
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const anchor = await getBlockAnchor();
  return (
    <html lang="en" className={`${newsreader.variable} ${schibsted.variable}`}>
      <body className="flex min-h-svh flex-col">
        <SiteHeader anchor={anchor} />
        <div className="flex-1">{children}</div>
        <SiteFooter />
      </body>
    </html>
  );
}
