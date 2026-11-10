import { cacheLife } from "next/cache";
import { fetchBoard, mayUseFixture, revalidateSeconds, storeConfig, type BoardName, type RawBoard } from "./source-core";

// The live board source (change: supabase-data-layer). Each board is read
// from Supabase in a cached server function and refreshed in the
// background every 15 minutes, so new data reaches the pages without a
// deploy. If a refresh fails at run time, the error propagates and Next
// keeps serving the last good page. With no store configured, or when the
// store cannot be read while building, the committed fixture is used.

export interface ReadBoard extends RawBoard {
  /** When this copy was read from the store (or the fixture was used). */
  readAt: string;
}

/** A build-time read that failed. Cached like a board, so the next refresh retries. */
interface FailedRead {
  failed: string;
}

async function cachedBoard(name: BoardName): Promise<ReadBoard | FailedRead> {
  "use cache";
  const revalidate = revalidateSeconds(process.env);
  // stale stays at 5 minutes: under 30 seconds Next leaves the board out of
  // the prerender. It only sets how long a browser reuses a prefetch.
  cacheLife({ stale: 300, revalidate, expire: 365 * 86_400 });
  const config = storeConfig(process.env);
  try {
    if (!config) throw new Error("store not configured");
    const board = await fetchBoard(name, config);
    return { ...board, readAt: new Date().toISOString() };
  } catch (error) {
    // A throw inside a cached function fails the prerender, so a build
    // records the failure instead. At run time it must throw: that keeps
    // the last good page rather than replacing it with the fixture.
    if (!mayUseFixture(process.env)) throw error;
    return { failed: (error as Error).message };
  }
}

async function fixtureBoard(fixture: RawBoard): Promise<ReadBoard> {
  "use cache";
  cacheLife("max");
  return { generatedAt: fixture.generatedAt, data: fixture.data, readAt: new Date().toISOString() };
}

export async function readBoard(name: BoardName, fixture: RawBoard): Promise<ReadBoard> {
  if (!storeConfig(process.env)) return fixtureBoard(fixture);
  const board = await cachedBoard(name);
  if ("failed" in board) {
    console.warn(`subnt.dev build: ${name} board from the committed fixture (${board.failed})`);
    return fixtureBoard(fixture);
  }
  return board;
}
