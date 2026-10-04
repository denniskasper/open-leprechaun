"""The Solana Address Indexer against recorded RPC responses (ticket 38):
the chain's own payloads in, normalized transfers out. No live call is ever
made — the seam is the port, fed through a mock transport that answers what
the public endpoint answered.

`fixtures/solana/recorded.json` is a recording of the public mainnet
endpoint: one settled transaction in which SOL and a token changed hands
between two wallets, one failed transaction, and one wallet's token
accounts. Every address and amount in it is public chain state belonging to
strangers. The transactions are trimmed to what an indexer reads — account
keys, the fee and error, and the before-and-after balances — with nothing
altered. The mock endpoint honours the real pagination contract: newest
first, `limit` a page, `before` continuing strictly after that signature.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from open_leprechaun.ports.address_indexer import (
    AddressRejectedError,
    ChainAsset,
    IndexerError,
)
from open_leprechaun.ports.solana import SolanaIndexer

RECORDED = json.loads((Path(__file__).parent / "fixtures/solana/recorded.json").read_text())

TRANSFER, FAILED = (entry["signature"] for entry in RECORDED["signatures"]["result"])
SIGNATURE_ENTRY = {entry["signature"]: entry for entry in RECORDED["signatures"]["result"]}

# The wallets of the recorded transfer. The payer sent SOL — to the taker, to
# a tip account, and as the rent of a token account opened for the taker —
# paid the network fee, and received USDC; the taker sent that USDC.
PAYER = "FHpcNSe6tb2n15bAdq4BkeYWGyZKFD7yLYrH92ng7wCT"
TAKER = "FyydFaMhgYmpSn3KuEkP4ZmPQ2wTrDjB8AaES1PXoYG4"
TAKER_USDC_ACCOUNT = "FRrDUeRheyP1NtuajqgqJzaXryrcgheKZ54SshatMQPd"
TIPPED = "pfnUxCuZcfP6yidkG3EsqyR5DTbyie3R74fGoA5oB3J"
# The payer of the recorded failed transaction.
FAILED_PAYER = "FfAJbv3prDQUybTNkS3EGaoSbkkbSLy1Eahe5MMxMG9t"

USDC = ChainAsset(
    symbol="USDC",
    name="USD Coin",
    contract_address="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    pegged_currency="USD",
)
SOL = ChainAsset(symbol="SOL", name="Solana")
# blockTime 1791113603, read as UTC.
SETTLED_AT = datetime(2026, 10, 4, 11, 33, 23, tzinfo=UTC)


class Endpoint:
    """The recorded endpoint: `listed` says which signatures each account's
    history names, newest first; everything else is the recording."""

    def __init__(self, listed: dict[str, list[str]], token_accounts: dict[str, list] | None = None):
        self.listed = listed
        self.token_accounts = token_accounts or {}
        self.transactions = dict(RECORDED["transactions"])
        self.calls: list[tuple[str, list]] = []
        self.rate_limited = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.rate_limited:
            self.rate_limited -= 1
            return httpx.Response(429, headers={"retry-after": "7"})
        body = json.loads(request.content)
        method, params = body["method"], body["params"]
        self.calls.append((method, params))
        assert request.headers.get("authorization") is None
        if method == "getTokenAccountsByOwner":
            owner, program = params[0], params[1]["programId"]
            value = self.token_accounts.get(owner, []) if program.startswith("Tokenkeg") else []
            return self._ok({"context": {"slot": 453244436}, "value": value})
        if method == "getSignaturesForAddress":
            signatures = self.listed.get(params[0], [])
            before = params[1].get("before")
            if before is not None:
                signatures = signatures[signatures.index(before) + 1 :]
            page = signatures[: params[1]["limit"]]
            return self._ok(
                [SIGNATURE_ENTRY.get(s, {"signature": s, "slot": 1, "err": None}) for s in page]
            )
        if method == "getTransaction":
            assert params[1]["encoding"] == "jsonParsed"
            return httpx.Response(200, json=self.transactions[params[0]])
        raise AssertionError(f"Unexpected method {method}")

    @staticmethod
    def _ok(result: object) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    def called(self, method: str) -> list[list]:
        return [params for name, params in self.calls if name == method]


def indexer(endpoint: Endpoint, **overrides) -> SolanaIndexer:
    given = dict(client=httpx.Client(transport=httpx.MockTransport(endpoint)), throttle_seconds=0)
    given.update(overrides)
    return SolanaIndexer(**given)


def taker_token_accounts() -> dict[str, list]:
    return {TAKER: RECORDED["token_accounts"]["result"]["value"]}


# --- What moved, from the chain's own before-and-after balances ---


def test_a_plain_sol_inflow_arrives_in_whole_units_at_its_utc_instant():
    """Lamports are a billionth of a SOL and blockTime is Unix seconds: the
    tip account received 10,000 lamports."""
    history = indexer(Endpoint({TIPPED: [TRANSFER]})).history(TIPPED)

    (received,) = history.transfers
    assert received.external_id == f"{TRANSFER}:native"
    assert received.occurred_at == SETTLED_AT
    assert (received.direction, received.asset, received.quantity) == (
        "in",
        SOL,
        Decimal("0.00001"),
    )
    assert received.fee_quantity is None
    assert history.fees == ()
    assert history.warnings == ()


def test_the_payers_fee_is_taken_out_of_what_it_sent_and_stated_once():
    """The payer's own account fell by 21,171,708 lamports, of which 18,334
    were the network fee: what it sent is the rest, the fee its own figure,
    carried by the outflow and not by the token that arrived."""
    history = indexer(Endpoint({PAYER: [TRANSFER]})).history(PAYER)

    sent, received = history.transfers
    assert (sent.direction, sent.asset, sent.quantity) == ("out", SOL, Decimal("0.021153374"))
    assert sent.fee_quantity == Decimal("0.000018334")
    assert (received.direction, received.asset, received.quantity) == (
        "in",
        USDC,
        Decimal("3.174596"),
    )
    assert received.external_id == f"{TRANSFER}:{USDC.contract_address}"
    assert received.fee_quantity is None
    assert history.fees == ()


def test_a_token_amount_scales_by_the_decimals_its_mint_declares():
    """USDC declares six decimals: 3,174,596 raw units left the taker."""
    history = indexer(Endpoint({TAKER: [TRANSFER]})).history(TAKER)

    sent = next(t for t in history.transfers if t.asset == USDC)
    assert (sent.direction, sent.quantity) == ("out", Decimal("3.174596"))


def test_sol_in_the_wallets_own_token_accounts_is_still_the_wallets():
    """The taker received 19,654,934 lamports directly and a wrapped-SOL
    token account opened in its name holding 1,488,440 of rent — one SOL
    inflow of both, and no second token called wrapped SOL. It paid no fee:
    it was not the transaction's first account."""
    history = indexer(Endpoint({TAKER: [TRANSFER]})).history(TAKER)

    received = next(t for t in history.transfers if t.asset == SOL)
    assert (received.direction, received.quantity) == ("in", Decimal("0.021143374"))
    assert [t.asset for t in history.transfers] == [SOL, USDC]
    assert all(t.fee_quantity is None for t in history.transfers)


