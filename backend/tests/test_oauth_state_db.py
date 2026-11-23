"""Login CSRF state consumption against a REAL database (regression for the
round-2 send-back).

The round-1 ``pop_oauth_state`` was a SELECT then an in-memory UPDATE that
never committed: the consumed mark never reached the database, so a replay of
the same state (or a second callback racing the first) could exchange the
token again. These tests run the real function against the repo's test DB
fixture (TPO_TEST_DATABASE_URL, the migrated schema) with a recording
Keycloak stub, and assert on the committed rows:

- the same state used twice: the second is refused with NO exchange call;
- two concurrent callbacks with one state: exactly one exchanges;
- an expired state is refused (no exchange);
- after a good callback the row is consumed (re-read in a NEW session);
- minting prunes rows expired over an hour ago, keeps fresh and spent ones.

The app engine (app.db.session) is bound at import time to
settings.DATABASE_URL, which the integration CI step points at this same
database; the fixture factory uses TPO_TEST_DATABASE_URL (same DB). The
Keycloak token endpoint is stubbed in-process, so no network call is made.
Fixtures are fictional.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import bindparam, text

from app.api.auth import (
    PRUNE_AFTER_SECONDS,
    STATE_TTL_SECONDS,
    create_oauth_state,
    keycloak_callback,
    pop_oauth_state,
)
from app.db.session import async_session_maker
from tests.helpers.oauth_state import (
    FRONTEND,
    StateRequest,
    StubTokenClient,
    make_settings,
)

pytestmark = pytest.mark.integration

asyncpg = pytest.importorskip("asyncpg")
del asyncpg

AUTH_ERROR = f"{FRONTEND}/?auth_error=state"
COOKIE = "tpo_oauth_state"  # plain name: FRONTEND is http://localhost


def _app_dsn() -> str:
    dsn = os.environ.get("TPO_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TPO_TEST_DATABASE_URL not set")
    if dsn.startswith("postgres://"):
        return "postgresql+asyncpg://" + dsn.removeprefix("postgres://")
    if dsn.startswith("postgresql://"):
        return "postgresql+asyncpg://" + dsn.removeprefix("postgresql://")
    return dsn


async def _mint(session: Any, expires_in_seconds: int) -> tuple[str, str]:
    """Mint a state through the REAL code path, with a caller-chosen TTL,
    committed, so the callback's pop (its own session) can see the row."""
    state, verifier = await create_oauth_state(session)
    # Overwrite the mint's 1800 s deadline with the caller's TTL (negative =
    # already expired); the row otherwise is exactly what production minted.
    await session.execute(
        text("UPDATE oauth_state SET expires_at = :exp WHERE state = :s"),
        {
            "exp": datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
            "s": state,
        },
    )
    await session.commit()
    return state, verifier


async def _row(state: str) -> tuple[object, object] | None:
    """Re-read a state row in a NEW session (fresh eyes on committed data)."""
    async with async_session_maker() as session:
        result = await session.execute(
            text(
                "SELECT code_verifier, consumed_at FROM oauth_state "
                "WHERE state = :s"
            ),
            {"s": state},
        )
        return result.first()


async def _clean(state: str) -> None:
    async with async_session_maker() as session:
        await session.execute(
            text("DELETE FROM oauth_state WHERE state = :s"), {"s": state}
        )
        await session.commit()


