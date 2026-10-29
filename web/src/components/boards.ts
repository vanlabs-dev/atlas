import { Activity, GitCommitVertical, Pickaxe, Radar, type LucideIcon } from "lucide-react";

export interface BoardLink {
  href: string;
  label: string;
  question: string;
  icon: LucideIcon;
}

// The four boards, in reading order. One list for every nav on the site.
export const BOARDS: BoardLink[] = [
  { href: "/mining", label: "Mining triage", question: "Where can a new miner still earn?", icon: Pickaxe },
  { href: "/fleet", label: "Fleet attention", question: "Whose code moved, and does price agree?", icon: Radar },
  { href: "/network", label: "Network pulse", question: "How is the whole chain doing?", icon: Activity },
  { href: "/upgrades", label: "Runtime upgrades", question: "How often does the chain runtime change?", icon: GitCommitVertical },
];
