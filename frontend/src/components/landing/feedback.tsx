"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Check } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Input, Label, FieldError, Textarea } from "@/components/ui/input";
import { Chapter } from "@/components/landing/chapter";
import { cn } from "@/lib/utils";

const MAX_MESSAGE = 4000;

const schema = z.object({
  email: z.string().email("Enter the email address we can reply to"),
  message: z
    .string()
    .trim()
    .min(1, "Tell us what happened — even one line helps")
    .max(MAX_MESSAGE, `Keep it under ${MAX_MESSAGE} characters`),
});

type FormValues = z.infer<typeof schema>;

// The address off the signed-in account, or null for a visitor. Read through
// useSyncExternalStore rather than the zustand hook: the store rehydrates from
// localStorage in the BROWSER only, so a plain subscribed read renders one
// thing during prerender and another after hydration. The third argument is
// the server snapshot — during prerender there is no session, and React
// re-renders with the real value once hydration finishes.
const subscribeToAuth = (onChange: () => void) => useAuth.subscribe(onChange);
const readAccountEmail = () => useAuth.getState().user?.email ?? null;
const noAccountOnServer = () => null;

export function Feedback() {
  const [sent, setSent] = React.useState(false);
  const [rating, setRating] = React.useState<number | null>(null);
  const [hovered, setHovered] = React.useState<number | null>(null);

  const account = React.useSyncExternalStore(
    subscribeToAuth,
    readAccountEmail,
    noAccountOnServer
  );

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", message: "" },
  });

  // The character counter is fed by its own state rather than by the form's
  // `watch()`. watch() hands back a fresh function every render, which makes
  // React Compiler skip memoizing this whole component — a steep price for a
  // number under a textarea.
  const [messageLength, setMessageLength] = React.useState(0);
  const { onChange: onMessageChange, ...messageField } = register("message");

  // Fill the field once the session is known. setValue is react-hook-form's
  // own store, not React state, so this does not cascade a render.
  React.useEffect(() => {
    if (account) setValue("email", account);
  }, [account, setValue]);

  const onSubmit = async (values: FormValues) => {
    try {
      await api.submitFeedback({
        email: values.email,
        message: values.message,
        rating,
        page: typeof window !== "undefined" ? window.location.pathname : null,
      });
      setSent(true);
      toast.success("Thank you. Your note is on its way.");
    } catch (err) {
      const detail =
        err instanceof ApiError && err.status === 0
          ? "We couldn't reach the server. Please try again in a moment."
          : err instanceof Error
            ? err.message
            : "Could not send your feedback.";
      toast.error(detail);
    }
  };

  const sendAnother = () => {
    reset({ email: account ?? "", message: "" });
    setMessageLength(0);
    setRating(null);
    setSent(false);
  };

  return (
    <section id="feedback" className="relative scroll-mt-16 bg-muted/50 py-28 sm:py-36">
      <div className="mx-auto max-w-7xl px-5 sm:px-8">
        <div className="grid gap-8 lg:grid-cols-12">
          <div className="lg:col-span-5">
            <Chapter n="০৫" label="Write home" />
            <h2 className="mt-10 font-display text-4xl leading-[1.05] font-normal tracking-[-0.02em] sm:text-6xl">
              We are still <em className="text-primary">building this.</em>
            </h2>
          </div>
          <p className="max-w-[46ch] self-end leading-relaxed text-muted-foreground lg:col-span-5 lg:col-start-8">
            Oratio is in its pilot. If something broke, confused you or is missing,
            send us a note. Leave your email and a person on the team will write back.
          </p>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 30, rotate: -0.6 }}
          whileInView={{ opacity: 1, y: 0, rotate: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}
          className="relative mt-14 overflow-hidden rounded-2xl border border-border bg-card shadow-lift"
        >
          {/* airmail edge */}
          <div
            aria-hidden
            className="h-2 bg-[repeating-linear-gradient(135deg,var(--sun)_0_14px,transparent_14px_28px,var(--primary)_28px_42px,transparent_42px_56px)] opacity-80"
          />
          {sent ? (
            <div className="grid min-h-[22rem] place-items-center px-6 py-14 text-center">
              <div>
                <span className="mx-auto flex size-14 items-center justify-center rounded-full border-2 border-primary text-primary">
                  <Check className="size-7" strokeWidth={2} aria-hidden />
                </span>
                <h3 className="mt-6 font-display text-3xl">Posted. Thank you.</h3>
                <p className="mx-auto mt-3 max-w-sm text-sm leading-relaxed text-muted-foreground">
                  Your note goes straight to the people building Oratio. If we need more
                  detail, we will write to you.
                </p>
                <Button variant="secondary" className="mt-8" onClick={sendAnother}>
                  Write another
                </Button>
              </div>
            </div>
          ) : (
            <form
              onSubmit={handleSubmit(onSubmit)}
              noValidate
              className="grid md:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]"
            >
              {/* message side */}
              <div className="p-6 sm:p-10 md:border-r md:border-dashed md:border-border">
                <Label
                  htmlFor="feedback-message"
                  className="font-mono text-[11px] font-normal uppercase tracking-[0.16em] text-muted-foreground"
                >
                  Your note
                </Label>
                <Textarea
                  id="feedback-message"
                  rows={8}
                  maxLength={MAX_MESSAGE}
                  placeholder="What did you try, and what happened? Which part felt off?"
                  className="mt-2 resize-none rounded-none border-0 bg-transparent bg-khata px-0 py-1 font-display text-lg leading-[2.1rem] [--margin:0rem] focus:shadow-none"
                  {...messageField}
                  onChange={(e) => {
                    setMessageLength(e.target.value.length);
                    return onMessageChange(e);
                  }}
                />
                <div className="flex items-start justify-between gap-4">
                  <FieldError message={errors.message?.message} />
                  <p className="mt-1.5 ml-auto shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
                    {messageLength}/{MAX_MESSAGE}
                  </p>
                </div>
              </div>

              {/* address side */}
              <div className="flex flex-col gap-8 border-t border-dashed border-border p-6 sm:p-10 md:border-t-0">
                <div className="flex items-start justify-between gap-6">
                  <div>
                    <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground">To</p>
                    <p className="mt-1 font-display text-xl">The Oratio team</p>
                  </div>
                  {/* the stamp doubles as the rating */}
                  <div className="shrink-0 rounded-md border-2 border-dashed border-sun/50 p-2 text-center">
                    <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-muted-foreground">
                      Rate it
                    </p>
                    <div
                      id="feedback-rating"
                      role="radiogroup"
                      aria-label="How is it so far? Optional rating out of 5"
                      className="mt-1 flex gap-0.5"
                      onMouseLeave={() => setHovered(null)}
                    >
                      {[1, 2, 3, 4, 5].map((value) => {
                        const lit = value <= (hovered ?? rating ?? 0);
                        return (
                          <button
                            key={value}
                            type="button"
                            role="radio"
                            aria-checked={rating === value}
                            aria-label={`${value} out of 5`}
                            // Clicking the current score clears it: a rating you
                            // cannot take back is one people stop giving honestly.
                            onClick={() => setRating((r) => (r === value ? null : value))}
                            onMouseEnter={() => setHovered(value)}
                            className="p-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                          >
                            <span
                              className={cn(
                                "block size-3.5 rounded-full border transition-colors",
                                lit ? "border-sun bg-sun" : "border-foreground/30"
                              )}
                            />
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>

                <div>
                  <Label
                    htmlFor="feedback-email"
                    className="font-mono text-[11px] font-normal uppercase tracking-[0.16em] text-muted-foreground"
                  >
                    From
                  </Label>
                  <Input
                    id="feedback-email"
                    type="email"
                    autoComplete="email"
                    placeholder="you@gmail.com"
                    readOnly={account !== null}
                    className={cn(
                      "rounded-none border-0 border-b border-foreground/30 bg-transparent px-0 focus:shadow-none",
                      account !== null && "cursor-not-allowed opacity-70"
                    )}
                    {...register("email")}
                  />
                  <FieldError message={errors.email?.message} />
                  <p className="mt-2 text-xs text-muted-foreground">
                    {account !== null
                      ? "Taken from the account you are signed in with."
                      : "Only used to reply about this note."}
                  </p>
                </div>

                <Button type="submit" loading={isSubmitting} size="lg" className="mt-auto w-full">
                  Post it
                </Button>
              </div>
            </form>
          )}
        </motion.div>
      </div>
    </section>
  );
}
