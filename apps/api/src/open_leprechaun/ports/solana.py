"""The Solana Address Indexer (ticket 38): the chain's public JSON-RPC
translated into the port's normalized transfers. No key, no signing — the
three methods it calls only read.

How an address's history is read:

- `getSignaturesForAddress` lists the transactions that name an account,
  newest first, a thousand a page, continued by `before`. A wallet's tokens
  live in separate token accounts, and a transfer *into* one names only that
  account — never the wallet — so the walk covers the wallet and every token
  account it owns today (`getTokenAccountsByOwner`, for both token programs).
  Without that, the unsolicited token inflow is exactly what would be missed.
- `getTransaction` states every account's lamport balance before and after,
  and every token account's balance with its mint and owner. What moved is
  the difference — the chain's own arithmetic, whatever programs ran — so
  nothing here interprets instructions.

Quirks absorbed here:

- Units: lamports are a billionth of a SOL; a token's raw amount scales by
  the decimals its mint declares. Both normalise to whole units.
- Time: `blockTime` is Unix seconds, read as UTC.
- SOL held in the wallet's own token accounts is still the wallet's: the rent
  that opens a token account and wrapped SOL both sit in an account the
  wallet owns, so lamports are summed over the wallet and its token accounts,
  and the wrapped-SOL mint is not also counted as a token.
- The network fee is charged to the first account of the transaction. When
  that is this address, the fee is taken back out of the SOL difference and
  stated on its own; a failed transaction still costs its fee, and moves
  nothing else.
- Rate limits: the public endpoint answers 429 readily; calls are spaced,
  a 429 waits and retries a bounded number of times, then raises.

What it cannot judge, and says so instead: a transaction that moved one
asset in and another out is most likely a swap, but balances state no intent
— both sides arrive as transfers with a warning. SOL moved into a stake
account has left the address but not the owner, and rewards accrue where
this walk does not look; transactions touching the Stake program are
counted in a warning.

A token is named by its mint. The label is the indexer's own short table for
a few well-known mints and otherwise the abbreviated mint itself: a token's
self-declared name is whatever its issuer typed — routinely a lure — so it
is deliberately not fetched to greet the Admin in the inbox.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from open_leprechaun.ports.address_indexer import (
    AddressHistory,
    AddressRejectedError,
    ChainAsset,
    IndexerError,
    NormalizedAddressTransfer,
    NormalizedNetworkFee,
)

PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"

SOL = ChainAsset(symbol="SOL", name="Solana")
_LAMPORTS_PER_SOL = Decimal(10**9)

_TOKEN_PROGRAMS = (
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
)
_STAKE_PROGRAM = "Stake11111111111111111111111111111111111111"
# SOL wrapped as a token: its balance is the lamports of the token account
# holding it, which the lamport sum already covers.
_WRAPPED_SOL_MINT = "So11111111111111111111111111111111111111112"

# Mints labelled by the indexer itself, each with the currency it pegs.
_KNOWN_MINTS: dict[str, tuple[str, str, str | None]] = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": ("USDC", "USD Coin", "USD"),
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": ("USDT", "Tether USD", "USD"),
}

_SIGNATURE_PAGE = 1000
# The budget of one address's walk; exhausting it means truncation, which is
# an error to raise, never a silent shortfall.
_MAX_SIGNATURES = 20_000
# The newest transaction format the walk declares it can read — balances are
# stated the same way in each so far; the endpoint refuses to serve a newer
# one rather than hand over what might be misread.
_MAX_TRANSACTION_VERSION = 1
_RATE_LIMIT_RETRIES = 5
# A finalized transaction never changes, so what one moved at an address is
# remembered: the commit that follows a preview asks the chain only for the
# signature lists again.
_REMEMBERED = 50_000

_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


@dataclass(frozen=True)
class _Moved:
    """What one transaction did at the address, and the two things about it
    the indexer can only flag."""

    transfers: tuple[NormalizedAddressTransfer, ...] = ()
    fee: NormalizedNetworkFee | None = None
    swap_shaped: bool = False
    touched_stake: bool = False
    # The wallet's token accounts this transaction named — how one that has
    # since been closed is still found.
    token_accounts: frozenset[str] = frozenset()


class SolanaIndexer:
    chain = "solana"
    name = "Solana"
    native = SOL
    # The chain keeps its whole history; an endpoint that has pruned some of
    # it is caught where a listed transaction is no longer served.
    lookback_days = None

    def __init__(
        self,
        rpc_url: str = PUBLIC_RPC_URL,
        client: httpx.Client | None = None,
        throttle_seconds: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._rpc_url = rpc_url
        self._client = client or httpx.Client(timeout=30.0)
        self._throttle_seconds = throttle_seconds
        self._sleep = sleep
        self._remembered: dict[tuple[str, str], _Moved] = {}

    def history(self, address: str) -> AddressHistory:
        _require_address(address)
        try:
            moved = self._walk(address)
        except (KeyError, IndexError, TypeError, AttributeError) as malformed:
            raise IndexerError("The Solana endpoint answered something unreadable.") from malformed
        return AddressHistory(
            transfers=tuple(transfer for entry in moved for transfer in entry.transfers),
            fees=tuple(entry.fee for entry in moved if entry.fee is not None),
            warnings=_warnings(
                sum(entry.swap_shaped for entry in moved),
                sum(entry.touched_stake for entry in moved),
            ),
        )

    def _walk(self, address: str) -> list[_Moved]:
        """Every transaction naming the wallet or a token account of its,
        each once, oldest first. The token accounts owned today are asked
        for; one since closed is learned from the transactions themselves —
        closing takes the wallet's signature, so the wallet's own history
        names it — and its history is then walked like the others."""
        known = set(self._token_accounts(address))
        pending = [address, *sorted(known)]
        slots: dict[str, int] = {}
        moved: dict[str, _Moved] = {}
        while pending:
            account = pending.pop(0)
            for signature in self._signatures(account, slots):
                moved[signature] = self._moved(address, frozenset(known), signature)
                for discovered in sorted(moved[signature].token_accounts - known):
                    known.add(discovered)
                    pending.append(discovered)
        return [
            moved[s] for s in sorted(moved, key=lambda signature: (slots[signature], signature))
        ]

    def _token_accounts(self, address: str) -> frozenset[str]:
        accounts: set[str] = set()
        for program in _TOKEN_PROGRAMS:
            answer = self._call(
                "getTokenAccountsByOwner",
                [address, {"programId": program}, {"encoding": "jsonParsed", **_FINALIZED}],
            )
            accounts.update(entry["pubkey"] for entry in answer["value"])
        return frozenset(accounts)

    def _signatures(self, account: str, slots: dict[str, int]) -> list[str]:
        """The transactions naming this account that the walk has not met
        yet — one transaction usually names the wallet and its token account
        both — recording each one's slot."""
        fresh: list[str] = []
        before: str | None = None
        while True:
            page = self._call(
                "getSignaturesForAddress",
                [
                    account,
                    {"limit": _SIGNATURE_PAGE, **_FINALIZED}
                    | ({"before": before} if before else {}),
                ],
            )
            for entry in page:
                if entry["signature"] not in slots:
                    slots[entry["signature"]] = entry["slot"]
                    fresh.append(entry["signature"])
            if len(slots) > _MAX_SIGNATURES:
                raise IndexerError(
                    f"This address has more than {_MAX_SIGNATURES} transactions — more"
                    " than one walk reads, and a history cut short is not imported."
                )
            if len(page) < _SIGNATURE_PAGE:
                return fresh
            before = page[-1]["signature"]

    def _moved(self, address: str, token_accounts: frozenset[str], signature: str) -> _Moved:
        remembered = self._remembered.get((address, signature))
        if remembered is not None:
            return remembered
        transaction = self._call(
            "getTransaction",
            [
                signature,
                {
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": _MAX_TRANSACTION_VERSION,
                    **_FINALIZED,
                },
            ],
        )
        if transaction is None:
            raise IndexerError(
                f"The endpoint lists transaction {signature} but no longer serves it — its"
                " history does not reach back far enough to read this address whole."
            )
        try:
            moved = _what_moved(address, token_accounts, signature, transaction)
        except (KeyError, IndexError, TypeError, ValueError, ArithmeticError) as malformed:
            raise IndexerError(
                f"Transaction {signature} came back in a shape this indexer cannot read."
            ) from malformed
        if len(self._remembered) >= _REMEMBERED:
            self._remembered.clear()
        self._remembered[(address, signature)] = moved
        return moved

    def _call(self, method: str, params: list) -> Any:  # noqa: ANN401
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        for attempt in range(_RATE_LIMIT_RETRIES + 1):
            if self._throttle_seconds:
                self._sleep(self._throttle_seconds)
            try:
                response = self._client.post(self._rpc_url, json=payload)
            except httpx.HTTPError as failed:
                raise IndexerError("The Solana endpoint is not answering.") from failed
            if response.status_code == 429:
                self._sleep(_retry_after(response, attempt))
                continue
            if response.status_code >= 400:
                raise IndexerError(f"The Solana endpoint answered HTTP {response.status_code}.")
            try:
                body = response.json()
            except ValueError as unparsed:
                raise IndexerError(
                    "The Solana endpoint answered something unreadable."
                ) from unparsed
            if not isinstance(body, dict) or ("result" not in body and "error" not in body):
                raise IndexerError("The Solana endpoint answered something unreadable.")
            if "error" in body:
                raise IndexerError(f"The Solana endpoint refused {method}: {_reason(body)}")
            return body["result"]
        raise IndexerError(
            "The Solana endpoint is rate-limiting — try again in a while, or point"
            " SOLANA_RPC_URL at a provider's endpoint."
        )


