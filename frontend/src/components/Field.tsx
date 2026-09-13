import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import clsx from "clsx";

const CONTROL_CLASSES =
  "w-full rounded border border-border bg-transparent px-2 py-1.5 text-sm text-foreground outline-none focus:border-primary";

interface FieldWrapProps {
  label: string;
  htmlFor: string;
  children: ReactNode;
  className?: string;
}

function FieldWrap({ label, htmlFor, children, className }: FieldWrapProps) {
  return (
    <div className={clsx("flex flex-col gap-1", className)}>
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted">
        {label}
      </label>
      {children}
    </div>
  );
}

/** Plain (non-react-hook-form) labeled text/number input for filter bars —
 * distinct from auth's FormField, which is bound to react-hook-form refs. */
export function TextField({
  label,
  id,
  className,
  ...props
}: { label: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <FieldWrap label={label} htmlFor={id ?? label}>
      <input id={id ?? label} className={clsx(CONTROL_CLASSES, className)} {...props} />
    </FieldWrap>
  );
}

export function SelectField({
  label,
  id,
  className,
  children,
  ...props
}: { label: string } & SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <FieldWrap label={label} htmlFor={id ?? label}>
      <select id={id ?? label} className={clsx(CONTROL_CLASSES, "cursor-pointer", className)} {...props}>
        {children}
      </select>
    </FieldWrap>
  );
}
