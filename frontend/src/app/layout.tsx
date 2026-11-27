import type { Metadata } from "next";
import { Host_Grotesk, Atkinson_Hyperlegible_Mono } from "next/font/google";
import "./globals.css";
import { QueryProvider } from "@/providers/query-provider";

const hostGrotesk = Host_Grotesk({
  variable: "--font-host-grotesk",
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
});

const atkinsonMono = Atkinson_Hyperlegible_Mono({
  variable: "--font-atkinson-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
  adjustFontFallback: false,
});

export const metadata: Metadata = {
  title: "Autonomous-FinOps console",
  description: "Triage idle and overpriced cloud resources from FOCUS billing exports, and forecast spend.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${hostGrotesk.variable} ${atkinsonMono.variable} h-full`}>
      <body className="min-h-full flex flex-col bg-paper text-ink">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