_FINALIZED = {"commitment": "finalized"}


def _require_address(address: str) -> None:
    """A Solana address is 32 bytes written in base58 — judged here, before
    anything is asked of the chain."""
    number = 0
    for character in address:
        digit = _BASE58.find(character)
        if digit < 0:
            number = -1
            break
        number = number * 58 + digit
    leading_zero_bytes = len(address) - len(address.lstrip("1"))
    if number < 0 or leading_zero_bytes + (number.bit_length() + 7) // 8 != 32:
        raise AddressRejectedError(
            "That is not a Solana address — one is 32 bytes in base58, 32 to 44 characters."
        )


def _what_moved(
    address: str, token_accounts: frozenset[str], signature: str, transaction: dict
) -> _Moved:
    """What the transaction's own before-and-after balances say moved at the
    address."""
    meta = transaction["meta"]
    block_time = transaction.get("blockTime")
    if block_time is None:
        raise IndexerError(
            f"The endpoint states no time for transaction {signature} — without one it"
            " cannot be placed in a tax year."
        )
    occurred_at = datetime.fromtimestamp(block_time, UTC)
    keys = [
        key["pubkey"] if isinstance(key, dict) else key
        for key in transaction["transaction"]["message"]["accountKeys"]
    ]

    def own(balances: list[dict]) -> list[dict]:
        # Older transactions state no owner beside a token balance; the
        # token accounts the wallet owns today stand in.
        return [
            balance
            for balance in balances
            if balance.get("owner") == address or keys[balance["accountIndex"]] in token_accounts
        ]

    before = own(meta.get("preTokenBalances") or [])
    after = own(meta.get("postTokenBalances") or [])

    owned = {index for index, key in enumerate(keys) if key == address}
    owned.update(balance["accountIndex"] for balance in before + after)
    fee = meta["fee"] if keys[0] == address else 0
    lamports = sum(meta["postBalances"][i] - meta["preBalances"][i] for i in owned) + fee

    raw: dict[str, int] = {}
    decimals: dict[str, int] = {}
    for balance, sign in [(b, -1) for b in before] + [(b, 1) for b in after]:
        mint = balance["mint"]
        if mint == _WRAPPED_SOL_MINT:
            continue
        amount = balance["uiTokenAmount"]
        raw[mint] = raw.get(mint, 0) + sign * int(amount["amount"])
        decimals[mint] = int(amount["decimals"])

    moves: list[tuple[str, ChainAsset, Decimal]] = []
    if lamports:
        moves.append(("native", SOL, Decimal(lamports) / _LAMPORTS_PER_SOL))
    for mint in sorted(raw):
        if raw[mint]:
            moves.append((mint, _token(mint), Decimal(raw[mint]).scaleb(-decimals[mint])))

    fee_quantity = Decimal(fee) / _LAMPORTS_PER_SOL if fee else None
    # The fee rides on the movement it most plausibly enabled: something the
    # address sent, else whatever moved.
    fee_bearer = next(
        (key for key, _, quantity in moves if quantity < 0), moves[0][0] if moves else None
    )
    transfers = tuple(
        NormalizedAddressTransfer(
            external_id=f"{signature}:{key}",
            occurred_at=occurred_at,
            direction="in" if quantity > 0 else "out",
            asset=asset,
            quantity=abs(quantity),
            fee_quantity=fee_quantity if key == fee_bearer else None,
        )
        for key, asset, quantity in moves
    )
    directions = {transfer.direction for transfer in transfers}
    return _Moved(
        transfers=transfers,
        fee=NormalizedNetworkFee(
            external_id=f"{signature}:fee", occurred_at=occurred_at, quantity=fee_quantity
        )
        if fee_quantity is not None and not moves
        else None,
        swap_shaped=directions == {"in", "out"},
        touched_stake=_STAKE_PROGRAM in keys,
        token_accounts=frozenset(keys[index] for index in owned) - {address},
    )


