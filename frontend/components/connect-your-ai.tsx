"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Check, Clipboard, KeyRound, Plug, RefreshCw, ShieldCheck } from "lucide-react";
import { isAxiosError } from "axios";
import api from "@/lib/api";
import { Button, Chip, Panel, PanelHead } from "@/components/kit";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
const PATS_PATH = "/auth/pats";
const MCP_CLIENT_NAME = "tax-planning-ops";

/** The frontend has one API-base config; the MCP door is the same origin + path. */
export function mcpUrlFromApiBase(apiBaseUrl: string = API_BASE_URL): string {
  const base = apiBaseUrl.replace(/\/+$/, "");
  return base.endsWith("/api/v1") ? `${base}/mcp` : `${base}/api/v1/mcp`;
}

interface PersonalAccessToken {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  workspace_scope: string[] | null;
  created_at: string | null;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  state: "active" | "expired" | "revoked";
}

interface CreatePATResponse {
  id: string;
  name: string;
  secret: string;
  prefix: string;
  scopes: string[];
  workspace_scope: string[] | null;
  expires_at: string | null;
  created_at: string;
}

interface TokenReveal {
  name: string;
  prefix: string;
  secret: string;
}

type ClientTab = "claude-code" | "claude-desktop" | "chatgpt" | "other";

const CLIENT_TABS: { id: ClientTab; label: string }[] = [
  { id: "claude-code", label: "Claude Code" },
  { id: "claude-desktop", label: "Claude Desktop / claude.ai" },
  { id: "chatgpt", label: "ChatGPT" },
  { id: "other", label: "Cursor / Codex / other" },
];

function apiErrorMessage(error: unknown, fallback: string): string {
  if (!isAxiosError(error)) return fallback;
  switch (error.response?.status) {
    case 401:
      return "Your session has expired. Sign in again and retry.";
    case 403:
      return "This action is not available for the current session.";
    case 404:
      return "The token service is not available on this ring yet.";
    case 429:
      return "You have reached the active-token limit. Revoke a token before creating another.";
    default:
      return fallback;
  }
}

function scopeLabel(scope: string): string {
  return scope
    .replace(/^taxplan:/, "")
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

function tokenState(token: PersonalAccessToken): PersonalAccessToken["state"] {
  if (token.revoked_at) return "revoked";
  if (token.expires_at && new Date(token.expires_at).valueOf() <= Date.now()) return "expired";
  return token.state;
}

function CodeBlock({ value, children }: { value: string; children?: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-[10px] border border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-3 py-2.5">
      <code className="fig min-w-0 flex-1 whitespace-pre-wrap break-words text-[12px] leading-relaxed text-[var(--g-ink-2)]">
        {children ?? value}
      </code>
      <CopyButton value={value} />
    </div>
  );
}

function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  async function copy() {
    if (!navigator.clipboard) {
      setFailed(true);
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setFailed(false);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setFailed(true);
    }
  }

  return (
    <button
      type="button"
      onClick={() => void copy()}
      className="shrink-0 rounded-[8px] border border-[var(--g-hairline)] bg-[var(--g-surface)] px-2.5 py-1.5 text-[11px] font-semibold text-[var(--g-ink-2)] transition-colors hover:bg-[var(--g-bg)]"
      aria-label={`${label} snippet`}
      title={failed ? "Copy failed" : undefined}
    >
      {copied ? <Check className="inline h-3.5 w-3.5" aria-hidden /> : <Clipboard className="inline h-3.5 w-3.5" aria-hidden />}{" "}
      {copied ? "Copied" : failed ? "Retry" : label}
    </button>
  );
}

