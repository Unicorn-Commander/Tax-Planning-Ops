import assert from "node:assert/strict";
import test from "node:test";
import { cleanCallbackUrl, parseTokenParams } from "./sso-callback-lib.ts";

function windowWith(url) {
  const u = new URL(url, "http://app.example.com");
  return {
    location: {
      href: u.href,
      pathname: u.pathname,
      search: u.search,
      hash: u.hash,
    },
    history: {
      state: null,
      calls: [],
      replaceState(state, title, url) {
        this.calls.push([state, title, url]);
      },
    },
  };
}

test("fragment form parses token and refresh_token", () => {
  const win = windowWith(
    "http://app.example.com/auth/sso-callback#token=frag-access&refresh_token=frag-refresh",
  );
  const { token, refreshToken } = parseTokenParams(win);
  assert.equal(token, "frag-access");
  assert.equal(refreshToken, "frag-refresh");
});

test("tokens are never read from the query string (leak is ignored)", () => {
  const win = windowWith(
    "http://app.example.com/auth/sso-callback?token=query-access&refresh_token=query-refresh",
  );
  const { token, refreshToken } = parseTokenParams(win);
  assert.equal(token, null);
  assert.equal(refreshToken, null);
});

test("fragment wins; a query token alongside is still ignored", () => {
  const win = windowWith(
    "http://app.example.com/auth/sso-callback?token=query-access#token=frag-access",
  );
  const { token, refreshToken } = parseTokenParams(win);
  assert.equal(token, "frag-access");
  assert.equal(refreshToken, null);
});

test("no tokens at all parses to null", () => {
  const win = windowWith("http://app.example.com/auth/sso-callback");
  const { token, refreshToken } = parseTokenParams(win);
  assert.equal(token, null);
  assert.equal(refreshToken, null);
});

test("cleanCallbackUrl strips hash, query, and leaves no tokens behind", () => {
  const win = windowWith(
    "http://app.example.com/auth/sso-callback#token=secret-access&refresh_token=secret-refresh",
  );
  const cleaned = cleanCallbackUrl(win);
  assert.equal(cleaned, "http://app.example.com/auth/sso-callback");
  assert.equal(win.history.calls.length, 1);
  assert.equal(win.history.calls[0][2], "http://app.example.com/auth/sso-callback");
  // The cleaned URL must not contain any token material.
  for (const [state, , url] of win.history.calls) {
    void state;
    assert.ok(!url.includes("secret-access"));
    assert.ok(!url.includes("secret-refresh"));
    assert.ok(!url.includes("token="));
  }
});

test("cleanCallbackUrl strips a leaked query token too", () => {
  const win = windowWith(
    "http://app.example.com/auth/sso-callback?token=secret-access&refresh_token=secret-refresh",
  );
  const cleaned = cleanCallbackUrl(win);
  assert.equal(cleaned, "http://app.example.com/auth/sso-callback");
  assert.ok(!cleaned.includes("token="));
  // And nothing token-like was ever handed to replaceState.
  for (const [state, , url] of win.history.calls) {
    void state;
    assert.ok(!url.includes("secret-access"));
    assert.ok(!url.includes("secret-refresh"));
  }
});

test("SSR/window undefined: parseTokenParams returns nulls without throwing", () => {
  const { token, refreshToken } = parseTokenParams(undefined);
  assert.equal(token, null);
  assert.equal(refreshToken, null);
});
