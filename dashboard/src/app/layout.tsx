import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Asomein Bot",
  description: "Asomein Bot Dashboard",
  icons: {
    icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512'><path fill='%230085ff' d='M111.8 62.2C170.2 105.9 233 194.7 256 241.1c23-46.4 85.8-135.2 144.2-178.9 27.1-20.2 64.9-25.3 84.1-8.5 20.3 17.8 14.8 55.4 3.7 93.3-15.6 53.6-59.5 106.1-133 113.8 69.3 5.4 114.7 18.2 129.4 46.2 14.7 27.9-2.2 62.4-76.3 87.7-93.5 32-152.1-10.7-152.1-10.7S197.4 426.6 103.9 394.6c-74.1-25.3-91-59.8-76.3-87.7 14.7-28 60.1-40.8 129.4-46.2-73.5-7.7-117.4-60.2-133-113.8-11.1-37.9-16.6-75.5 3.7-93.3 19.2-16.8 57-11.7 84.1 8.5z'/></svg>"
  }
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
