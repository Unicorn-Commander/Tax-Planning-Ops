// SECURITY: tokens arrive in the URL FRAGMENT (backend/app/api/auth.py
// redirects to /auth/sso-callback#token=...). Fragments never reach a server,
// so they cannot land in proxy access logs or Referer headers. The query
// fallback below is a ONE-RELEASE bridge for browsers that were already
// mid-login (redirected with the old ?token= form) when this deploy shipped.
// REMOVE THE QUERY FALLBACK ONE RELEASE AFTER THIS SHIPS.

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
    replaceState: (state: unknown, title: string, url: string) => void;
  };
}

function browserWindow(): Window | null {
  return typeof window === "undefined" ? null : window;
}

export function parseTokenParams(
  win: WindowLike | null | undefined = browserWindow() as WindowLike | null,
): { token: string | null; refreshToken: string | null } {
  if (!win) return { token: null, refreshToken: null };
  const hash = win.location.hash;
  if (hash.length > 1) {
    const params = new URLSearchParams(hash.slice(1));
    return {
      token: params.get("token"),
      refreshToken: params.get("refresh_token"),
    };
  }
  // One-release fallback: the previous redirect put tokens in the query.
  const params = new URLSearchParams(win.location.search);
  return {
    token: params.get("token"),
    refreshToken: params.get("refresh_token"),
  };
}

export function cleanCallbackUrl(
  win: WindowLike | null | undefined = browserWindow() as WindowLike | null,
): string {
  if (!win) return "";
  // Strip the token-carrying hash/query from the URL immediately so a
  // back-button revisit or a third-party Referer cannot echo the tokens.
  const clean = new URL(win.location.href);
  clean.hash = "";
  clean.search = "";
  win.history.replaceState(win.history.state, "", clean.toString());
  return clean.toString();
}
