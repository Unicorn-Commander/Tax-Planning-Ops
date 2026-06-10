import { ShieldCheck } from "lucide-react";

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <section className="w-full max-w-md rounded-lg border border-[var(--line)] bg-[var(--panel)] p-6 shadow-sm">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-[var(--accent)] text-white">
            <ShieldCheck className="h-5 w-5" aria-hidden />
          </div>
          <div>
            <h1 className="text-xl font-semibold">Tax-Planning-Ops</h1>
            <p className="text-sm text-[var(--muted)]">Unicorn Commander sign-in</p>
          </div>
        </div>
        <a
          href={`${apiUrl}/auth/keycloak`}
          className="flex h-11 w-full items-center justify-center rounded-md bg-[var(--accent)] px-4 text-sm font-medium text-white hover:bg-[var(--accent-strong)]"
        >
          Continue with Keycloak
        </a>
      </section>
    </main>
  );
}
