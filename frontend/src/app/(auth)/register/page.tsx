"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Input, Label, FieldError } from "@/components/ui/input";
import { GoogleButton, OrDivider, googleSignInEnabled } from "@/components/auth/google-button";
import { ConsentText } from "@/components/auth/consent";

const schema = z.object({
  full_name: z.string().min(2, "Tell us your name"),
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(8, "At least 8 characters").max(72, "At most 72 characters"),
  target_band: z
    .number({ message: "Between 4.0 and 9.0" })
    .min(4, "Between 4.0 and 9.0")
    .max(9, "Between 4.0 and 9.0"),
  accept_terms: z.literal(true, {
    message: "Please read and accept the Terms and Privacy Policy",
  }),
});

type FormValues = z.infer<typeof schema>;

export default function RegisterPage() {
  const router = useRouter();
  const { setTokens, setUser } = useAuth();
  const {
    register,
    handleSubmit,
    control,
    setError,
    clearErrors,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { target_band: 7, accept_terms: false as unknown as true },
  });

  const accepted = useWatch({ control, name: "accept_terms" }) === true;

  // A Google credential that came back before the consent box was ticked.
  // Google's ID tokens stay valid for an hour, so it is held, not thrown away.
  const [pendingGoogle, setPendingGoogle] = React.useState<string | null>(null);
  const [googleBusy, setGoogleBusy] = React.useState(false);

  React.useEffect(() => {
    if (accepted) clearErrors("accept_terms");
  }, [accepted, clearErrors]);

  const createFromGoogle = async (credential: string) => {
    setGoogleBusy(true);
    try {
      const tokens = await api.googleLogin(credential, true);
      setTokens(tokens.access_token, tokens.refresh_token);
      const user = await api.me();
      setUser(user);
      toast.success(`Welcome to Oratio${user.full_name ? `, ${user.full_name}` : ""}!`);
      router.push("/dashboard");
    } catch (err) {
      setPendingGoogle(null);
      toast.error(
        err instanceof Error ? `${err.message} Please try Google again.` : "Google sign-up failed.",
      );
    } finally {
      setGoogleBusy(false);
    }
  };

  const onGoogle = (credential: string) => {
    if (accepted) {
      void createFromGoogle(credential);
      return;
    }
    setPendingGoogle(credential);
    setError("accept_terms", { message: "Tick this box to finish signing up with Google." });
    document.getElementById("accept_terms")?.focus();
  };

  const onSubmit = async (values: FormValues) => {
    try {
      await api.register(values);
      const tokens = await api.login(values.email, values.password);
      setTokens(tokens.access_token, tokens.refresh_token);
      const user = await api.me();
      setUser(user);
      toast.success("Account created — welcome aboard!");
      router.push("/dashboard");
    } catch (err) {
      const message =
        err instanceof ApiError && err.status === 409
          ? "That email is already registered."
          : err instanceof Error
            ? err.message
            : "Registration failed.";
      toast.error(message);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      className="w-full max-w-sm"
    >
      <h1 className="font-display text-4xl font-medium tracking-tight">
        Create your account
      </h1>
      <p className="mt-1.5 text-sm text-muted-foreground">
        Free to start. Your first mock test is a few minutes away.
      </p>

      <form onSubmit={handleSubmit(onSubmit)} className="mt-8 space-y-5" noValidate>
        <div>
          <Label htmlFor="full_name">Full name</Label>
          <Input id="full_name" autoComplete="name" placeholder="Aisha Rahman" {...register("full_name")} />
          <FieldError message={errors.full_name?.message} />
        </div>
        <div>
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            {...register("email")}
          />
          <FieldError message={errors.email?.message} />
        </div>
        <div>
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            placeholder="At least 8 characters"
            {...register("password")}
          />
          <FieldError message={errors.password?.message} />
        </div>
        <div>
          <Label htmlFor="target_band">Target band</Label>
          <Input
            id="target_band"
            type="number"
            step="0.5"
            min="4"
            max="9"
            {...register("target_band", { valueAsNumber: true })}
          />
          <FieldError message={errors.target_band?.message} />
        </div>
        <div>
          <label htmlFor="accept_terms" className="flex items-start gap-3 text-sm leading-relaxed text-muted-foreground">
            <input
              id="accept_terms"
              type="checkbox"
              className="mt-1 size-4 shrink-0 accent-[var(--primary)]"
              {...register("accept_terms")}
            />
            <ConsentText />
          </label>
          <FieldError message={errors.accept_terms?.message} />
        </div>
        <Button type="submit" loading={isSubmitting} className="w-full" size="lg">
          Create account
        </Button>
      </form>

      {googleSignInEnabled && (
        <>
          <OrDivider />
          {pendingGoogle ? (
            <Button
              type="button"
              className="w-full"
              size="lg"
              disabled={!accepted}
              loading={googleBusy}
              onClick={() => createFromGoogle(pendingGoogle)}
            >
              Finish signing up with Google
            </Button>
          ) : (
            <GoogleButton text="signup_with" onCredential={onGoogle} />
          )}
        </>
      )}

      <p className="mt-8 border-t border-border pt-6 text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-foreground underline decoration-sun decoration-2 underline-offset-4 hover:text-primary">
          Sign in
        </Link>
      </p>
    </motion.div>
  );
}
