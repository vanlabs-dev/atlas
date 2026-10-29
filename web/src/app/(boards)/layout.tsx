import { BoardRail } from "@/components/board-rail";

export default function BoardsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <BoardRail />
      <main className="min-h-svh pb-20 md:pb-0 md:pl-14">{children}</main>
    </>
  );
}