@pytest.fixture
async def db_session_maker() -> Any:
    """Session factory bound to the test database (same DB the app engine
    uses: DATABASE_URL points here for the integration CI step)."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(_app_dsn(), poolclass=NullPool)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield maker
    finally:
        # Drop the app engine's pooled connections: pytest-asyncio gives each
        # test a fresh event loop, and asyncpg connections are bound to the
        # loop that opened them (the same reason the door test calls
        # close_db() after its client).
        from app.db.session import close_db

        await close_db()
        await engine.dispose()


async def test_same_state_twice_second_refused_without_exchange(
    stub_client: StubTokenClient, db_session_maker: Any
) -> None:
    """Replay regression: the round-1 pop never committed, so the second
    callback of the same state exchanged again. Now the first pop commits the
    consumed mark before the exchange, and the second pop matches zero rows."""
    async with db_session_maker() as session:
        state, verifier = await _mint(session, STATE_TTL_SECONDS)
    try:
        first = await keycloak_callback(
            request=StateRequest(cookies={COOKIE: state}),
            code="fictional-code-one",
            state=state,
            settings=make_settings(),
        )
        assert first.status_code == 302
        assert len(stub_client.calls) == 1
        assert stub_client.calls[0]["code_verifier"] == verifier
        assert first.headers["location"].startswith(f"{FRONTEND}/auth/sso-callback#")

        # The consumed mark must be durable BEFORE the replay can even start.
        row = await _row(state)
        assert row is not None
        assert row[1] is not None

        stub_client.calls.clear()
        second = await keycloak_callback(
            request=StateRequest(cookies={COOKIE: state}),
            code="fictional-code-one",
            state=state,
            settings=make_settings(),
        )
        assert second.status_code == 302
        assert second.headers["location"] == AUTH_ERROR
        # The contract: NO token exchange on a replayed state.
        assert stub_client.calls == []
    finally:
        await _clean(state)


async def test_two_concurrent_callbacks_exactly_one_exchanges(
    stub_client: StubTokenClient, db_session_maker: Any
) -> None:
    """Two callbacks with the same state, racing in the same event loop: the
    atomic UPDATE ... RETURNING can hand the verifier to exactly one of them;
    the other sees the committed consumed mark and refuses."""
    async with db_session_maker() as session:
        state, verifier = await _mint(session, STATE_TTL_SECONDS)
    try:
        first, second = await asyncio.gather(
            keycloak_callback(
                request=StateRequest(cookies={COOKIE: state}),
                code="fictional-race-code",
                state=state,
                settings=make_settings(),
            ),
            keycloak_callback(
                request=StateRequest(cookies={COOKIE: state}),
                code="fictional-race-code",
                state=state,
                settings=make_settings(),
            ),
        )
        # Exactly one exchange, with the stored verifier.
        assert len(stub_client.calls) == 1
        assert stub_client.calls[0]["code_verifier"] == verifier
        winners = [
            r
            for r in (first, second)
            if r.headers["location"].startswith(f"{FRONTEND}/auth/sso-callback#")
        ]
        losers = [r for r in (first, second) if r.headers["location"] == AUTH_ERROR]
        assert len(winners) == 1
        assert len(losers) == 1
    finally:
        await _clean(state)


async def test_expired_state_refused_without_exchange(
    stub_client: StubTokenClient, db_session_maker: Any
) -> None:
    """A row past its 1800 s TTL is refused by the deadline in the atomic
    statement (expires_at > now()), with no exchange. The row is left
    unconsumed: expiry, not consumption, is why it was refused."""
    async with db_session_maker() as session:
        state, verifier = await _mint(session, -5)
    try:
        assert verifier  # minted fine; only the deadline is in the past
        response = await keycloak_callback(
            request=StateRequest(cookies={COOKIE: state}),
            code="fictional-stale-code",
            state=state,
            settings=make_settings(),
        )
        assert response.status_code == 302
        assert response.headers["location"] == AUTH_ERROR
        assert stub_client.calls == []
        row = await _row(state)
        assert row is not None
        assert row[1] is None
    finally:
        await _clean(state)


async def test_good_callback_consumes_row_visible_in_new_session(
    stub_client: StubTokenClient, db_session_maker: Any
) -> None:
    """After a successful callback, a fresh session must see the row with
    consumed_at set and the verifier intact: the consumption is committed,
    not merely flushed in the callback's own transaction."""
    async with db_session_maker() as session:
        state, verifier = await _mint(session, STATE_TTL_SECONDS)
    try:
        response = await keycloak_callback(
            request=StateRequest(cookies={COOKIE: state}),
            code="fictional-good-code",
            state=state,
            settings=make_settings(),
        )
        assert response.status_code == 302
        assert len(stub_client.calls) == 1
        row = await _row(state)
        assert row is not None
        stored_verifier, consumed_at = row
        assert stored_verifier == verifier
        assert consumed_at is not None
        # And pop is now a flat refusal (zero rows).
        assert await pop_oauth_state(state) is None
    finally:
        await _clean(state)


async def test_mint_prunes_old_rows_keeps_fresh_and_spent(
    db_session_maker: Any
) -> None:
    """Every mint sweeps rows expired over an hour ago (the public
    /auth/keycloak must not let the table grow unboundedly), but keeps fresh
    rows and even CONSUMED recent rows (their cookie may still be in flight
    within the 1800 s window; a replay of a consumed row is refused by
    consumed_at, not by deletion)."""
    from uuid import uuid4

    from app.api.auth import _prune_expired_states

    # Unique per run: the shared test DB may hold rows from earlier runs.
    run_id = uuid4().hex[:10]
    now = datetime.now(UTC)
    dead = now - timedelta(seconds=PRUNE_AFTER_SECONDS + 600)
    fresh = now + timedelta(seconds=STATE_TTL_SECONDS)
    spent = now + timedelta(seconds=120)
    tags = ("dead", "fresh", "spent")
    seeded = [f"prune-{run_id}-{t}" for t in tags]
    async with db_session_maker() as session:
        for tag, name, exp, consumed in (
            (tags[0], seeded[0], dead, False),
            (tags[1], seeded[1], fresh, False),
            (tags[2], seeded[2], spent, True),
        ):
            await session.execute(
                text(
                    "INSERT INTO oauth_state (state, code_verifier, expires_at, "
                    "consumed_at) VALUES (:s, :v, :e, "
                    "CASE WHEN :c THEN now() ELSE NULL END)"
                ),
                {"s": name, "v": f"v-{tag}", "e": exp, "c": consumed},
            )
        await session.commit()

    # The real mint path runs the sweep as its first statement.
    async with db_session_maker() as session:
        await create_oauth_state(session)
        await session.commit()

    async with db_session_maker() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT state, consumed_at IS NOT NULL AS spent "
                    "FROM oauth_state WHERE state IN :seeded "
                    "ORDER BY state"
                ).bindparams(bindparam("seeded", expanding=True)),
                {"seeded": seeded},
            )
        ).all()
    states = [r[0] for r in rows]
    assert seeded[0] not in states
    assert seeded[1] in states
    assert seeded[2] in states
    spent_flags = {r[0]: r[1] for r in rows}
    assert spent_flags[seeded[2]] is True
    assert spent_flags[seeded[1]] is False

    await asyncio.gather(*(_clean(name) for name in seeded[1:]))

    # A bare prune call right after the sweep finds nothing left to drop.
    async with db_session_maker() as session:
        await _prune_expired_states(session)
        leftover = (
            await session.execute(
                text(
                    "SELECT count(*) FROM oauth_state "
                    "WHERE expires_at < now() - make_interval(secs => :slack)"
                ),
                {"slack": PRUNE_AFTER_SECONDS},
            )
        ).scalar_one()
        assert leftover == 0
        await session.rollback()
