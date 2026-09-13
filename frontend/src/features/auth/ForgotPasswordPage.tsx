import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";

import { forgotPassword } from "@/features/auth/api";
import { AuthLayout } from "@/features/auth/components/AuthLayout";
import { FormField } from "@/features/auth/components/FormField";
import { ApiError } from "@/lib/api-client";
import { type ForgotPasswordFormValues, forgotPasswordSchema } from "@/lib/zod-schemas/auth";

export function ForgotPasswordPage() {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ForgotPasswordFormValues>({ resolver: zodResolver(forgotPasswordSchema) });

  const mutation = useMutation({ mutationFn: forgotPassword });

  if (mutation.isSuccess) {
    return (
      <AuthLayout title="Check your email">
        <p className="text-sm text-muted">
          If an account exists for that email address, we've sent a link to reset your password.
        </p>
        <Link
          to="/login"
          className="mt-6 inline-block text-sm font-medium text-primary hover:underline"
        >
          Back to log in
        </Link>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Reset your password"
      subtitle="Enter your email and we'll send you a reset link."
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={handleSubmit((values) => mutation.mutate(values))}
        noValidate
      >
        <FormField
          label="Email"
          type="email"
          autoComplete="email"
          error={errors.email?.message}
          {...register("email")}
        />

        {mutation.isError && (
          <p className="text-sm text-bearish" role="alert">
            {mutation.error instanceof ApiError
              ? mutation.error.message
              : "Something went wrong. Please try again."}
          </p>
        )}

        <button
          type="submit"
          disabled={mutation.isPending}
          className="mt-2 rounded bg-primary px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {mutation.isPending ? "Sending…" : "Send reset link"}
        </button>
      </form>

      <p className="mt-4 text-center text-sm text-muted">
        <Link to="/login" className="text-foreground hover:underline">
          Back to log in
        </Link>
      </p>
    </AuthLayout>
  );
}
