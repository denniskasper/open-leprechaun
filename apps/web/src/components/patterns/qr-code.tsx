import { encode } from "uqr";

/**
 * The dark modules of the QR code for `text`, as one SVG path on a grid of
 * `size` units a side, quiet zone included. Drawn here rather than fetched as
 * an image: what it encodes is a secret, and it should not leave the page.
 */
export function qrPath(text: string): { size: number; path: string } {
  // The quiet zone is part of the symbol: four modules, per the standard,
  // or a scanner may not find the code against the surrounding page.
  const { data, size } = encode(text, { ecc: "M", border: 4 });
  const strokes: string[] = [];
  data.forEach((row, y) => {
    row.forEach((dark, x) => {
      if (dark) {
        strokes.push(`M${x} ${y}h1v1h-1z`);
      }
    });
  });
  return { size, path: strokes.join("") };
}

/**
 * A QR code on its own plate. A scanner wants dark modules on a light ground,
 * so the plate stays light in both themes — the paper surface in "paper", the
 * bone foreground in "ink" — rather than inverting with the page.
 */
export function QrCode({ text, label }: { text: string; label: string }) {
  const { size, path } = qrPath(text);

  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${size} ${size}`}
      shapeRendering="crispEdges"
      className="size-44 shrink-0 rounded-md border border-border bg-background dark:bg-foreground"
    >
      <path d={path} className="fill-foreground dark:fill-background" />
    </svg>
  );
}
