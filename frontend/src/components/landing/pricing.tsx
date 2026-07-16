"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { fadeUp, staggerContainer } from "@/lib/motion";
import { cn } from "@/lib/utils";

const tiers = [
  {
    name: "Starter",
    price: "$0",
    period: "forever",
    tagline: "Get a feel for AI-powered prep.",
    features: [
      "AI chat instructor",
      "3 practice sets per week",
      "1 writing evaluation per week",
      "Progress dashboard",
    ],
    cta: "Start Free",
    featured: false,
  },
  {
    name: "Pro",
    price: "$12",
    period: "/month",
    tagline: "Serious preparation, unlimited AI.",
    features: [
      "Unlimited practice & evaluations",
      "Full mock exams with band scores",
      "Speaking examiner with transcripts",
      "Personal study plan & weakness analysis",
      "Priority AI responses",
    ],
    cta: "Go Pro",
    featured: true,
  },
  {
    name: "Team",
    price: "$39",
    period: "/month",
    tagline: "For classrooms and academies.",
    features: [
      "Everything in Pro",
      "Up to 10 student seats",
      "Instructor progress overview",
      "Custom study material (PDF ingest)",
    ],
    cta: "Contact Us",
    featured: false,
  },
];

export function Pricing() {
  return (
    <section id="pricing" className="relative py-24">
      <div className="mx-auto max-w-6xl px-6">
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-80px" }}
          className="text-center"
        >
          <motion.h2
            variants={fadeUp}
            className="font-display text-3xl font-bold tracking-tight sm:text-5xl"
          >
            Simple, <span className="text-gradient">transparent</span> pricing
          </motion.h2>
          <motion.p
            variants={fadeUp}
            className="mx-auto mt-4 max-w-2xl text-muted-foreground"
          >
            Start free. Upgrade when you&apos;re ready to go all-in.
          </motion.p>
        </motion.div>

        <motion.div
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          className="mt-14 grid gap-6 lg:grid-cols-3"
        >
          {tiers.map((tier) => (
            <motion.div key={tier.name} variants={fadeUp} className="h-full">
              <motion.div
                whileHover={{ y: -8 }}
                transition={{ type: "spring", stiffness: 280, damping: 20 }}
                className={cn(
                  "relative flex h-full flex-col rounded-[28px] p-7 shadow-soft transition-shadow duration-300",
                  tier.featured
                    ? "glass-strong border-primary/30 shadow-glow"
                    : "glass hover:shadow-lift"
                )}
              >
                {tier.featured && (
                  <Badge className="absolute -top-3 left-1/2 -translate-x-1/2 shadow-glow">
                    Most Popular
                  </Badge>
                )}
                <h3 className="font-display text-lg font-semibold">{tier.name}</h3>
                <div className="mt-3 flex items-baseline gap-1">
                  <span className="font-display text-4xl font-bold">{tier.price}</span>
                  <span className="text-sm text-muted-foreground">{tier.period}</span>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">{tier.tagline}</p>
                <ul className="mt-6 flex-1 space-y-3">
                  {tier.features.map((f) => (
                    <li key={f} className="flex items-start gap-2.5 text-sm">
                      <Check className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
                      {f}
                    </li>
                  ))}
                </ul>
                <Link href="/register" className="mt-7 block">
                  <Button
                    variant={tier.featured ? "primary" : "secondary"}
                    className="w-full"
                  >
                    {tier.cta}
                  </Button>
                </Link>
              </motion.div>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
