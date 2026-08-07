# One Section 20 Event shape feeds one capital-income engine

## Status

accepted

## Context

v1's annual summary carried flat, futures-shaped totals — gains, losses, taxable, allowance — with
no category, no statutory loss pot and no carryforward between years. Capital income from shares,
funds, dividends, interest or an advance lump sum had nowhere to go, and the allowance was applied
to a single source rather than to the combined picture the law actually taxes.

German law offsets capital-income losses only within statutory categories, caps some of them by
year, carries the unused remainder forward inside its own category, and then applies one allowance
across everything that survives. None of that can be expressed by a per-source calculator.

## Decision

Every source of capital income reduces to one **Section 20 Event**: a date, a category, a gross
amount, a partial-exemption rate, the German tax already withheld at source, any foreign
withholding with its source country, and a reference to the record that produced it.

One engine consumes that stream and nothing else. Per year, in order: group by category; net
within category; apply that category's per-year loss cap; consume that category's carryforward;
carry the remainder forward within the same category; sum surviving categories; apply the
allowance once, less any portion already consumed at source; apply the rate.

**No producer of capital income knows anything about categories, allowances or rates.** Futures,
share disposals, fund disposals, dividends, distributions, interest and advance lump sums are all
emitters.

## Considered Options

- **Extend the futures calculator with more fields.** Rejected: the allowance would still be
  applied per source, which is wrong in law, and each new source would touch the engine.
- **One engine per source, combined at report time.** Rejected: offsetting and carryforward are
  cross-source by category, so combining at the end cannot produce the right figure.

## Consequences

- This is the ordering constraint the whole rebuild turns on. The engine must exist, complete and
  category-driven, **before** futures are written — a producer written against a futures-shaped
  calculator cannot be reused, and discovering that later means rewriting the derivatives work.
- The engine is a pure function of events and configuration with no database dependency, so every
  statutory rule can have a test naming the paragraph it implements and failing individually.
- Each category accepts an opening carryforward entered from an assessment predating the ledger,
  because a loss established elsewhere still shelters income here.