def _token(mint: str) -> ChainAsset:
    known = _KNOWN_MINTS.get(mint)
    if known is not None:
        symbol, name, pegged_currency = known
        return ChainAsset(
            symbol=symbol, name=name, contract_address=mint, pegged_currency=pegged_currency
        )
    return ChainAsset(
        symbol=f"{mint[:4]}…{mint[-4:]}", name=f"Solana token {mint}", contract_address=mint
    )


def _warnings(swap_shaped: int, touched_stake: int) -> tuple[str, ...]:
    warnings: list[str] = []
    if swap_shaped:
        warnings.append(
            f"{_counted(swap_shaped)} moved one asset in and another out — most likely a"
            " swap. The chain states balances, not intent, so each side arrives as its own"
            " transfer; replace each pair with a trade in the ledger."
        )
    if touched_stake:
        warnings.append(
            f"{_counted(touched_stake)} touched the Stake program. SOL delegated to a stake"
            " account has left this address but not your ownership, and rewards accrue"
            " inside the stake account, which this address's history does not show —"
            " record staking by hand."
        )
    return tuple(warnings)


def _counted(count: int) -> str:
    return f"{count} transaction" if count == 1 else f"{count} transactions"


def _reason(body: dict) -> str:
    error = body["error"]
    message = error.get("message") if isinstance(error, dict) else None
    return str(message or "no reason given")


def _retry_after(response: httpx.Response, attempt: int) -> float:
    """What the endpoint asks for, else a doubling wait — never longer than
    half a minute a try."""
    try:
        asked = float(response.headers.get("retry-after", ""))
    except ValueError:
        asked = float(2**attempt)
    return min(max(asked, 0.0), 30.0)
