import type { Metadata } from "next";
import "@fontsource-variable/hanken-grotesk";
import "@fontsource-variable/newsreader";
import "./globals.css";
import { AppProviders } from "@/components/providers/app-providers";

export const metadata: Metadata = {
  title: { default: "Lumora", template: "%s · Lumora" },
  description:
    "Search your documents and ask questions across your team's knowledge, with answers that cite their sources.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-dvh">
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
