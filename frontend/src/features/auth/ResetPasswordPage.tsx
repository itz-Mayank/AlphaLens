import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, useSearchParams } from "react-router-dom";

import { resetPassword } from "@/features/auth/api";
import { AuthLayout } from "@/features/auth/components/AuthLayout";
import { FormField } from "@/features/auth/components/FormField";
import { ApiError } from "@/lib/api-client";
import { type ResetPasswordFormValues, resetPasswordSchema } from "@/lib/zod-schemas/auth";

export function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ResetPasswordFormValues>({ resolver: zodResolver(resetPasswordSchema) });

  const mutation = useMutation({
    mutationFn: (values: ResetPasswordFormValues) =>
      resetPassword({ token: token ?? "", new_password: values.password }),
  });

  if (!token) {
    return (
      <AuthLayout title="Invalid reset link">
        <p className="text-sm text-muted">
          This password reset link is missing its token. Request a new one below.
        </p>
        <Link
          to="/forgot-password"
          className="mt-6 inline-block text-sm font-medium text-primary hover:underline"
        >
          Request new link
        </Link>
      </AuthLayout>
    );
  }

  if (mutation.isSuccess) {
    return (
      <AuthLayout title="Password updated">
        <p className="text-sm text-muted">
          Your password has been reset. You can now log in with your new password.
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
    <AuthLayout title="Set a new password">
      <form
        className="flex flex-col gap-4"
        onSubmit={handleSubmit((values) => mutation.mutate(values))}
        noValidate
      >
        <FormField
          label="New password"
          type="password"
          autoComplete="new-password"
          error={errors.password?.message}
          {...register("password")}
        />
        <FormField
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          error={errors.confirmPassword?.message}
          {...register("confirmPassword")}
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
          {mutation.isPending ? "Updating…" : "Update password"}
        </button>
      </form>
    </AuthLayout>
  );
}
