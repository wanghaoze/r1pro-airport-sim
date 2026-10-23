import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "R1 Pro · Scene Studio",
  description: "Edit Isaac scenes, issue conversation commands and train models across 32 rooms.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
