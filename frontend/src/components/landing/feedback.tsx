"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { CheckCircle2, MessageSquareHeart, Star } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Input, Label, FieldError, Textarea } from "@/components/ui/input";
import { fadeUp, staggerContainer } from "@/lib/motion";
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
      toast.success("Thank you — your feedback is in.");
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
    <section id="feedback" className="relative py-24">
      <div className="mx-auto max-w-3xl px-6">
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-80px" }}
          className="text-center"
        >
          <motion.div
            variants={fadeUp}
            className="glass mx-auto flex size-14 items-center justify-center rounded-2xl shadow-soft"
          >
            <MessageSquareHeart className="size-7 text-primary" aria-hidden />
          </motion.div>
          <motion.h2
            variants={fadeUp}
            className="mt-6 font-display text-3xl font-bold tracking-tight sm:text-5xl"
          >
            We&apos;re in <span className="text-gradient">pilot testing</span>
          </motion.h2>
          <motion.p
            variants={fadeUp}
            className="mx-auto mt-4 max-w-xl text-muted-foreground"
          >
            Something broken, confusing, or missing? Tell us here. Leave your
            email and we&apos;ll follow up personally.
          </motion.p>
        </motion.div>

        <motion.div
          variants={fadeUp}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          className="glass-strong mt-10 rounded-[28px] p-7 shadow-soft sm:p-9"
        >
          {sent ? (
            <div className="py-6 text-center">
              <CheckCircle2 className="mx-auto size-12 text-success" aria-hidden />
              <h3 className="mt-4 font-display text-xl font-semibold">
                Got it — thank you.
              </h3>
              <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
                Your notes go straight to the team building this. If we need
                more detail, we&apos;ll write to you.
              </p>
              <Button variant="secondary" className="mt-6" onClick={sendAnother}>
                Send another
              </Button>
            </div>
          ) : (
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-5" noValidate>
              <div>
                <Label htmlFor="feedback-email">Your email</Label>
                <Input
                  id="feedback-email"
                  type="email"
                  autoComplete="email"
                  placeholder="you@gmail.com"
                  readOnly={account !== null}
                  className={cn(account !== null && "cursor-not-allowed opacity-70")}
                  {...register("email")}
                />
                <FieldError message={errors.email?.message} />
                <p className="mt-1.5 text-xs text-muted-foreground">
                  {account !== null
                    ? "Taken from the account you're signed in with."
                    : "Only used to reply about this feedback."}
                </p>
              </div>

              <div>
                <Label htmlFor="feedback-message">Your feedback</Label>
                <Textarea
                  id="feedback-message"
                  rows={5}
                  maxLength={MAX_MESSAGE}
                  placeholder="What did you try, and what happened? Which part felt off?"
                  {...messageField}
                  onChange={(e) => {
                    setMessageLength(e.target.value.length);
                    return onMessageChange(e);
                  }}
                />
                <div className="flex items-start justify-between gap-4">
                  <FieldError message={errors.message?.message} />
                  <p className="mt-1.5 ml-auto shrink-0 text-xs text-muted-foreground">
                    {messageLength}/{MAX_MESSAGE}
                  </p>
                </div>
              </div>

              <div>
                <Label htmlFor="feedback-rating">
                  How is it so far?{" "}
                  <span className="font-normal text-muted-foreground">(optional)</span>
                </Label>
                <div
                  id="feedback-rating"
                  role="radiogroup"
                  aria-label="Overall rating"
                  className="flex items-center gap-1"
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
                        className="rounded-lg p-1 transition-transform hover:scale-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                      >
                        <Star
                          className={cn(
                            "size-6 transition-colors",
                            lit ? "fill-warning text-warning" : "text-muted-foreground/40"
                          )}
                          aria-hidden
                        />
                      </button>
                    );
                  })}
                </div>
              </div>

              <Button type="submit" loading={isSubmitting} size="lg" className="w-full">
                Send Feedback
              </Button>
            </form>
          )}
        </motion.div>
      </div>
    </section>
  );
}
