import { Navbar } from "@/components/landing/navbar";
import { Hero } from "@/components/landing/hero";
import { Features } from "@/components/landing/features";
import { Modules } from "@/components/landing/modules";
import { Pricing } from "@/components/landing/pricing";
import { Footer } from "@/components/landing/footer";

export default function LandingPage() {
  return (
    <main className="relative min-h-screen overflow-x-clip bg-mesh">
      <Navbar />
      <Hero />
      <Features />
      <Modules />
      <Pricing />
      <Footer />
    </main>
  );
}
