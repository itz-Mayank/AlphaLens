import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";

import { registerAccount } from "@/features/auth/api";
import { AuthLayout } from "@/features/auth/components/AuthLayout";
import { FormField } from "@/features/auth/components/FormField";
import { ApiError } from "@/lib/api-client";
import { type RegisterFormValues, registerSchema } from "@/lib/zod-schemas/auth";
import { useAuthStore } from "@/stores/authStore";

export function RegisterPage() {
  const navigate = useNavigate();
  const setSession = useAuthStore((s) => s.setSession);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<RegisterFormValues>({ resolver: zodResolver(registerSchema) });

  const mutation = useMutation({
    mutationFn: (values: RegisterFormValues) =>
      registerAccount({
        email: values.email,
        password: values.password,
        full_name: values.fullName,
      }),
    onSuccess: (data) => {
      setSession(data.user, data.access_token);
      navigate("/app", { replace: true });
    },
  });

  return (
    <AuthLayout title="Create your account" subtitle="Start exploring markets with AlphaLens.">
      <form
        className="flex flex-col gap-4"
        onSubmit={handleSubmit((values) => mutation.mutate(values))}
        noValidate
      >
        <FormField
          label="Full name"
          autoComplete="name"
          error={errors.fullName?.message}
          {...register("fullName")}
        />
        <FormField
          label="Email"
          type="email"
          autoComplete="email"
          error={errors.email?.message}
          {...register("email")}
        />
        <FormField
          label="Password"
          type="password"
          autoComplete="new-password"
          error={errors.password?.message}
          {...register("password")}
        />
        <FormField
          label="Confirm password"
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
          {mutation.isPending ? "Creating account…" : "Create account"}
        </button>
      </form>

      <p className="mt-4 text-center text-sm text-muted">
        Already have an account?{" "}
        <Link to="/login" className="text-foreground hover:underline">
          Log in
        </Link>
      </p>
    </AuthLayout>
  );
}
