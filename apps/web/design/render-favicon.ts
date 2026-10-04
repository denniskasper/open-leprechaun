// Draws the raster icons from public/favicon.svg — run by hand after changing
// the drawing, and commit what it writes: `node design/render-favicon.ts`.
// Chromium is the rasteriser because it is what will draw the SVG in a tab.

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const file = (name: string) => fileURLToPath(new URL(`../public/${name}`, import.meta.url));

const svg = readFileSync(file("favicon.svg"), "utf8");
const tile = svg.match(/<rect[^>]*fill="([^"]+)"/)?.[1];
if (!tile) throw new Error("favicon.svg has no tile to take a colour from");

const browser = await chromium.launch();

// `backdrop` fills the tile's rounded corners; without one they stay clear.
async function render(size: number, backdrop?: string): Promise<Buffer> {
  const page = await browser.newPage({ viewport: { width: size, height: size } });
  await page.setContent(
    `<body style="margin:0;background:${backdrop ?? "transparent"}">` +
      `<img width="${size}" height="${size}" style="display:block"` +
      ` src="data:image/svg+xml,${encodeURIComponent(svg)}">`,
  );
  const png = await page.screenshot({ omitBackground: backdrop === undefined });
  await page.close();
  return png;
}

// An .ico is a directory of images; each entry here is a PNG stored whole.
function ico(images: { size: number; png: Buffer }[]): Buffer {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);

  let offset = header.length + 16 * images.length;
  const entries = images.map(({ size, png }) => {
    const entry = Buffer.alloc(16);
    entry.writeUInt8(size, 0);
    entry.writeUInt8(size, 1);
    entry.writeUInt16LE(1, 4);
    entry.writeUInt16LE(32, 6);
    entry.writeUInt32LE(png.length, 8);
    entry.writeUInt32LE(offset, 12);
    offset += png.length;
    return entry;
  });

  return Buffer.concat([header, ...entries, ...images.map(({ png }) => png)]);
}

const sizes = [16, 32, 48];
const pngs = await Promise.all(sizes.map((size) => render(size)));
writeFileSync(file("favicon.ico"), ico(sizes.map((size, i) => ({ size, png: pngs[i]! }))));

// iOS masks the icon itself and paints a clear corner black, so this one is a
// full-bleed square.
writeFileSync(file("apple-touch-icon.png"), await render(180, tile));

await browser.close();
