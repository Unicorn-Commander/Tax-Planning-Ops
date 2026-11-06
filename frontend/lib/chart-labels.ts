/** Horizontal collide-detect for SVG chart labels. Width is an estimate
 *  (fontSize 8.5 mono ≈ 5.15px/char); rows stack upward so neighbors such as
 *  NIIT and the next IRMAA tier do not share a baseline. */

export const LABEL_CHAR_PX = 5.15;
export const LABEL_GAP_PX = 8;
export const LABEL_ROW_PITCH = 12;

export interface PlacedLabel {
  x: number;
  text: string;
  row: number;
}

export function labelWidth(text: string): number {
  return text.length * LABEL_CHAR_PX;
}

/** Lowest row whose box does not overlap an earlier label. Input order is kept. */
export function staggerLabels(labels: { x: number; text: string }[]): PlacedLabel[] {
  const ordered = labels.map((label, index) => ({ ...label, index, row: 0 }));
  ordered.sort((a, b) => a.x - b.x || a.index - b.index);
  const rightEdge: number[] = [];
  for (const label of ordered) {
    const half = labelWidth(label.text) / 2;
    const left = label.x - half;
    let row = 0;
    while (row < rightEdge.length && left < rightEdge[row] + LABEL_GAP_PX) row += 1;
    rightEdge[row] = label.x + half;
    label.row = row;
  }
  ordered.sort((a, b) => a.index - b.index);
  return ordered.map(({ x, text, row }) => ({ x, text, row }));
}
