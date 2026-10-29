# subnt-dev-site: brainstorm

Date: 2026-10-30. Session 1 of the greenfield lifecycle.

## Goal

Build a distinctive, professionally designed site in `web/`, served at
subnt.dev. It has two jobs:

- A public site anyone can open, with excellent UX.
- A glance view for the owner of the data Atlas builds and consolidates.

No audience split. The design carries both jobs.

## Success signals

- A visitor with no context understands what Atlas is within one screen.
- The site looks distinct, not like a default component-library template.
- Dark mode is first class, not an afterthought.
- Motion is purposeful and respects `prefers-reduced-motion`.
- The owner can glance at Atlas data without leaving the site.

## Constraints and non-goals

- Visual design is the priority. Data wiring is secondary for now.
- Stack (owner choice): Next.js, Tailwind v4, shadcn/ui, TypeScript,
  Motion, dark mode.
- No logins, no wallet tracking, no trading-advice framing, no public
  chat, no paid Desearch in v1.
- The Pi is LAN-only. Data reaches the site only through a validated
  snapshot pushed to Supabase (see memory `subnt-dev-frontend-plan`).
- The runtime upgrade job must not be able to edit `web/` (add a test).
- Vercel ignored-build step so upgrade pushes to `main` do not redeploy.

## Options considered

1. Thin slice first: full data pipeline, one data page. Rejected. It
   spends the effort on plumbing the owner is not focused on now.
2. Design shell first: full site frame and all four board pages on
   fixture data, real data wired page by page afterward. Chosen.

## Chosen direction

Design shell first, on typed fixture data.

- Pages: home (what Atlas is), mining triage, fleet attention with
  rotation signals, network pulse, runtime-upgrade timeline.
- Fixtures sit behind one typed data layer. Swapping fixtures for the
  Supabase snapshot later changes that layer only.
- Server render with about 1 hour revalidate once real data lands.
- Design process: use only the owner's two skills, installed globally
  2026-10-30. Do not use the local `ui-craft*` or `show-me` skills.
  - `design-taste-frontend` (taste-skill v2, `~/.claude/skills/`):
    deals directions with `scripts/draw.mjs`, inspects with
    `scripts/inspect.mjs`. Needs Node 22+ (have 24) and Chrome, Edge or
    Chromium (not found on this machine). Pages and app screens have
    separate runs.
  - `ui-ux-pro-max` (`~/.claude/skills/`): run
    `python3 ~/.claude/skills/ui-ux-pro-max/scripts/search.py "<query>" --design-system`.
    The SKILL.md path uses `${CLAUDE_PLUGIN_ROOT}`, which is unset here.
    Use the full path.
- Atlas README still calls subnt.dev retired. Fix when the site ships.

## Open questions

1. Next.js version: owner asked for 15. A newer major may exist as of
   2026-10. Confirm 15 on purpose or take current stable.
2. Browser for the taste-skill inspector: install Chromium, or point
   the scripts at an existing browser.
3. Aesthetic direction (one word each from owner, or `show-me` options
   in Session 2): editorial, terminal-instrument, or something else.
4. Fixtures: hand-written, or a one-off export from the live Atlas
   stores for realism.
5. Order of the later pipeline work (publisher, Supabase schema, leak
   scan, publish gate) relative to design milestones.
6. Retire subnt-trader timing: now, or after the site is live.
