import type { Metadata } from "next";
import { Hanken_Grotesk, IBM_Plex_Mono, Newsreader, Tiro_Bangla } from "next/font/google";
import { ThemeProvider } from "next-themes";
import { Toaster } from "sonner";
import "./globals.css";

const hanken = Hanken_Grotesk({
  variable: "--font-hanken",
  subsets: ["latin"],
});

const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
  style: ["normal", "italic"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

// Only the landing story sets Bangla, so this face is not preloaded: it would
// otherwise compete with the Latin faces every app page actually needs.
const tiroBangla = Tiro_Bangla({
  variable: "--font-tiro-bangla",
  subsets: ["bengali"],
  weight: "400",
  preload: false,
});

export const metadata: Metadata = {
  title: {
    default: "Oratio — IELTS practice for the journey abroad",
    template: "%s · Oratio",
  },
  description:
    "Sit full IELTS mock tests at home, get a band for every skill, and see exactly what to fix — built for students in Bangladesh preparing to study abroad.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      data-scroll-behavior="smooth"
      className={`${hanken.variable} ${newsreader.variable} ${plexMono.variable} ${tiroBangla.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          {children}
          <Toaster position="top-center" closeButton />
        </ThemeProvider>
      </body>
    </html>
  );
}
