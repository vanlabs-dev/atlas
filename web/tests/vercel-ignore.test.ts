import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync, execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const SCRIPT = join(import.meta.dirname, "../scripts/vercel-ignore.sh");

// A throwaway repository: commit A changes web/, commit B changes only
// a path outside it. The step runs from web/, as Vercel runs it.
function repo() {
  const root = mkdtempSync(join(tmpdir(), "vercel-ignore-"));
  const git = (...args: string[]) =>
    execFileSync("git", ["-c", "user.name=t", "-c", "user.email=t@example.org", ...args], { cwd: root, encoding: "utf8" }).trim();
  git("init", "-q");
  mkdirSync(join(root, "web"));
  writeFileSync(join(root, "web/page.txt"), "a\n");
  git("add", ".");
  git("commit", "-qm", "site");
  const a = git("rev-parse", "HEAD");
  writeFileSync(join(root, "corpus.md"), "b\n");
  git("add", ".");
  git("commit", "-qm", "corpus only");
  return { root, a, cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

function step(root: string, env: Record<string, string>) {
  // The caller's environment minus any real Vercel values, plus the case's own.
  const base = { ...process.env };
  delete base.VERCEL_GIT_PREVIOUS_SHA;
  delete base.VERCEL_GIT_COMMIT_MESSAGE;
  return spawnSync("bash", [SCRIPT], { cwd: join(root, "web"), env: { ...base, ...env } }).status;
}

test("a push that changes nothing under web/ skips the build", () => {
  const r = repo();
  try {
    assert.equal(step(r.root, { VERCEL_GIT_PREVIOUS_SHA: r.a }), 0);
  } finally {
    r.cleanup();
  }
});

test("an unknown previous commit builds", () => {
  const r = repo();
  try {
    assert.equal(step(r.root, {}), 1);
    assert.equal(step(r.root, { VERCEL_GIT_PREVIOUS_SHA: "0".repeat(40) }), 1);
  } finally {
    r.cleanup();
  }
});

test("a [build] commit message always builds, for variable-only changes", () => {
  const r = repo();
  try {
    assert.equal(step(r.root, { VERCEL_GIT_PREVIOUS_SHA: r.a, VERCEL_GIT_COMMIT_MESSAGE: "Apply new store settings [build]" }), 1);
  } finally {
    r.cleanup();
  }
});
