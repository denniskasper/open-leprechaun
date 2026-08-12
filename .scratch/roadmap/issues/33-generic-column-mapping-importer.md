# 33 — Generic column-mapping importer

**What to build:** An unsupported venue does not block the Admin. Map an arbitrary file's columns onto ledger fields, see the first rows interpreted live, then save the mapping under a name and reuse it.

**Blocked by:** 31

**Status:** done

- [x] The mapping UI shows a live preview of the first rows as they would be interpreted
- [x] Required fields are enforced before the import can proceed
- [x] Ambiguous dates require an explicit format and timezone; nothing is guessed
- [x] A mapping can be saved, named and reused against a later file
- [x] The result flows through the same preview, batch and reversal machinery as any other import

## Comments

Implemented. The port (`ports/column_mapping.py`) reads a file two ways under one
`ColumnMapping` declaration: `interpret` is lenient — the mapping screen's live preview,
answering every row it can with a problem sentence for each cell it cannot — and
`MappingConnector` wears the CSV Connector protocol strictly, so the mapped file reaches
ticket 31's evaluation through the same `services/csv_imports` seam every shipped connector
uses (`preview_of`/`commit_of`, extracted for this). Saved mappings are one table
(`column_mapping`, revision `f2a94c8e51d7`), upserted by name. The Imports screen grew a
second flow ("Map a file", `pages/imports-mapping.tsx`) beside the connector picker; a
Playwright journey maps an invented venue's semicolon/decimal-comma export end to end.

How each criterion is held:

- **Live preview**: `POST /column-mappings/interpret` answers the file's columns (the pickers
  are built from them), the first 20 rows as the import would read them — UTC timestamps,
  fixed-point strings, direction from the type never the sign — every distinct type value for
  the translation rows, and the defects still standing. The screen re-asks it a beat (250 ms)
  after every change.
- **Required fields enforced**: the port's `defects` names each missing declaration in a
  sentence; saving and importing both refuse (422) while any stands, and the commit re-judges
  server-side — the disabled button is never the only guard.
- **Nothing guessed about dates**: the mapping declares an exact strptime format and an IANA
  timezone; a format carrying `%z` must not declare a timezone besides (each row converts by
  its own offset). DST is pinned by a summer and a winter row. The delimiter and the decimal
  convention (comma vs point) are likewise declared, never sniffed.
- **Saved, named, reused**: upsert by name — one name is one current declaration — listed,
  loadable into the editor, deletable. Translation rows union what the file carries with what
  the mapping already declares, so a saved mapping reused on a new file keeps its rows.
- **Same machinery**: the strict parse hands `NormalizedRow`s to the framework; batch, dedup,
  idempotent re-import, authoritative source and reversal are all the framework's own, pinned
  over HTTP in `test_mapped_imports.py`.

Decisions worth recording:

- **The provenance source is `mapping:<account_id>`** — it stems from the flow, never from
  which saved mapping read the file, so renaming, refining or deleting a mapping cannot detach
  an Account from its import history; a re-import under a re-saved mapping still changes
  nothing (pinned). The trade-off is one dedup namespace per Account across the mapped flow —
  acceptable because ticket 31 already holds one authoritative source per Account.
- **Only single-role types are mappable** (`MAPPED_TYPES`, pinned to `TRANSACTION_TYPES` on
  both API and web): one file row states one movement, so a trade's two sides never fit, and
  an opening balance is the Admin's declaration, never an import's. Broker exports with real
  trades are ticket-88 territory.
- **A type value maps to a type or to "leave out"** — an undeclared value is a stated problem
  and refuses the strict parse; leave-out rows and zero-amount rows are counted in a warning,
  never dropped in silence.
- **No identifier column → identifiers derive from row content**, with an occurrence counter
  keeping genuinely identical rows distinct — stable across re-exports, so re-importing the
  same file stays idempotent.
- **Strict where the preview was lenient**: a cell the mapping cannot read refuses the whole
  file naming its row — mis-parsing part of a file writes wrong history.
- No version bump — releases have not started; rides as `feat:` like tickets 10–32.
- Post-review fixes (two-axis review): a multi-character or empty delimiter now answers its
  defect instead of crashing the interpreter (the API schema accepts any string); the save
  endpoint returns the row by `RETURNING` instead of re-listing; the saved-mappings picker
  surfaces a load failure with retry; the web `MAPPED_TYPES` copy is pinned against the web's
  own vocabulary schema; the file input is one shared component; an unused router dependency
  and a docstring typo went.
