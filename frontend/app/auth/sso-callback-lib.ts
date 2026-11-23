// SECURITY: tokens arrive ONLY in the URL FRAGMENT (backend/app/api/auth.py
// redirects to /auth/sso-callback#token=...). Fragments never reach a server,
// so they cannot land in proxy access logs or Referer headers. Tokens are
// never read from the query string: a ?token= in the URL is a leak, so it is
// stripped and ignored. The fragment is read ONCE at module load (before
// React renders) so the tokens are gone from the address bar on first paint.

export interface WindowLike {
  location: {
    href: string;
    pathname: string;
    search: string;
    hash: string;
  };
  history: {
    state: unknown;
    calls: Array<[unknown, string, string]>;
    replaceState: (state: unknown, title: string, url: void | string) => void;
  };
}

export interface CallbackTokens {
  token: string | null;
  refreshToken: string | null;
}

function browserWindow(): Window | null {
  return typeof window === "undefined" ? null : window;
}

export function parseTokenParams(
  win: WindowLike | null | undefined = browserWindow() as WindowLike | null,
): CallbackTokens {
  if (!win) return { token: null, refreshToken: null };
  const hash = win.location.hash;
  if (hash.length > 1) {
    const params = new URLSearchParams(hash.slice(1));
    return {
      token: params.get("token"),
      refreshToken: params.get("refresh_token"),
    };
  }
  // No fragment: never fall back to the query. A token in the query string is
  // a leak (proxy logs, history, Referer), so it is ignored here and stripped
  // from the URL by cleanCallbackUrl.
  return { token: null, refreshToken: null };
}

export function cleanCallbackUrl(
  win: WindowLike | null | undefined = browserWindow() as WindowLike | null,
): string {
  if (!win) return "";
  // Strip the token-carrying hash AND the (leaked) query from the URL
  // immediately so a back-button revisit or a third-party Referer cannot echo
  // the tokens.
  const clean = new URL(win.location.href);
  clean.hash = "";
  clean.search = "";
  win.history.replaceState(win.history.state, "", clean.toString());
  return clean.toString();
}