def test_a_failed_transaction_costs_its_payer_the_fee_and_nothing_else():
    history = indexer(Endpoint({FAILED_PAYER: [FAILED]})).history(FAILED_PAYER)

    assert history.transfers == ()
    (fee,) = history.fees
    assert fee.external_id == f"{FAILED}:fee"
    assert fee.quantity == Decimal("0.000005")


def test_a_transaction_that_moved_nothing_at_the_address_yields_nothing():
    """The failed transaction names the USDC mint's holder accounts too; a
    bystander neither paid nor moved."""
    bystander = "8sKQHfjNhvmAw94PhfvfMcytmqW6jmxvwieYyzXCCPu"

    history = indexer(Endpoint({bystander: [FAILED]})).history(bystander)

    assert (history.transfers, history.fees) == ((), ())


def test_an_unknown_mint_is_named_by_its_address_exactly_as_the_chain_writes_it():
    """No label is fetched from the token itself — the mint, abbreviated, is
    the symbol, and the contract keeps its casing."""
    mint = "Dz9mQ9NzkBcCsuGPFJ3r1bS4wgqKMHBPiVuniW8Mbonk"
    endpoint = Endpoint({TAKER: [TRANSFER]})
    recorded = json.dumps(endpoint.transactions[TRANSFER]).replace(USDC.contract_address, mint)
    endpoint.transactions[TRANSFER] = json.loads(recorded)

    history = indexer(endpoint).history(TAKER)

    token = next(t.asset for t in history.transfers if t.asset.contract_address)
    assert token == ChainAsset(
        symbol="Dz9m…bonk", name=f"Solana token {mint}", contract_address=mint
    )


