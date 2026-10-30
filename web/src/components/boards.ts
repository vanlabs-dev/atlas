export interface BoardLink {
  href: string;
  label: string;
  short: string;
  question: string;
}

// The four boards, in reading order. One list for every nav on the site.
export const BOARDS: BoardLink[] = [
  { href: "/mining", label: "Mining triage", short: "Mining", question: "Where can a new miner still earn?" },
  { href: "/fleet", label: "Fleet attention", short: "Fleet", question: "Whose code moved, and does price agree?" },
  { href: "/network", label: "Network pulse", short: "Network", question: "How is the whole chain doing?" },
  { href: "/upgrades", label: "Runtime upgrades", short: "Upgrades", question: "How often does the chain runtime change?" },
];

export const SOURCE = "https://github.com/vanlabs-dev/atlas";
