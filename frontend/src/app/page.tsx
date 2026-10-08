import { Navbar } from "@/components/landing/navbar";
import { Hero } from "@/components/landing/hero";
import { Night } from "@/components/landing/night";
import { Route } from "@/components/landing/route";
import { Marquee } from "@/components/landing/marquee";
import { Stamp } from "@/components/landing/stamp";
import { Pack } from "@/components/landing/pack";
import { Feedback } from "@/components/landing/feedback";
import { Footer } from "@/components/landing/footer";

export default function LandingPage() {
  return (
    <main className="relative min-h-screen overflow-x-clip bg-background">
      <Navbar />
      <Hero />
      <Night />
      <Route />
      <Marquee />
      <Stamp />
      <Pack />
      <Feedback />
      <Footer />
    </main>
  );
}
