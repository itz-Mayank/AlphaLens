import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { login } from "@/features/auth/api";
import { AuthLayout } from "@/features/auth/components/AuthLayout";
import { FormField } from "@/features/auth/components/FormField";
import { ApiError } from "@/lib/api-client";
import { type LoginFormValues, loginSchema } from "@/lib/zod-schemas/auth";
import { useAuthStore } from "@/stores/authStore";

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const setSession = useAuthStore((s) => s.setSession);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormValues>({ resolver: zodResolver(loginSchema) });

  const mutation = useMutation({
    mutationFn: login,
    onSuccess: (data) => {
      setSession(data.user, data.access_token);
      const state = location.state as { from?: { pathname?: string } } | null;
      navigate(state?.from?.pathname ?? "/app", { replace: true });
    },
  });

  return (
    <AuthLayout title="Log in" subtitle="Welcome back to AlphaLens.">
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
        <FormField
          label="Password"
          type="password"
          autoComplete="current-password"
          error={errors.password?.message}
          {...register("password")}
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
          {mutation.isPending ? "Logging in…" : "Log in"}
        </button>
      </form>

      <div className="mt-4 flex items-center justify-between text-sm text-muted">
        <Link to="/forgot-password" className="hover:text-foreground">
          Forgot password?
        </Link>
        <Link to="/register" className="hover:text-foreground">
          Create account
        </Link>
      </div>
    </AuthLayout>
  );
}