function ConnectYourAiPanel() {
  const [tab, setTab] = useState<ClientTab>("claude-code");
  const mcpUrl = mcpUrlFromApiBase();
  const oauthCommand = `claude mcp add --transport http ${MCP_CLIENT_NAME} ${mcpUrl}`;
  const tokenCommand = `${oauthCommand} --header "Authorization: Bearer tpo_pat_…"`;
  const oauthJson = JSON.stringify(
    {
      mcpServers: {
        [MCP_CLIENT_NAME]: {
          type: "http",
          url: mcpUrl,
        },
      },
    },
    null,
    2,
  );
  const tokenJson = JSON.stringify(
    {
      mcpServers: {
        [MCP_CLIENT_NAME]: {
          type: "http",
          url: mcpUrl,
          headers: { Authorization: "Bearer tpo_pat_…" },
        },
      },
    },
    null,
    2,
  );

  return (
    <Panel className="rise overflow-hidden">
      <PanelHead>
        <span className="grid h-7 w-7 place-items-center rounded-[8px] bg-[var(--agent-soft)] text-[var(--agent)]">
          <Plug className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <div className="text-[14px] font-semibold leading-tight text-[var(--g-ink)]">Connect your AI</div>
          <div className="mt-0.5 text-[12px] text-[var(--g-ink-3)]">Use the MCP door from an agent client</div>
        </div>
        <Chip tone="agent" className="ml-auto">MCP / API</Chip>
      </PanelHead>

      <div className="space-y-5 p-5">
        <div className="rounded-[10px] border border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-3.5 py-3">
          <div className="microlabel">Canonical MCP URL</div>
          <div className="mt-1.5 flex items-start gap-2">
            <code className="fig min-w-0 flex-1 break-all text-[12px] text-[var(--g-ink-2)]">{mcpUrl}</code>
            <CopyButton value={mcpUrl} label="Copy URL" />
          </div>
          <p className="mt-2 text-[11.5px] leading-relaxed text-[var(--g-ink-3)]">
            This URL follows the configured <code className="fig">NEXT_PUBLIC_API_URL</code> for the current ring.
          </p>
        </div>

        <div>
          <div className="flex gap-1 overflow-x-auto border-b border-[var(--g-hairline)]" role="tablist" aria-label="AI client setup">
            {CLIENT_TABS.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={tab === item.id}
                onClick={() => setTab(item.id)}
                className={
                  "shrink-0 border-b-2 px-3 py-2 text-left text-[12px] font-semibold transition-colors " +
                  (tab === item.id
                    ? "border-[var(--agent)] text-[var(--agent)]"
                    : "border-transparent text-[var(--g-ink-3)] hover:text-[var(--g-ink)]")
                }
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="space-y-4 pt-4" role="tabpanel">
            {tab === "claude-code" ? (
              <>
                <div>
                  <div className="microlabel">OAuth setup</div>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--g-ink-2)]">
                    Run this command. A browser window asks you to sign in.
                  </p>
                  <div className="mt-2"><CodeBlock value={oauthCommand} /></div>
                </div>
                <div>
                  <div className="microlabel">or paste a token</div>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--g-ink-2)]">
                    Use a PAT when the client cannot complete the browser sign-in.
                  </p>
                  <div className="mt-2"><CodeBlock value={tokenCommand} /></div>
                </div>
              </>
            ) : null}

            {tab === "claude-desktop" ? (
              <>
                <div>
                  <div className="microlabel">OAuth setup</div>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--g-ink-2)]">
                    Settings → Connectors → Add custom connector → URL. Sign-in appears in the browser.
                  </p>
                  <div className="mt-2"><CodeBlock value={mcpUrl} /></div>
                </div>
                <div>
                  <div className="microlabel">Token setup</div>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--g-ink-2)]">
                    If your client offers a bearer-token field, paste a token created below.
                  </p>
                </div>
              </>
            ) : null}

            {tab === "chatgpt" ? (
              <>
                <div>
                  <div className="microlabel">OAuth setup</div>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--g-ink-2)]">
                    Settings → Connectors → Developer mode → New connector → URL. Sign-in appears when ChatGPT connects.
                  </p>
                  <div className="mt-2"><CodeBlock value={mcpUrl} /></div>
                </div>
                <p className="text-[12px] leading-relaxed text-[var(--g-ink-3)]">
                  If this client asks for a token instead, create one below and use its one-time reveal.
                </p>
              </>
            ) : null}

            {tab === "other" ? (
              <>
                <div>
                  <div className="microlabel">OAuth setup</div>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--g-ink-2)]">
                    Use the URL-only form when the client supports MCP sign-in. It will open a browser window.
                  </p>
                  <div className="mt-2"><CodeBlock value={oauthJson} /></div>
                </div>
                <div>
                  <div className="microlabel">Token form</div>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--g-ink-2)]">
                    For a client that needs a bearer header, replace the placeholder with the token revealed once below.
                  </p>
                  <div className="mt-2"><CodeBlock value={tokenJson} /></div>
                </div>
              </>
            ) : null}
          </div>
        </div>

        <p className="flex items-start gap-2 border-t border-[var(--g-hairline-soft)] pt-4 text-[12px] leading-relaxed text-[var(--g-ink-3)]">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-[var(--agent)]" />
          <span>Your AI gets your permissions and nothing more; revoke any time below.</span>
        </p>
      </div>
    </Panel>
  );
}

