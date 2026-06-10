"""Local OIDC stand-in for development/QA.

Serves a JWKS endpoint and mints RS256 tokens so the real verification path
(JWKS fetch, kid resolution, iss/aud/exp checks) is exercised without a live
Keycloak. Never use in production.

Usage:
  python scripts/dev_oidc.py serve [--port 8765]
  python scripts/dev_oidc.py mint --workspace <uuid> [--scopes "taxplan:advisor taxplan:admin"]
                                  [--sub dev-user] [--ttl 43200] [--issuer http://localhost:8765]

Key material is generated once into .dev-oidc/ (gitignored).
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from jose.utils import base64url_encode

STATE_DIR = Path(__file__).resolve().parents[1] / ".dev-oidc"
KID = "tpo-dev-key-1"


def _ensure_keys() -> tuple[bytes, dict]:
    STATE_DIR.mkdir(exist_ok=True)
    priv_path = STATE_DIR / "private.pem"
    jwks_path = STATE_DIR / "jwks.json"
    if priv_path.exists() and jwks_path.exists():
        return priv_path.read_bytes(), json.loads(jwks_path.read_text())
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = key.public_key().public_numbers()

    def _b64(n: int, length: int | None = None) -> str:
        data = n.to_bytes(length or (n.bit_length() + 7) // 8, "big")
        return base64url_encode(data).decode()

    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": KID,
                "n": _b64(pub.n),
                "e": _b64(pub.e),
            }
        ]
    }
    priv_path.write_bytes(priv_pem)
    jwks_path.write_text(json.dumps(jwks))
    return priv_pem, jwks


def serve(port: int) -> None:
    _, jwks = _ensure_keys()
    body = json.dumps(jwks).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    print(f"dev JWKS serving on http://localhost:{port} (any path)")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


def mint(issuer: str, workspace: str, sub: str, scopes: str, ttl: int, audience: str) -> str:
    priv_pem, _ = _ensure_keys()
    now = int(time.time())
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": sub,
        "iat": now,
        "exp": now + ttl,
        "workspace_id": workspace,
        "scope": scopes,
    }
    return jwt.encode(claims, priv_pem.decode(), algorithm="RS256", headers={"kid": KID})


def main() -> None:
    parser = argparse.ArgumentParser()
    sub_parsers = parser.add_subparsers(dest="cmd", required=True)
    p_serve = sub_parsers.add_parser("serve")
    p_serve.add_argument("--port", type=int, default=8765)
    p_mint = sub_parsers.add_parser("mint")
    p_mint.add_argument("--workspace", required=True)
    p_mint.add_argument("--sub", default="dev-user")
    p_mint.add_argument("--scopes", default="taxplan:advisor taxplan:admin")
    p_mint.add_argument("--ttl", type=int, default=43200)
    p_mint.add_argument("--issuer", default="http://localhost:8765")
    p_mint.add_argument("--audience", default="tax-planning-ops")
    args = parser.parse_args()
    if args.cmd == "serve":
        serve(args.port)
    else:
        print(mint(args.issuer, args.workspace, args.sub, args.scopes, args.ttl, args.audience))


if __name__ == "__main__":
    main()
