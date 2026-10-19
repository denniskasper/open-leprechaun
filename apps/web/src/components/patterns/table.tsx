import type { ComponentProps, ReactNode } from "react";
import { formatTimestampInColumn } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * The table pattern (docs/agents/design.md, "Tables"), the one way a table is
 * drawn. The frame spans the column and its table is only as wide as the
 * content needs: a few columns stay compact on the left, and the frame
 * scrolls sideways only when the content really does not fit — under a
 * pinned first column, never by hiding a column or restacking rows.
 */
export function Table({ className, ...props }: ComponentProps<"table">) {
  return (
    <div className="table-frame">
      <table className={cn("text-sm", className)} {...props} />
    </div>
  );
}

const FIGURE = "text-right font-mono text-xs tabular-nums whitespace-nowrap";

/**
 * A column heading: a microlabel, right-aligned over figures. It may break
 * onto a second line, so a column is as wide as its values need and not as
 * its caption happens to be.
 */
export function Heading({
  figure = false,
  className,
  ...props
}: ComponentProps<"th"> & { figure?: boolean }) {
  return (
    <th
      scope="col"
      className={cn(
        "microlabel py-2.5 pr-4 text-left align-bottom font-normal text-muted-foreground last:pr-0",
        figure && "text-right",
        className,
      )}
      {...props}
    />
  );
}

/** The cell that names its row — read out before every cell beside it. */
export function RowHeading({ className, ...props }: ComponentProps<"th">) {
  return (
    <th
      scope="row"
      className={cn("py-3 pr-4 text-left align-top font-normal last:pr-0", className)}
      {...props}
    />
  );
}

/** A cell; a `figure` stands right-aligned in the fixed-pitch face, on one line. */
export function Cell({
  figure = false,
  className,
  ...props
}: ComponentProps<"td"> & { figure?: boolean }) {
  return (
    <td
      className={cn("py-3 pr-4 align-top last:pr-0", figure && FIGURE, className)}
      {...props}
    />
  );
}

/**
 * A timestamp off the API, as a column states it: one line where there is
 * room, broken between its date and its time where there is not.
 */
export function Timestamp({ value }: { value: string }) {
  return <span className="whitespace-normal">{formatTimestampInColumn(Date.parse(value))}</span>;
}

/**
 * What a row opens beneath itself, across every column. It keeps to the
 * width in view, so it stays readable while the table scrolls under it.
 */
export function DetailRow({ columns, children }: { columns: number; children: ReactNode }) {
  return (
    <tr>
      <td colSpan={columns} className="pt-1 pb-5">
        <div className="sticky left-0 max-w-[100cqw]">{children}</div>
      </td>
    </tr>
  );
}
