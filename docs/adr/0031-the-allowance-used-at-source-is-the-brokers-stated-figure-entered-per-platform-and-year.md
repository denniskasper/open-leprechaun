# The allowance used at source is the broker's stated figure, entered per Platform and year

## Status

accepted

## Context

A **Freistellungsauftrag** lets income pass untaxed at a German broker or bank until an allocated
slice of the **Sparerpauschbetrag** is used up. Whatever passed that way has consumed allowance the
§20 engine must not grant again (ADR-0013). Until now all the application recorded was the amount
*lodged* with each Platform: one current value, per Platform, with no year. That answers "how
much may this institution let through", not "how much did it let through in 2025". The engine
needs the second, and Anlage KAP Zeile 17 asks for it too.

The institution states that figure itself. Its annual tax certificate (Jahressteuerbescheinigung)
prints the "in Anspruch genommener Sparer-Pauschbetrag" for the year, and the Finanzamt receives
the same figure from it.

## Decision

The **allowance used at source** is a figure the Admin enters, per Platform and per Tax Year,
exactly as the certificate states it: euros to the cent, zero or more, at most one per Platform
and year. The application never works it out.

- It may stand on a `broker` or a `bank` Platform, the two kinds that can withhold, whatever that
  Platform's withholding behaviour is now. A certificate stays true after a broker stops
  withholding, and a past year can still be entered after the change.
- Any year may be entered, including years before the ledger's first event.
- A Platform holding any of them cannot be removed, because removing it would silently change a
  past year's tax. The figures are cleared one by one first.
- The lodged amount stays on the Platform, for information only. The used amount, not the
  lodged one, reduces the allowance.

## Considered Options

- **Derive it from the ledger.** Rejected: the institution nets income against its own loss pots
  (Verlustverrechnungstöpfe), applies its own timing and sees only its own accounts. A figure
  recomputed here would drift from the certificate the Finanzamt also receives, and it would be
  wrong for an institution whose history the ledger does not hold in full.
- **One total per year.** Rejected: certificates arrive per institution, and the Admin checks
  each figure against its own document. A single total cannot be checked against any one
  certificate, and correcting one institution's figure would mean re-adding the others.
- **Make the lodged amount per year.** Rejected: the order lodged is a ceiling, not what was
  used. An institution whose income stayed below its slice used less than was lodged, and the
  engine would claim allowance that was never consumed at source as consumed.

## Consequences

- The engine and the report can read the year's total across Platforms without any rule of
  their own about how an institution counts.
- A figure the Admin has not entered is unknown, not zero. Entering 0 is how an unused order is
  stated.
- A bank the ledger does not otherwise track can be registered as a `bank` Platform with no
  Accounts, solely to hold its figures.
- A used total above the allowance is stored as stated. Capping it is the engine's concern, not
  the record's.
