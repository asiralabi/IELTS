"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";

export function AiAssistant() {
  const pathname = usePathname();
  const [showBubble, setShowBubble] = React.useState(false);
  const [hovered, setHovered] = React.useState(false);

  React.useEffect(() => {
    const t = setTimeout(() => setShowBubble(true), 2500);
    const hide = setTimeout(() => setShowBubble(false), 9000);
    return () => {
      clearTimeout(t);
      clearTimeout(hide);
    };
  }, []);

  if (pathname.startsWith("/chat")) return null;

  return (
    <div className="fixed bottom-20 right-4 z-50 flex flex-col items-end gap-2 md:bottom-6 md:right-6">
      <AnimatePresence>
        {(showBubble || hovered) && (
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.9 }}
            transition={{ type: "spring", stiffness: 300, damping: 22 }}
            className="glass-strong max-w-52 rounded-2xl rounded-br-sm px-4 py-2.5 text-sm shadow-soft"
          >
            Need help? Ask your AI instructor anything!
          </motion.div>
        )}
      </AnimatePresence>

      <Link href="/chat" aria-label="Open AI chat">
        <motion.div
          onHoverStart={() => setHovered(true)}
          onHoverEnd={() => setHovered(false)}
          whileHover={{ scale: 1.08 }}
          whileTap={{ scale: 0.94 }}
          animate={{ y: [0, -6, 0] }}
          transition={{
            y: { duration: 3, repeat: Infinity, ease: "easeInOut" },
          }}
          className="relative flex size-16 items-center justify-center rounded-[22px] bg-gradient-to-br from-primary via-secondary to-accent shadow-glow animate-pulse-glow"
        >
          {/* Cute robot face */}
          <div className="relative flex h-9 w-11 flex-col items-center justify-center rounded-xl bg-white/95 dark:bg-zinc-900/95">
            <div className="flex gap-2">
              <span className="block h-2.5 w-1.5 origin-center animate-blink rounded-full bg-primary" />
              <span className="block h-2.5 w-1.5 origin-center animate-blink rounded-full bg-primary [animation-delay:0.05s]" />
            </div>
            <span className="mt-1 block h-1 w-3 rounded-full border-b-2 border-primary" />
          </div>
          {/* Antenna */}
          <span className="absolute -top-2 left-1/2 h-2.5 w-0.5 -translate-x-1/2 rounded-full bg-white/70" />
          <span className="absolute -top-3.5 left-1/2 size-2 -translate-x-1/2 rounded-full bg-accent shadow-glow-accent" />
        </motion.div>
      </Link>
    </div>
  );
}
