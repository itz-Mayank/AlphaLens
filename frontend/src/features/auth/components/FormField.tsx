import { forwardRef } from "react";
import type { InputHTMLAttributes } from "react";

interface FormFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
}

export const FormField = forwardRef<HTMLInputElement, FormFieldProps>(
  ({ label, error, id, ...inputProps }, ref) => {
    const inputId = id ?? inputProps.name;
    return (
      <div className="flex flex-col gap-1.5">
        <label htmlFor={inputId} className="text-sm font-medium text-foreground">
          {label}
        </label>
        <input
          {...inputProps}
          id={inputId}
          ref={ref}
          aria-invalid={Boolean(error)}
          className="rounded border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
        />
        {error && (
          <p className="text-xs text-bearish" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  },
);
FormField.displayName = "FormField";
