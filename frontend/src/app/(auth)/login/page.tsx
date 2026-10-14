"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/store";
import type { TokenPair } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input, Label, FieldError } from "@/components/ui/input";
import { GoogleButton, OrDivider, googleSignInEnabled } from "@/components/auth/google-button";
import { FinishGoogleSignUp } from "@/components/auth/consent";

const schema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});

type FormValues = z.infer<typeof schema>;

export default function LoginPage() {
  const router = useRouter();
  const { setTokens, setUser } = useAuth();
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  // A Google credential for an address with no account yet, held while the
  // student agrees to the terms. Google's ID tokens stay valid for an hour.
  const [pendingGoogle, setPendingGoogle] = React.useState<string | null>(null);

  const signedIn = async (
    tokens: TokenPair,
    greeting = "Welcome back",
  ) => {
    setTokens(tokens.access_token, tokens.refresh_token);
    const user = tokens.user ?? (await api.me());
    setUser(user);
    toast.success(`${greeting}${user.full_name ? `, ${user.full_name}` : ""}!`);
    router.push("/dashboard");
  };

  const onGoogle = async (credential: string) => {
    try {
      await signedIn(await api.googleLogin(credential, false));
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setPendingGoogle(credential);
        return;
      }
      toast.error(err instanceof Error ? err.message : "Google sign-in failed.");
    }
  };

  const createFromGoogle = async () => {
    if (!pendingGoogle) return;
    try {
      await signedIn(await api.googleLogin(pendingGoogle, true), "Welcome to Oratio");
    } catch (err) {
      // An expired credential lands here; a fresh click on the button fixes it.
      setPendingGoogle(null);
      toast.error(
        err instanceof Error ? `${err.message} Please try Google again.` : "Google sign-up failed.",
      );
    }
  };

  const onSubmit = async (values: FormValues) => {
    try {
      await signedIn(await api.login(values.email, values.password));
    } catch (err) {
      const message =
        err instanceof ApiError && err.status === 401 && !/google/i.test(err.message)
          ? "Incorrect email or password."
          : err instanceof Error
            ? err.message
            : "Login failed.";
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
      <h1 className="font-display text-4xl font-medium tracking-tight">Welcome back</h1>
      <p className="mt-1.5 text-sm text-muted-foreground">
        Pick up where you left off.
      </p>

      <form onSubmit={handleSubmit(onSubmit)} className="mt-8 space-y-5" noValidate>
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
            autoComplete="current-password"
            placeholder="••••••••"
            {...register("password")}
          />
          <FieldError message={errors.password?.message} />
        </div>
        <Button type="submit" loading={isSubmitting} className="w-full" size="lg">
          Sign In
        </Button>
      </form>

      {googleSignInEnabled && (
        <>
          <OrDivider />
          {pendingGoogle ? (
            <FinishGoogleSignUp
              onCreate={createFromGoogle}
              onCancel={() => setPendingGoogle(null)}
            />
          ) : (
            <GoogleButton text="signin_with" onCredential={onGoogle} />
          )}
        </>
      )}

      <p className="mt-8 border-t border-border pt-6 text-sm text-muted-foreground">
        New here?{" "}
        <Link href="/register" className="font-medium text-foreground underline decoration-sun decoration-2 underline-offset-4 hover:text-primary">
          Create a free account
        </Link>
      </p>
    </motion.div>
  );
}
