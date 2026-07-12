import type { Metadata } from "next";
import Nav from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "Robust Swing v1",
  description: "Q1→Q5 swing-trading funnel for the Nifty 500",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-dvh bg-page text-ink antialiased">
        <div className="flex flex-col md:flex-row">
          <Nav />
          <main className="min-w-0 flex-1 px-4 py-5 sm:px-6 sm:py-6 lg:px-8">
            <div className="mx-auto max-w-6xl">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
