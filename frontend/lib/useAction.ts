"use client";

import { isAxiosError } from "axios";
import { useCallback, useState } from "react";

interface ApiErrorDetail {
  msg?: string;
}

function messageFrom(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return (detail as ApiErrorDetail[]).map((item) => item.msg ?? "invalid").join("; ");
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "Request failed";
}

/**
 * Wrap an async API call with pending + error state so every action button can
 * disable while in-flight and surface a failure inline (no more silent
 * unhandled rejections / double-submit).
 */
export function useAction<A extends unknown[], T>(fn: (...args: A) => Promise<T>) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (...args: A): Promise<T | undefined> => {
      setPending(true);
      setError(null);
      try {
        return await fn(...args);
      } catch (err) {
        setError(messageFrom(err));
        return undefined;
      } finally {
        setPending(false);
      }
    },
    [fn],
  );

  return { run, pending, error };
}
