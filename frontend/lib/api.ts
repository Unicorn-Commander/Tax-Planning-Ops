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

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("access_token");
      localStorage.removeItem("user");
      window.location.href = "/auth/login";
    }
    return Promise.reject(error);
  },
);

export default api;