# --- Finding the history: the wallet and the token accounts it owns ---


def test_a_transfer_naming_only_the_token_account_is_still_found():
    """A token sent into a wallet names the wallet's token account, never
    the wallet: the walk covers every token account the wallet owns, under
    both token programs, or the unsolicited inflow is the one thing missed."""
    endpoint = Endpoint({TAKER_USDC_ACCOUNT: [TRANSFER]}, taker_token_accounts())

    history = indexer(endpoint).history(TAKER)

    assert {t.asset for t in history.transfers} == {SOL, USDC}
    programs = [params[1]["programId"] for params in endpoint.called("getTokenAccountsByOwner")]
    assert programs == [
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    ]


def test_a_token_account_since_closed_is_learned_from_the_wallets_own_history():
    """The endpoint lists only token accounts that exist today. One the
    wallet has closed is still named, with its owner, by the wallet's own
    transactions — and what names only that account is then read too."""
    endpoint = Endpoint({TAKER: [TRANSFER], TAKER_USDC_ACCOUNT: [FAILED]})

    indexer(endpoint).history(TAKER)

    walked = [params[0] for params in endpoint.called("getSignaturesForAddress")]
    assert walked[0] == TAKER
    assert TAKER_USDC_ACCOUNT in walked
    assert [params[0] for params in endpoint.called("getTransaction")] == [TRANSFER, FAILED]


