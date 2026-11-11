// Words and scales for the runtime-upgrades board. The areas group the
// subtensor repository's top-level directories (sitedata/compose.py
// AREAS). Import-free of aliases so the node tests can load it.

import type { Release } from "../data/types.ts";

export const AREAS = [
  { key: "filesRuntime", label: "Runtime", short: "Run" },
  { key: "filesPallets", label: "Pallets", short: "Pal" },
  { key: "filesEvm", label: "EVM", short: "EVM" },
  { key: "filesNode", label: "Node", short: "Node" },
  { key: "filesSdk", label: "SDK", short: "SDK" },
  { key: "filesDocs", label: "Docs", short: "Docs" },
  { key: "filesTooling", label: "Tooling", short: "Tool" },
] as const satisfies readonly { key: keyof Release; label: string; short: string }[];

/** Heat steps for files changed in one area: 0, 1 to 9, 10 to 39, 40 to 99, 100+. */
export const HEAT_STEPS = [0, 1, 10, 40, 100] as const;

export function heat(files: number): 0 | 1 | 2 | 3 | 4 {
  let level = 0;
  for (let i = 1; i < HEAT_STEPS.length; i++) if (files >= HEAT_STEPS[i]) level = i;
  return level as 0 | 1 | 2 | 3 | 4;
}

/** Files that change how the chain runs: runtime, pallets, EVM and node code. */
export function chainFiles(r: Release): number {
  return r.filesRuntime + r.filesPallets + r.filesEvm + r.filesNode;
}

/** "Includes spec 480" or "Includes specs 460, 461 and 462". */
export function bundledText(bundled: string | null): string | null {
  if (!bundled) return null;
  const specs = bundled.split(", ");
  if (specs.length === 1) return `Includes spec ${specs[0]}, never live on its own`;
  return `Includes specs ${specs.slice(0, -1).join(", ")} and ${specs[specs.length - 1]}, never live on their own`;
}

/** How the board names merged code no chain upgrade has shipped yet. */
export interface PendingView {
  /** waiting: the repository states a spec above the live one. unreleased: merged commits in no spec yet. */
  kind: "waiting" | "unreleased";
  /** Large label: the waiting spec, or "Next" for unreleased commits. */
  label: string;
  /** Heat-map row note under the label. */
  sub: string;
  heading: string;
  /** Second sentence of the board's finding. */
  finding: string;
  /** Line under the headline in the banner. */
  note: string;
}

/**
 * Merged code waits in one of two ways. When the repository already
 * states a spec above the live one, that spec is merged and waiting. When
 * it does not, the commits landed after the live spec shipped and are in
 * no spec yet; calling them "spec N, waiting" would name the live spec.
 */
export function pendingView(pending: Pick<Release, "spec" | "commits">, liveSpec: number, since: string): PendingView {
  if (pending.spec > liveSpec) {
    return {
      kind: "waiting",
      label: String(pending.spec),
      sub: "waiting",
      heading: "Merged, waiting",
      finding: `The chain runs spec ${liveSpec}; spec ${pending.spec} is merged and waiting.`,
      note: `In the repository since ${since}, not on chain yet.`,
    };
  }
  const commits = pending.commits === 1 ? "1 commit" : `${pending.commits} commits`;
  return {
    kind: "unreleased",
    label: "Next",
    sub: "unreleased",
    heading: `Merged since spec ${liveSpec}`,
    finding: `The chain runs spec ${liveSpec}; ${commits} merged since then ${pending.commits === 1 ? "is" : "are"} in no spec yet.`,
    note: `Merged after spec ${liveSpec} shipped, from ${since}. No spec number yet.`,
  };
}
