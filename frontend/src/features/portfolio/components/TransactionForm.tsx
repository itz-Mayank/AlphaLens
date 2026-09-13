import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "@/lib/api-client";

import { createTransaction } from "../api";
import type { TransactionType } from "../types";

const KNOWN_ERROR_MESSAGES: Record<string, string> = {
  STOCK_NOT_FOUND: "That ticker isn't known to this deployment yet.",
  INSUFFICIENT_CASH: "This portfolio doesn't have enough cash for this purchase.",
  INSUFFICIENT_POSITION: "You can't sell more shares than you currently hold (no short selling).",
  VALIDATION_ERROR: "Please check the form values.",
};

const TYPE_OPTIONS: { value: TransactionType; label: string }[] = [
  { value: "BUY", label: "Buy" },
  { value: "SELL", label: "Sell" },
  { value: "CASH_DEPOSIT", label: "Deposit cash" },
  { value: "CASH_WITHDRAWAL", label: "Withdraw cash" },
];

export function TransactionForm({ portfolioId }: { portfolioId: string }) {
  const queryClient = useQueryClient();
  const [transactionType, setTransactionType] = useState<TransactionType>("BUY");
  const [ticker, setTicker] = useState("");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [amount, setAmount] = useState("");
  const [fees, setFees] = useState("0");

  const isSecurityTxn = transactionType === "BUY" || transactionType === "SELL";

  const mutation = useMutation({
    mutationFn: () =>
      createTransaction(portfolioId, {
        transaction_type: transactionType,
        ticker: isSecurityTxn ? ticker.trim().toUpperCase() : undefined,
        quantity: isSecurityTxn ? quantity : undefined,
        price: isSecurityTxn ? price : undefined,
        amount: isSecurityTxn ? undefined : amount,
        fees: isSecurityTxn ? fees || "0" : "0",
      }),
    onSuccess: () => {
      setTicker("");
      setQuantity("");
      setPrice("");
      setAmount("");
      setFees("0");
      queryClient.invalidateQueries({ queryKey: ["portfolios", portfolioId] });
    },
  });

  const canSubmit = isSecurityTxn
    ? Boolean(ticker.trim() && quantity && price)
    : Boolean(amount);

  const error = mutation.error;
  const errorMessage =
    error instanceof ApiError ? (KNOWN_ERROR_MESSAGES[error.code] ?? error.message) : null;

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs text-muted">Type</span>
          <select
            className="rounded border border-border bg-transparent px-2 py-1.5"
            value={transactionType}
            onChange={(e) => setTransactionType(e.target.value as TransactionType)}
          >
            {TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>

        {isSecurityTxn ? (
          <>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-muted">Ticker</span>
              <input
                className="rounded border border-border bg-transparent px-2 py-1.5 uppercase"
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                placeholder="AAPL"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-muted">Quantity</span>
              <input
                type="number"
                min={0}
                step="any"
                className="rounded border border-border bg-transparent px-2 py-1.5"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-muted">Price per share</span>
              <input
                type="number"
                min={0}
                step="any"
                className="rounded border border-border bg-transparent px-2 py-1.5"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-muted">Fees</span>
              <input
                type="number"
                min={0}
                step="any"
                className="rounded border border-border bg-transparent px-2 py-1.5"
                value={fees}
                onChange={(e) => setFees(e.target.value)}
              />
            </label>
          </>
        ) : (
          <label className="flex flex-col gap-1 text-sm sm:col-span-2">
            <span className="text-xs text-muted">Amount</span>
            <input
              type="number"
              min={0}
              step="any"
              className="rounded border border-border bg-transparent px-2 py-1.5"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </label>
        )}
      </div>

      <div>
        <button
          type="button"
          onClick={() => mutation.mutate()}
          disabled={!canSubmit || mutation.isPending}
          className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60"
        >
          {mutation.isPending ? "Recording…" : "Record transaction"}
        </button>
      </div>

      {errorMessage && <p className="text-sm text-bearish">{errorMessage}</p>}
    </div>
  );
}
