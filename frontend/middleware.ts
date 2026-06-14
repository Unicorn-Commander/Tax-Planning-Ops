import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Phase 3 — the v3 redesign is the app now. The old v1 routes are retained only
// as a safety net; this middleware redirects every one of them to its v3
// equivalent at the edge, so a bookmark, a history entry, or the post-login
// landing can never strand a user on the old UI.
//
// Mapping (v1 → v3):
//   /dashboard           → /            (the posture resolver: solo→/home, firm→/desk)
//   /clients             → /book
//   /clients/:id         → /c/:id       (Case File; analysis folds into it)
//   /clients/:id/profile → /c/:id/brief
//   /clients/:id/returns → /c/:id/return
//   /clients/:id/strategies | /quarterly | /pdf → /c/:id/plan
//   /clients/:id/business→ /c/:id/entities
//   /admin | /admin/*    → /playbook

const CLIENT_SUB: Record<string, string> = {
  "": "",
  "/analysis": "",
  "/profile": "/brief",
  "/returns": "/return",
  "/strategies": "/plan",
  "/quarterly": "/plan",
  "/pdf": "/plan",
  "/business": "/entities",
};

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (pathname === "/dashboard") return NextResponse.redirect(new URL("/", req.url));
  if (pathname === "/clients") return NextResponse.redirect(new URL("/book", req.url));

  const m = pathname.match(/^\/clients\/([^/]+)(\/[^/]+)?$/);
  if (m) {
    const id = m[1];
    const sub = CLIENT_SUB[m[2] ?? ""] ?? "";
    return NextResponse.redirect(new URL(`/c/${id}${sub}`, req.url));
  }

  if (pathname === "/admin" || pathname.startsWith("/admin/")) {
    return NextResponse.redirect(new URL("/playbook", req.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard", "/clients", "/clients/:path*", "/admin", "/admin/:path*"],
};
