import { DataAge } from "./data-age";

// Title row of a board: what it is, its one finding, and the data age.
export function BoardHeader({ title, finding, at }: { title: string; finding: string; at: string }) {
  return (
    <header className="flex flex-col gap-2 pb-8 pt-8">
      <h1 className="text-[24px] font-bold leading-tight tracking-[-0.01em]">{title}</h1>
      <p className="max-w-[70ch] text-lead leading-snug">{finding}</p>
      <DataAge at={at} />
    </header>
  );
}
