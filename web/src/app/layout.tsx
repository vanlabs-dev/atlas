import type { Metadata, Viewport } from "next";
import { Archivo } from "next/font/google";
import { getBlockAnchor } from "@/data/chain";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { SiteTabs } from "@/components/site-nav";
import { FLIGHT_MODE_SCRIPT } from "@/state/flight-mode";
import "./globals.css";

// One family. The width axis carries the condensed figures and the hovers that widen a name.
const archivo = Archivo({
  subsets: ["latin"],
  style: "normal",
  axes: ["wdth"],
  variable: "--font-archivo",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "subnt.dev: Atlas reads all 128 Bittensor subnets", template: "%s | subnt.dev" },
  description:
    "Atlas is a self-hosted system on a Raspberry Pi. It reads the code of every Bittensor subnet, the chain and the market, and shows what changed.",
};

export const viewport: Viewport = {
  // The page draws under the notch and the home bar; the bars and the gutters add the safe-area insets.
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0b" },
    { media: "(prefers-color-scheme: light)", color: "#f2f2f0" },
  ],
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const anchor = await getBlockAnchor();
  return (
    <html lang="en" className={archivo.variable} suppressHydrationWarning>
      <body className="flex min-h-svh flex-col">
        {/* Before first paint: writes the home field's stage mode on <html> (src/state/flight-mode.ts). */}
        <script dangerouslySetInnerHTML={{ __html: FLIGHT_MODE_SCRIPT }} />
        <SiteHeader anchor={anchor} />
        <div className="flex-1">{children}</div>
        <SiteFooter />
        <SiteTabs />
      </body>
    </html>
  );
}
