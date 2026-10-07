import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import {
  commitAddressImport,
  previewAddressImport,
  type AddressIndexer,
  type CommittedImport,
} from "@/api/imports";
import type { Platform } from "@/api/platforms";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { committedWords, UnpricedReport, PreviewReport } from "@/pages/imports";

/**
 * What reading a chain asks of the Admin, in one line: nothing but the
 * address. Said before anything is previewed, because every other way in
 * wants a key or a file.
 */
export function indexerWords(indexer: AddressIndexer): string {
  return `${indexer.name}'s history is public: the address is all that is asked, and nothing can be moved with it. Network fees are recorded in ${indexer.native_symbol}.`;
}

/** What the commit did — a re-read that found nothing new says so about the address, not a file. */
export function addressCommittedWords(committed: CommittedImport, locale?: string): string {
  return committed.batch_id === null
    ? "Nothing new — the ledger already knows this address's history."
    : committedWords(committed, locale);
}

/**
 * The address an Account already states for this chain, if any — offered as
 * the starting value so it is typed once. Only a suggestion: the reference
 * on an Account is the Admin's note, and what is read is what the field says.
 */
export function suggestedAddress(
  platforms: Platform[],
  accountId: string,
  chain: string,
): string | null {
  const account = platforms
    .flatMap((platform) => platform.accounts)
    .find((entry) => String(entry.id) === accountId);
  if (!account?.external_reference || account.chain?.toLowerCase() !== chain) return null;
  return account.external_reference;
}

export function AddressPanel({
  indexers,
  platforms,
  onDone,
}: {
  indexers: AddressIndexer[];
  platforms: Platform[];
  onDone: () => void;
}) {
  const fieldId = useId();
  // One chain needs no choosing.
  const [chain, setChain] = useState(indexers.length === 1 ? (indexers[0]?.chain ?? "") : "");
  const [accountId, setAccountId] = useState("");
  const [address, setAddress] = useState("");
  const queryClient = useQueryClient();

  const preview = useMutation({ mutationFn: previewAddressImport });
  const commit = useMutation({
    mutationFn: commitAddressImport,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["import-batches"] });
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["inbox"] });
    },
  });

  const chosen = indexers.find((indexer) => indexer.chain === chain);
  const trimmed = address.trim();
  const ready = chosen !== undefined && accountId !== "" && trimmed !== "";
  const request = { chain, address: trimmed, account_id: Number(accountId) };

  /** Any changed input outdates what was previewed or committed. */
  function outdate(): void {
    preview.reset();
    commit.reset();
  }

  /** A fresh choice of chain or Account offers the address that Account states, never over a typed one. */
  function suggest(nextAccountId: string, nextChain: string): void {
    if (trimmed !== "") return;
    const suggested = suggestedAddress(platforms, nextAccountId, nextChain);
    if (suggested) setAddress(suggested);
  }

  return (
    <section
      aria-label="Read an address"
      className="rise space-y-5 border-y border-border py-6"
      style={{ animationDelay: "80ms" }}
    >
      <div className="grid measure-form gap-4 sm:grid-cols-3">
        <div className="space-y-1.5">
          <label htmlFor={`${fieldId}-chain`} className="microlabel text-muted-foreground">
            Chain
          </label>
          <NativeSelect
            id={`${fieldId}-chain`}
            className="w-full"
            value={chain}
            onChange={(event) => {
              outdate();
              setChain(event.target.value);
              suggest(accountId, event.target.value);
            }}
          >
            <option value="">Choose…</option>
            {indexers.map((indexer) => (
              <option key={indexer.chain} value={indexer.chain}>
                {indexer.name}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1.5">
          <label htmlFor={`${fieldId}-account`} className="microlabel text-muted-foreground">
            Into Account
          </label>
          <NativeSelect
            id={`${fieldId}-account`}
            className="w-full"
            value={accountId}
            onChange={(event) => {
              outdate();
              setAccountId(event.target.value);
              suggest(event.target.value, chain);
            }}
          >
            <option value="">Choose…</option>
            {platforms
              .filter((platform) => platform.accounts.length > 0)
              .map((platform) => (
                <optgroup key={platform.id} label={platform.name}>
                  {platform.accounts.map((account) => (
                    <option key={account.id} value={account.id}>
                      {account.name}
                    </option>
                  ))}
                </optgroup>
              ))}
          </NativeSelect>
        </div>
        <div className="space-y-1.5">
          <label htmlFor={`${fieldId}-address`} className="microlabel text-muted-foreground">
            Public address
          </label>
          <Input
            id={`${fieldId}-address`}
            className="font-mono text-xs"
            autoComplete="off"
            spellCheck={false}
            value={address}
            onChange={(event) => {
              outdate();
              setAddress(event.target.value);
            }}
          />
        </div>
      </div>

      {chosen && <p className="measure-prose text-sm text-muted-foreground">{indexerWords(chosen)}</p>}

      <div className="flex flex-wrap items-center gap-2.5">
        <Button
          variant="outline"
          disabled={!ready || preview.isPending || preview.isSuccess}
          onClick={() => {
            if (ready) preview.mutate(request);
          }}
        >
          {preview.isPending ? "Reading the chain…" : "Preview"}
        </Button>
        {preview.isSuccess && !commit.isSuccess && (
          <Button
            disabled={commit.isPending}
            onClick={() => {
              if (ready) commit.mutate(request);
            }}
          >
            {commit.isPending ? "Committing…" : "Commit import"}
          </Button>
        )}
        <Button variant="ghost" className="text-muted-foreground" onClick={onDone}>
          {commit.isSuccess ? "Done" : "Cancel"}
        </Button>
        {preview.isPending && (
          <p className="measure-prose text-xs text-muted-foreground">
            A long history takes minutes — the chain is read one transaction at a time.
          </p>
        )}
        {commit.isSuccess && (
          <p className="font-mono text-xs text-signal">{addressCommittedWords(commit.data)}</p>
        )}
      </div>

      {commit.isSuccess && <UnpricedReport committed={commit.data} />}

      {preview.error && (
        <p role="alert" className="text-sm text-alarm">
          {preview.error.message}
        </p>
      )}
      {commit.error && (
        <p role="alert" className="text-sm text-alarm">
          {commit.error.message}
        </p>
      )}
      {preview.isSuccess && <PreviewReport preview={preview.data} />}
    </section>
  );
}
