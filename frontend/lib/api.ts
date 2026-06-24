import axios from "axios";
import { WORKSPACE_HEADER_NAME, getStoredWorkspaceId } from "@/lib/workspace";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

// [OVDBG] temporary cold-load instrumentation — REMOVE in the fix commit.
function OVDBG(tag: string, data: Record<string, unknown>): void {
  if (typeof window === "undefined") return;
  // eslint-disable-next-line no-console
  console.log(`[OVDBG] ${tag}`, JSON.stringify(data));
}
function ovWatched(url: unknown): boolean {
  const u = String(url || "");
  return u.includes("/overview") || u.includes("/me") || u.includes("/auth/refresh");
}

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    let token = localStorage.getItem("access_token");
    // Dev autologin: guarantee the token exists on the very first request so a
    // data fetch firing before the auth provider's effect can't race to a 401.
    if (!token && process.env.NEXT_PUBLIC_DEV_AUTOLOGIN === "1") {
      token = "dev";
      localStorage.setItem("access_token", "dev");
    }
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    const workspaceId = getStoredWorkspaceId();
    if (workspaceId && !config.headers[WORKSPACE_HEADER_NAME]) {
      config.headers[WORKSPACE_HEADER_NAME] = workspaceId;
    }
    if (ovWatched(config.url)) {
      OVDBG("request.out", {
        url: config.url,
        hasToken: Boolean(token),
        tokenLen: token ? token.length : 0,
        ws: workspaceId,
        retried: Boolean((config as { _retried?: boolean })._retried),
      });
    }
  }
  return config;
});

// --- silent access-token refresh -------------------------------------------
// Keycloak access tokens are short-lived; rather than bounce the user to
// /auth/login the moment one expires, we exchange the stored refresh token for
// a fresh access token (backend POST /auth/refresh) and transparently retry the
// failed request. Only a genuinely dead SSO session (refresh fails / no refresh
// token) sends the user to log in.

let refreshInFlight: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken =
    typeof window !== "undefined" ? localStorage.getItem("refresh_token") : null;
  OVDBG("refresh.start", { hasRefreshToken: Boolean(refreshToken) });
  if (!refreshToken) return null;
  try {
    // Bare axios (not `api`) so this request bypasses the interceptors below and
    // can't recurse if it 401s itself.
    const res = await axios.post(`${API_BASE_URL}/auth/refresh`, {
      refresh_token: refreshToken,
    });
    const accessToken: string | undefined = res.data?.access_token;
    const rotated: string | undefined = res.data?.refresh_token;
    OVDBG("refresh.ok", {
      status: res.status,
      hasAccess: Boolean(accessToken),
      accessLen: accessToken ? accessToken.length : 0,
      rotated: Boolean(rotated),
    });
    if (!accessToken) return null;
    localStorage.setItem("access_token", accessToken);
    if (rotated) localStorage.setItem("refresh_token", rotated);
    return accessToken;
  } catch (e) {
    const err = e as { response?: { status?: number }; code?: string; message?: string };
    OVDBG("refresh.FAIL", { status: err?.response?.status, code: err?.code, msg: err?.message });
    return null;
  }
}

// Collapse concurrent 401s onto a single refresh round-trip.
function getRefreshedToken(): Promise<string | null> {
  if (!refreshInFlight) {
    refreshInFlight = refreshAccessToken().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

function clearSessionAndRedirect(): void {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("user");
  window.location.href = "/auth/login";
}

api.interceptors.response.use(
  (response) => {
    if (ovWatched(response.config?.url)) {
      OVDBG("response.ok", { url: response.config?.url, status: response.status });
    }
    return response;
  },
  async (error) => {
    const original = error.config;
    const status = error.response?.status;
    if (ovWatched(original?.url)) {
      OVDBG("response.err", {
        url: original?.url,
        status,
        code: error?.code,
        msg: error?.message,
        retried: Boolean(original?._retried),
      });
    }
    if (status !== 401 || typeof window === "undefined" || !original) {
      OVDBG("interceptor.reject-no-redirect", { url: original?.url, status, code: error?.code });
      return Promise.reject(error);
    }
    // Never try to refresh the refresh call itself, and retry a given request
    // only once.
    const isRefreshCall = String(original.url || "").includes("/auth/refresh");
    if (!isRefreshCall && !original._retried) {
      original._retried = true;
      const newToken = await getRefreshedToken();
      OVDBG("interceptor.afterRefresh", { url: original?.url, gotToken: Boolean(newToken) });
      if (newToken) {
        // Request interceptor will re-stamp Authorization from localStorage,
        // but set it here too so the retry is self-contained.
        original.headers = original.headers ?? {};
        original.headers.Authorization = `Bearer ${newToken}`;
        OVDBG("interceptor.retry.start", { url: original?.url });
        return api(original).then(
          (r) => {
            OVDBG("interceptor.retry.RESOLVED", { url: original?.url, status: r.status });
            return r;
          },
          (e) => {
            OVDBG("interceptor.retry.REJECTED", {
              url: original?.url,
              status: e?.response?.status,
              code: e?.code,
              msg: e?.message,
            });
            throw e;
          },
        );
      }
    }
    OVDBG("interceptor.clearSessionAndRedirect", { url: original?.url, isRefreshCall, retried: Boolean(original?._retried) });
    clearSessionAndRedirect();
    return Promise.reject(error);
  },
);

export default api;