function PersonalAccessTokensCard() {
  const [tokens, setTokens] = useState<PersonalAccessToken[]>([]);
  const [scopeOptions, setScopeOptions] = useState<string[]>([]);
  const [selectedScopes, setSelectedScopes] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [ttlDays, setTtlDays] = useState("90");
  const [loading, setLoading] = useState(true);
  const [loadingScopes, setLoadingScopes] = useState(true);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [scopeError, setScopeError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [confirmRevokeId, setConfirmRevokeId] = useState<string | null>(null);
  const [reveal, setReveal] = useState<TokenReveal | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<PersonalAccessToken[]>(PATS_PATH)
      .then((response) => {
        if (!cancelled) setTokens(Array.isArray(response.data) ? response.data : []);
      })
      .catch((error: unknown) => {
        if (!cancelled) setTokenError(apiErrorMessage(error, "Couldn’t load your API tokens."));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .get<{ scopes?: unknown }>("/me")
      .then((response) => {
        if (cancelled) return;
        const scopes = Array.isArray(response.data?.scopes)
          ? response.data.scopes.filter((scope): scope is string => typeof scope === "string" && scope.startsWith("taxplan:"))
          : [];
        const uniqueScopes = [...new Set(scopes)].sort();
        setScopeOptions(uniqueScopes);
        setSelectedScopes(uniqueScopes);
      })
      .catch((error: unknown) => {
        if (!cancelled) setScopeError(apiErrorMessage(error, "Couldn’t load the scopes available to this account."));
      })
      .finally(() => {
        if (!cancelled) setLoadingScopes(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function mintToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    const trimmedName = name.trim();
    if (!trimmedName) {
      setFormError("Give this token a name so you can recognize it later.");
      return;
    }
    if (selectedScopes.length === 0) {
      setFormError("Select at least one permission for this token.");
      return;
    }

    setCreating(true);
    try {
      const response = await api.post<CreatePATResponse>(PATS_PATH, {
        name: trimmedName,
        scopes: selectedScopes,
        ttl_days: Number(ttlDays),
      });
      const created = response.data;
      const createdToken: PersonalAccessToken = {
        id: created.id,
        name: created.name,
        prefix: created.prefix,
        scopes: created.scopes,
        workspace_scope: created.workspace_scope,
        created_at: created.created_at,
        last_used_at: null,
        expires_at: created.expires_at,
        revoked_at: null,
        state: "active",
      };
      setTokens((current) => [createdToken, ...current]);
      setReveal({ name: created.name, prefix: created.prefix, secret: created.secret });
      setName("");
    } catch (error: unknown) {
      setFormError(apiErrorMessage(error, "Couldn’t create that token."));
    } finally {
      setCreating(false);
    }
  }

  async function revokeToken(id: string) {
    setRevokingId(id);
    setTokenError(null);
    try {
      const response = await api.delete<{ revoked_at?: string }>(`${PATS_PATH}/${encodeURIComponent(id)}`);
      setTokens((current) =>
        current.map((token) =>
          token.id === id
            ? { ...token, state: "revoked", revoked_at: response.data?.revoked_at ?? new Date().toISOString() }
            : token,
        ),
      );
      setConfirmRevokeId(null);
    } catch (error: unknown) {
      setTokenError(apiErrorMessage(error, "Couldn’t revoke that token."));
    } finally {
      setRevokingId(null);
    }
  }

  const activeTokens = tokens.filter((token) => tokenState(token) === "active").length;

  return (
    <Panel className="rise overflow-hidden">
      <PanelHead>
        <span className="grid h-7 w-7 place-items-center rounded-[8px] bg-[var(--agent-soft)] text-[var(--agent)]">
          <KeyRound className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <div className="text-[14px] font-semibold leading-tight text-[var(--g-ink)]">API tokens</div>
          <div className="mt-0.5 text-[12px] text-[var(--g-ink-3)]">Durable access for MCP clients</div>
        </div>
        <span className="ml-auto text-[11px] text-[var(--g-ink-3)]">{activeTokens} active</span>
      </PanelHead>

      <div className="space-y-5 p-5">
        <p className="text-[13px] leading-relaxed text-[var(--g-ink-2)]">
          Create a token only for a client that cannot use MCP sign-in. The secret is shown once, never stored in this
          page, and never logged. Each token is limited to the permissions you select and expires after the chosen time.
        </p>

        {reveal ? (
          <div className="rounded-[12px] border border-[color-mix(in_srgb,var(--seal)_45%,transparent)] bg-[var(--seal-soft)] p-4">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="microlabel text-[var(--seal)]">Save this token now</div>
                <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--g-ink-2)]">
                  <b>{reveal.name}</b> will not be shown again after you dismiss this reveal.
                </p>
              </div>
              <Chip tone="seal">one-time reveal</Chip>
            </div>
            <div className="mt-3 flex items-start gap-2 rounded-[9px] border border-[var(--g-hairline)] bg-[var(--g-surface)] px-3 py-2.5">
              <code className="fig min-w-0 flex-1 break-all text-[12px] text-[var(--g-ink)]">{reveal.secret}</code>
              <CopyButton value={reveal.secret} label="Copy token" />
            </div>
            <p className="mt-2 text-[11.5px] text-[var(--g-ink-3)]">Prefix: <code className="fig">{reveal.prefix}</code></p>
            <Button type="button" variant="seal" className="mt-3 text-[12px]" onClick={() => setReveal(null)}>
              I’ve saved it
            </Button>
          </div>
        ) : null}

        <form className="space-y-4 rounded-[12px] border border-[var(--g-hairline)] bg-[var(--g-bg-2)] p-4" onSubmit={(event) => void mintToken(event)}>
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_180px]">
            <label className="block">
              <span className="microlabel">Token name</span>
              <input
                type="text"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. claude-code-laptop"
                maxLength={100}
                className="mt-1.5 h-10 w-full rounded-[10px] border border-[var(--g-hairline)] bg-[var(--g-surface)] px-3 text-[14px] text-[var(--g-ink)] outline-none transition-colors focus:border-[var(--agent)]"
              />
            </label>
            <label className="block">
              <span className="microlabel">Expires after</span>
              <select
                value={ttlDays}
                onChange={(event) => setTtlDays(event.target.value)}
                className="mt-1.5 h-10 w-full rounded-[10px] border border-[var(--g-hairline)] bg-[var(--g-surface)] px-3 text-[13px] text-[var(--g-ink)] outline-none focus:border-[var(--agent)]"
              >
                <option value="30">30 days</option>
                <option value="90">90 days (default)</option>
                <option value="180">180 days</option>
                <option value="365">365 days</option>
                <option value="0">Never</option>
              </select>
            </label>
          </div>

          <fieldset>
            <legend className="microlabel">Permissions</legend>
            {loadingScopes ? (
              <p className="mt-2 text-[12px] text-[var(--g-ink-3)]">Loading permissions…</p>
            ) : scopeError ? (
              <p className="mt-2 text-[12px] text-[var(--cliff)]">{scopeError}</p>
            ) : scopeOptions.length === 0 ? (
              <p className="mt-2 text-[12px] text-[var(--g-ink-3)]">No grantable tax-planning permissions are available.</p>
            ) : (
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {scopeOptions.map((scope) => (
                  <label key={scope} className="flex cursor-pointer items-start gap-2 rounded-[9px] border border-[var(--g-hairline)] bg-[var(--g-surface)] px-3 py-2.5">
                    <input
                      type="checkbox"
                      checked={selectedScopes.includes(scope)}
                      onChange={(event) => {
                        setSelectedScopes((current) =>
                          event.target.checked ? [...current, scope] : current.filter((item) => item !== scope),
                        );
                      }}
                      className="mt-0.5 accent-[var(--agent)]"
                    />
                    <span className="min-w-0">
                      <span className="block text-[12.5px] font-semibold text-[var(--g-ink)]">{scopeLabel(scope)}</span>
                      <span className="fig block text-[11px] text-[var(--g-ink-3)]">{scope}</span>
                    </span>
                  </label>
                ))}
              </div>
            )}
          </fieldset>

          {formError ? <p className="text-[12.5px] text-[var(--cliff)]">{formError}</p> : null}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" variant="ink" disabled={creating || loadingScopes || scopeOptions.length === 0} className="text-[13px]">
              {creating ? "Creating…" : "Create token"}
            </Button>
            <span className="text-[11.5px] text-[var(--g-ink-3)]">Default lifetime: 90 days · maximum: 365 days</span>
          </div>
        </form>

        {tokenError ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[10px] border border-[var(--cliff)] bg-[var(--cliff-soft)] px-3.5 py-2.5 text-[12.5px] text-[var(--cliff)]">
            <span>{tokenError}</span>
            <button type="button" className="inline-flex items-center gap-1.5 font-semibold underline" onClick={() => window.location.reload()}>
              <RefreshCw className="h-3.5 w-3.5" /> Retry
            </button>
          </div>
        ) : null}

        <div>
          <div className="flex items-center justify-between gap-3">
            <span className="microlabel">Your tokens</span>
            <span className="text-[11px] text-[var(--g-ink-3)]">Secrets are never shown in this list</span>
          </div>
          {loading ? (
            <div className="mt-3 space-y-2">
              <div className="skeleton h-16 w-full rounded-[10px]" />
              <div className="skeleton h-16 w-full rounded-[10px]" />
            </div>
          ) : tokens.length === 0 ? (
            <div className="mt-3 rounded-[10px] border border-dashed border-[var(--g-hairline)] px-4 py-5 text-[12.5px] text-[var(--g-ink-3)]">
              No API tokens yet. Create one above when a client needs a durable credential.
            </div>
          ) : (
            <ul className="mt-3 space-y-2">
              {tokens.map((token) => {
                const state = tokenState(token);
                return (
                  <li key={token.id} className="rounded-[10px] border border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-3.5 py-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="truncate text-[13.5px] font-semibold text-[var(--g-ink)]">{token.name}</span>
                          <Chip tone={state === "active" ? "save" : state === "revoked" ? "cliff" : "neutral"}>{state}</Chip>
                        </div>
                        <p className="mt-1 break-all text-[11.5px] text-[var(--g-ink-3)]">
                          <code className="fig">{token.prefix}</code> · {token.scopes.map(scopeLabel).join(", ") || "no permissions"}
                        </p>
                        <p className="mt-1 text-[11px] text-[var(--g-ink-3)]">
                          Created {formatDate(token.created_at)} · {token.expires_at ? `expires ${formatDate(token.expires_at)}` : "never expires"}
                          {token.last_used_at ? ` · last used ${formatDate(token.last_used_at)}` : ""}
                        </p>
                      </div>
                      {state === "active" ? (
                        confirmRevokeId === token.id ? (
                          <div className="flex shrink-0 items-center gap-2">
                            <button type="button" className="text-[11.5px] text-[var(--g-ink-3)] underline" onClick={() => setConfirmRevokeId(null)}>
                              Cancel
                            </button>
                            <Button
                              type="button"
                              variant="ghost"
                              className="!border-[var(--cliff)] !px-2.5 !py-1.5 text-[11.5px] !text-[var(--cliff)]"
                              disabled={revokingId === token.id}
                              onClick={() => void revokeToken(token.id)}
                            >
                              {revokingId === token.id ? "Revoking…" : "Revoke now"}
                            </Button>
                          </div>
                        ) : (
                          <Button type="button" variant="ghost" className="shrink-0 !px-2.5 !py-1.5 text-[11.5px]" onClick={() => setConfirmRevokeId(token.id)}>
                            Revoke
                          </Button>
                        )
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </Panel>
  );
}

export function ConnectYourAiSection() {
  return (
    <>
      <ConnectYourAiPanel />
      <PersonalAccessTokensCard />
    </>
  );
}