def test_an_answer_in_no_shape_the_walk_knows_is_an_indexer_failure():
    def shapeless(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": [{"no": "pubkey"}]})

    with pytest.raises(IndexerError, match="unreadable"):
        indexer(shapeless).history(TIPPED)


def test_a_transaction_listed_under_several_accounts_is_read_once():
    endpoint = Endpoint({TAKER: [TRANSFER], TAKER_USDC_ACCOUNT: [TRANSFER]}, taker_token_accounts())

    history = indexer(endpoint).history(TAKER)

    assert len(history.transfers) == 2
    assert len(endpoint.called("getTransaction")) == 1


def test_a_balance_stating_no_owner_is_judged_by_the_token_accounts_owned_today():
    """Older transactions carry no owner beside a token balance."""
    endpoint = Endpoint({TAKER: [TRANSFER]}, taker_token_accounts())
    meta = endpoint.transactions[TRANSFER] = json.loads(json.dumps(endpoint.transactions[TRANSFER]))
    for balance in meta["result"]["meta"]["preTokenBalances"]:
        del balance["owner"]
    for balance in meta["result"]["meta"]["postTokenBalances"]:
        del balance["owner"]

    history = indexer(endpoint).history(TAKER)

    assert [(t.asset, t.direction) for t in history.transfers] == [(SOL, "in"), (USDC, "out")]


def test_a_full_page_of_signatures_continues_before_its_last(monkeypatch):
    monkeypatch.setattr("open_leprechaun.ports.solana._SIGNATURE_PAGE", 1)
    endpoint = Endpoint({PAYER: [TRANSFER, FAILED]})

    history = indexer(endpoint).history(PAYER)

    cursors = [
        params[1].get("before")
        for params in endpoint.called("getSignaturesForAddress")
        if params[0] == PAYER
    ]
    assert cursors == [None, TRANSFER, FAILED]
    assert len(history.transfers) == 2


def test_a_history_longer_than_the_budget_raises_rather_than_truncates(monkeypatch):
    monkeypatch.setattr("open_leprechaun.ports.solana._MAX_SIGNATURES", 1)

    with pytest.raises(IndexerError, match="more than 1 transactions"):
        indexer(Endpoint({PAYER: [TRANSFER, FAILED]})).history(PAYER)


def test_a_second_read_asks_only_for_what_could_have_changed():
    """A finalized transaction never changes: the commit that follows a
    preview lists signatures again but fetches no transaction twice."""
    endpoint = Endpoint({PAYER: [TRANSFER]})
    reader = indexer(endpoint)

    first = reader.history(PAYER)
    listed_once = len(endpoint.called("getSignaturesForAddress"))
    second = reader.history(PAYER)

    assert first == second
    assert len(endpoint.called("getTransaction")) == 1
    assert len(endpoint.called("getSignaturesForAddress")) == 2 * listed_once


# --- What the indexer cannot judge, said rather than guessed ---


def test_one_asset_in_and_another_out_is_flagged_as_a_likely_swap():
    history = indexer(Endpoint({PAYER: [TRANSFER]})).history(PAYER)

    (warning,) = history.warnings
    assert warning.startswith("1 transaction moved one asset in and another out")


def test_a_transaction_touching_the_stake_program_is_flagged():
    endpoint = Endpoint({TIPPED: [TRANSFER]})
    recorded = json.loads(json.dumps(endpoint.transactions[TRANSFER]))
    recorded["result"]["transaction"]["message"]["accountKeys"][7]["pubkey"] = (
        "Stake11111111111111111111111111111111111111"
    )
    endpoint.transactions[TRANSFER] = recorded

    history = indexer(endpoint).history(TIPPED)

    (warning,) = history.warnings
    assert warning.startswith("1 transaction touched the Stake program")


# --- The endpoint's own failures, and what is not an address ---


@pytest.mark.parametrize(
    "not_an_address",
    ["not-an-address", "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984", "", TRANSFER, PAYER + "abc"],
)
def test_what_is_not_a_solana_address_is_refused_before_anything_is_asked(not_an_address):
    endpoint = Endpoint({})

    with pytest.raises(AddressRejectedError, match="not a Solana address"):
        indexer(endpoint).history(not_an_address)

    assert endpoint.calls == []


def test_a_rate_limit_waits_as_asked_and_then_reads_on():
    endpoint = Endpoint({TIPPED: [TRANSFER]})
    endpoint.rate_limited = 2
    waited: list[float] = []

    history = indexer(endpoint, sleep=waited.append).history(TIPPED)

    assert waited == [7.0, 7.0]
    assert len(history.transfers) == 1


def test_a_rate_limit_that_never_lifts_raises_its_sentence():
    endpoint = Endpoint({TIPPED: [TRANSFER]})
    endpoint.rate_limited = 100

    with pytest.raises(IndexerError, match="rate-limiting"):
        indexer(endpoint, sleep=lambda seconds: None).history(TIPPED)


def test_the_endpoints_own_refusal_is_carried_as_the_failure():
    """Recorded: what the endpoint answers a transaction newer than the
    declared format."""

    def refuses(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "error": {"code": -32015, "message": "Transaction version (2) is not supported"},
                "id": 1,
            },
        )

    with pytest.raises(IndexerError, match="Transaction version"):
        indexer(refuses).history(TIPPED)


def test_an_unreachable_endpoint_is_an_indexer_failure():
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(IndexerError, match="not answering"):
        indexer(unreachable).history(TIPPED)


def test_a_transaction_without_a_time_is_refused_rather_than_placed_by_guess():
    endpoint = Endpoint({TIPPED: [TRANSFER]})
    recorded = json.loads(json.dumps(endpoint.transactions[TRANSFER]))
    recorded["result"]["blockTime"] = None
    endpoint.transactions[TRANSFER] = recorded

    with pytest.raises(IndexerError, match="states no time"):
        indexer(endpoint).history(TIPPED)


def test_a_transaction_the_endpoint_no_longer_serves_is_refused():
    endpoint = Endpoint({TIPPED: [TRANSFER]})
    endpoint.transactions[TRANSFER] = {"jsonrpc": "2.0", "id": 1, "result": None}

    with pytest.raises(IndexerError, match="no longer serves"):
        indexer(endpoint).history(TIPPED)
