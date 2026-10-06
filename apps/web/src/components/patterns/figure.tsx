import {
  formatAssetAmount,
  formatMoneyExact,
  formatPrice,
  formatQuantity,
  formatRoundedAssetAmount,
  formatRoundedQuantity,
  formatRoundedSignedAssetAmount,
  formatRoundedSignedQuantity,
  formatMoneyRounded,
  formatSignedAssetAmount,
  formatSignedQuantity,
} from "@/lib/format";

/**
 * A figure rounded for reading, with the digits as stated one hover away —
 * a list shows what is enough to read, and never loses what was recorded.
 */
function Figure({ shown, exact }: { shown: string; exact: string }) {
  return shown === exact ? <>{shown}</> : <span title={exact}>{shown}</span>;
}

/**
 * An amount of an asset, rounded. Without `bare` the symbol stands beside it;
 * with it the symbol only decides the rounding, for a column that names the
 * asset elsewhere.
 */
export function Amount({
  value,
  symbol,
  signed = false,
  bare = false,
}: {
  value: string;
  symbol?: string;
  signed?: boolean;
  bare?: boolean;
}) {
  if (bare || symbol === undefined) {
    return signed ? (
      <Figure
        shown={formatRoundedSignedQuantity(value, symbol)}
        exact={formatSignedQuantity(value)}
      />
    ) : (
      <Figure shown={formatRoundedQuantity(value, symbol)} exact={formatQuantity(value)} />
    );
  }
  return signed ? (
    <Figure
      shown={formatRoundedSignedAssetAmount(value, symbol)}
      exact={formatSignedAssetAmount(value, symbol)}
    />
  ) : (
    <Figure
      shown={formatRoundedAssetAmount(value, symbol)}
      exact={formatAssetAmount(value, symbol)}
    />
  );
}

/** An amount of money off the API, rounded to the currency's minor unit. */
export function Money({ value, currency }: { value: string; currency: string }) {
  return (
    <Figure shown={formatMoneyRounded(value, currency)} exact={formatMoneyExact(value, currency)} />
  );
}

/** A price as its source states it, rounded; bare, because the source names no currency. */
export function Price({ value }: { value: string }) {
  return <Figure shown={formatPrice(value)} exact={formatQuantity(value)} />;
}
