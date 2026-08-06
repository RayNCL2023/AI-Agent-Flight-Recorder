/** Word-level LCS diff for comparing answer texts between branches. */

export interface DiffToken {
  kind: "same" | "removed" | "added";
  text: string;
}

export function wordDiff(a: string, b: string): DiffToken[] {
  const wa = a.split(/(\s+)/).filter((w) => w.length > 0);
  const wb = b.split(/(\s+)/).filter((w) => w.length > 0);
  const m = wa.length;
  const n = wb.length;

  // LCS table (guard against pathological sizes).
  if (m * n > 500_000) {
    return [
      { kind: "removed", text: a },
      { kind: "added", text: b },
    ];
  }
  const dp: number[][] = Array.from({ length: m + 1 }, () =>
    new Array<number>(n + 1).fill(0),
  );
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] =
        wa[i] === wb[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const out: DiffToken[] = [];
  let i = 0;
  let j = 0;
  const push = (kind: DiffToken["kind"], text: string) => {
    const last = out.at(-1);
    if (last && last.kind === kind) last.text += text;
    else out.push({ kind, text });
  };
  while (i < m && j < n) {
    if (wa[i] === wb[j]) {
      push("same", wa[i]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push("removed", wa[i]);
      i++;
    } else {
      push("added", wb[j]);
      j++;
    }
  }
  while (i < m) push("removed", wa[i++]);
  while (j < n) push("added", wb[j++]);
  return out;
}
