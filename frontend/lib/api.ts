import axios from "axios";
import { WORKSPACE_HEADER_NAME, getStoredWorkspaceId } from "@/lib/workspace";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

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
  if (!refreshToken) return null;
  try {
    // Bare axios (not `api`) so this request bypasses the interceptors below and
    // can't recurse if it 401s itself.
    //
    // Bound the round-trip. The data fetch that triggered this refresh set its
    // own per-request timeout, but that timeout does NOT cover the time the
    // response interceptor below spends `await`-ing THIS call — so an
    // unbounded, hung /auth/refresh would freeze the awaiting request forever:
    // the file chrome sticks on "Loading…" with no 401 and no redirect (the
    // interceptor never reaches either branch). A finite timeout turns a hung
    // refresh into a definitive failure (returns null) so the caller's
    // retry-with-backoff / re-auth path actually runs.
    const res = await axios.post(
      `${API_BASE_URL}/auth/refresh`,
      { refresh_token: refreshToken },
      { timeout: 8000 },
    );
    const accessToken: string | undefined = res.data?.access_token;
    const rotated: string | undefined = res.data?.refresh_token;
    if (!accessToken) return null;
    localStorage.setItem("access_token", accessToken);
    if (rotated) localStorage.setItem("refresh_token", rotated);
    return accessToken;
  } catch {
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
  (response) => response,
  async (error) => {
    const original = error.config;
    const status = error.response?.status;
    if (status !== 401 || typeof window === "undefined" || !original) {
      return Promise.reject(error);
    }
    // Never try to refresh the refresh call itself, and retry a given request
    // only once.
    const isRefreshCall = String(original.url || "").includes("/auth/refresh");
    if (!isRefreshCall && !original._retried) {
      original._retried = true;
      const newToken = await getRefreshedToken();
      if (newToken) {
        // Request interceptor will re-stamp Authorization from localStorage,
        // but set it here too so the retry is self-contained.
        original.headers = original.headers ?? {};
        original.headers.Authorization = `Bearer ${newToken}`;
        return api(original);
      }
    }
    clearSessionAndRedirect();
    return Promise.reject(error);
  },
);

export default api;
