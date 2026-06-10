export const logger = {
  log: (...args: unknown[]) => {
    if (process.env.NODE_ENV !== "production") {
      console.log(...args);
    }
  },
  warn: (...args: unknown[]) => console.warn(...args),
  error: (...args: unknown[]) => console.error(...args),
};
