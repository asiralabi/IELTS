"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import { Send, Plus, MessageSquare, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { ChatMessage, ChatSession } from "@/lib/types";
import { Topbar } from "@/components/shell/topbar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type LocalMessage = Pick<ChatMessage, "role" | "content"> & { id: string };

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1.5 px-1 py-2" aria-label="AI is thinking">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          animate={{ y: [0, -6, 0], opacity: [0.4, 1, 0.4] }}
          transition={{ duration: 1, repeat: Infinity, delay: i * 0.18 }}
          className="size-2 rounded-full bg-primary"
        />
      ))}
    </div>
  );
}

export default function ChatPage() {
  const [sessions, setSessions] = React.useState<ChatSession[]>([]);
  const [sessionId, setSessionId] = React.useState<number | null>(null);
  const [messages, setMessages] = React.useState<LocalMessage[]>([]);
  const [input, setInput] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const bottomRef = React.useRef<HTMLDivElement>(null);

  const loadSessions = React.useCallback(() => {
    api.chatSessions().then(setSessions).catch(() => {});
  }, []);

  React.useEffect(loadSessions, [loadSessions]);

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  const openSession = async (id: number) => {
    setSessionId(id);
    try {
      const history = await api.chatHistory(id);
      setMessages(history.map((m) => ({ id: String(m.id), role: m.role, content: m.content })));
    } catch {
      toast.error("Could not load that conversation.");
    }
  };

  const newChat = () => {
    setSessionId(null);
    setMessages([]);
  };

  const send = async () => {
    const message = input.trim();
    if (!message || busy) return;
    setInput("");
    setMessages((m) => [...m, { id: `u-${Date.now()}`, role: "user", content: message }]);
    setBusy(true);
    try {
      const res = await api.chat(message, sessionId);
      setSessionId(res.session_id);
      setMessages((m) => [
        ...m,
        { id: `a-${Date.now()}`, role: "assistant", content: res.reply },
      ]);
      loadSessions();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "The AI could not reply.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex h-[calc(100vh-3rem)] max-w-6xl flex-col">
      <Topbar title="AI Instructor" />

      <div className="flex min-h-0 flex-1 gap-5">
        {/* Session list */}
        <aside className="glass hidden w-60 shrink-0 flex-col overflow-hidden rounded-[24px] p-3 shadow-soft lg:flex">
          <Button variant="secondary" size="sm" onClick={newChat} className="mb-3 w-full">
            <Plus className="size-4" aria-hidden />
            New chat
          </Button>
          <div className="no-scrollbar flex-1 space-y-1 overflow-y-auto">
            {sessions.map((s) => (
              <button
                key={s.id}
                onClick={() => openSession(s.id)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm transition-colors",
                  sessionId === s.id
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <MessageSquare className="size-4 shrink-0" aria-hidden />
                <span className="truncate">{s.title || `Chat ${s.id}`}</span>
              </button>
            ))}
          </div>
        </aside>

        {/* Conversation */}
        <div className="glass flex min-w-0 flex-1 flex-col overflow-hidden rounded-[24px] shadow-soft">
          <div className="no-scrollbar flex-1 space-y-4 overflow-y-auto p-5">
            {messages.length === 0 && !busy && (
              <div className="flex h-full flex-col items-center justify-center text-center">
                <motion.div
                  animate={{ y: [0, -8, 0] }}
                  transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                  className="mb-4 flex size-16 items-center justify-center rounded-[22px] bg-gradient-to-br from-primary to-secondary shadow-glow"
                >
                  <Sparkles className="size-8 text-white" aria-hidden />
                </motion.div>
                <h2 className="font-display text-xl font-semibold">
                  Ask me anything about IELTS
                </h2>
                <p className="mt-2 max-w-sm text-sm text-muted-foreground">
                  Grammar, vocabulary, strategies, band descriptors — your
                  instructor is ready.
                </p>
                <div className="mt-6 flex flex-wrap justify-center gap-2">
                  {[
                    "How is Writing Task 2 scored?",
                    "Give me 5 linking phrases for essays",
                    "What happens in Speaking Part 2?",
                  ].map((q) => (
                    <button
                      key={q}
                      onClick={() => setInput(q)}
                      className="glass rounded-full px-4 py-2 text-xs text-muted-foreground transition-all hover:text-foreground hover:shadow-glow"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <AnimatePresence initial={false}>
              {messages.map((m) => (
                <motion.div
                  key={m.id}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}
                >
                  <div
                    className={cn(
                      "max-w-[85%] rounded-3xl px-4 py-3 text-sm leading-relaxed shadow-soft",
                      m.role === "user"
                        ? "rounded-br-lg bg-gradient-to-br from-primary to-secondary text-white"
                        : "glass-strong rounded-bl-lg"
                    )}
                  >
                    {m.role === "assistant" ? (
                      <div className="prose-chat">
                        <ReactMarkdown>{m.content}</ReactMarkdown>
                      </div>
                    ) : (
                      m.content
                    )}
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>

            {busy && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start">
                <div className="glass-strong rounded-3xl rounded-bl-lg px-4 py-2 shadow-soft">
                  <ThinkingDots />
                  <p className="pb-1 text-[11px] text-muted-foreground">
                    Your instructor is thinking — local AI can take a little while…
                  </p>
                </div>
              </motion.div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Composer */}
          <div className="border-t border-border p-4">
            <div className="flex items-end gap-2">
              <Textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                placeholder="Ask your AI instructor…"
                rows={1}
                className="max-h-36 min-h-11 resize-none"
                aria-label="Chat message"
              />
              <Button
                onClick={send}
                disabled={!input.trim() || busy}
                size="icon"
                aria-label="Send message"
              >
                <Send className="size-4" aria-hidden />
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
