interface ErrorStateProps {
  message?: string;
  onRetry?: () => void;
}

export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-bearish/30 bg-bearish/5 py-12 text-center">
      <p className="text-sm font-medium text-bearish">
        {message ?? "Something went wrong loading this data."}
      </p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded border border-border px-3 py-1.5 text-sm text-foreground hover:bg-border/40"
        >
          Retry
        </button>
      )}
    </div>
  );
}
