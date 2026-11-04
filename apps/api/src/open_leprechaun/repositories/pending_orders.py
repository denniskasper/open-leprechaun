"""Writes and reads over what a broker last said it holds open for a Depot.

One `pending_order_observation` per Account, replaced whole with its
`pending_order` rows each time the broker is asked — an observation, never
history.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine, Row, text

from open_leprechaun.ports.broker import NormalizedPendingOrder


def replace(
    engine: Engine,
    account_id: int,
    *,
    as_of: datetime,
    error: str | None,
    orders: tuple[NormalizedPendingOrder, ...] = (),
    reserved_cash: Decimal | None = None,
    reserved_currency: str | None = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM pending_order_observation WHERE account_id = :account_id"),
            {"account_id": account_id},
        )
        connection.execute(
            text(
                "INSERT INTO pending_order_observation"
                " (account_id, as_of, error, reserved_cash, reserved_currency)"
                " VALUES (:account_id, :as_of, :error, :reserved_cash, :reserved_currency)"
            ),
            {
                "account_id": account_id,
                "as_of": as_of,
                "error": error,
                "reserved_cash": reserved_cash,
                "reserved_currency": reserved_currency,
            },
        )
        if orders:
            connection.execute(
                text(
                    "INSERT INTO pending_order (account_id, external_id, created_at, isin,"
                    " symbol, name, side, order_type, currency, quantity, value, limit_price,"
                    " stop_price) VALUES (:account_id, :external_id, :created_at, :isin,"
                    " :symbol, :name, :side, :order_type, :currency, :quantity, :value,"
                    " :limit_price, :stop_price)"
                ),
                [
                    {
                        "account_id": account_id,
                        "external_id": order.external_id,
                        "created_at": order.created_at,
                        # A broker always names a security by ISIN; only a
                        # statement may not, and a statement states no orders.
                        "isin": order.security.isin or "",
                        "symbol": order.security.symbol,
                        "name": order.security.name,
                        "side": order.side,
                        "order_type": order.order_type,
                        "currency": order.currency,
                        "quantity": order.quantity,
                        "value": order.value,
                        "limit_price": order.limit_price,
                        "stop_price": order.stop_price,
                    }
                    for order in orders
                ],
            )


def observations(engine: Engine) -> list[Row]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT account_id, as_of, error, reserved_cash, reserved_currency"
                    " FROM pending_order_observation ORDER BY account_id"
                )
            )
        )


def orders(engine: Engine) -> list[Row]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT account_id, external_id, created_at, isin, symbol, name, side,"
                    " order_type, currency, quantity, value, limit_price, stop_price"
                    " FROM pending_order ORDER BY account_id, created_at, external_id"
                )
            )
        )
