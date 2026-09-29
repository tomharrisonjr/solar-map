# Agent-neutral worktree workflow (Taskfile + AGENTS.md)

- GitHub Issue: #6
- Date: 2026-09-29
- Status: Draft

## Steps

| Status | # | Step |
|--------|---|------|
| ⬜ Pending | 1 | Taskfile with worktree + check tasks |
| ⬜ Pending | 2 | AGENTS.md as the source of truth; CLAUDE.md points to it |
| ⬜ Pending | 3 | Slim /start-step to call `task wt:new` |
| ⬜ Pending | 4 | Wrap-up (docs, .gitignore, verify end-to-end) |

## Context

Working in a git worktree needs setup that Git doesn't do: gitignored config (`backend/.env`),
a consistent location, branch naming, and cleanup. Today `/start-step` does this via Claude's
`EnterWorktree` tool, which is Claude-specific, mangles branch names (`/`→`+`, `worktree-`
prefix), branches from `origin/main` rather than local `main`, and puts worktrees under
`.claude/worktrees/`. We also hit port 5432/8000 collisions when a worktree's compose stack ran
next to the main checkout's.

Goal: put the deterministic steps in a Taskfile (runnable by a human, CI, Cursor, or Claude),
keep only judgment work (read plan, infer type, write issue text) in the slash command, and put
repo-level agent instructions in `AGENTS.md` (vendor-neutral) with `CLAUDE.md` pointing at it.

Decisions: worktrees live in a sibling folder `../solar-map.worktrees/<branch-slug>/`; the
worktree is created by `task wt:new` (plain `git worktree add -b`), not `EnterWorktree`.
`task` is already installed (Homebrew).

## Step 1 — Taskfile with worktree + check tasks

New `Taskfile.yml` at repo root:

- `wt:new -- <branch>` — `git worktree add -b <branch> ../solar-map.worktrees/<slug> main`
  (slug = branch with `/`→`-`); then bootstrap: symlink `backend/.env` to the main checkout's
  copy (create from `.env.example` in main if missing); print the worktree path.
- `wt:rm -- <branch>` — `docker compose down -v` in the worktree, `git worktree remove`,
  optionally `git branch -d`.
- `wt:list` — `git worktree list`.
- `check` — `docker compose run --rm web ruff check .` then `... manage.py test` (the repo's
  "before done" gate, currently only in CLAUDE.md).
- Port collisions: make `docker-compose.yml` host ports configurable
  (`"${DB_PORT:-5432}:5432"`, `"${WEB_PORT:-8000}:8000"`) and have `wt:new` pick free ports
  into a worktree-local `.env` used by compose (or document one-stack-at-a-time). Decide during
  implementation; prefer the simple env-var default.
- Bootstrap caveat: this feature is built on a normal chore branch off `main`, since the task
  doesn't exist yet.

## Step 2 — AGENTS.md as the source of truth; CLAUDE.md points to it

- Move the content of `CLAUDE.md` into `AGENTS.md`; make `CLAUDE.md` a symlink to `AGENTS.md`
  (fallback if symlinks are unwanted: one-line file importing it).
- Add a "Worktrees" section: use `task wt:new`/`wt:rm`; where they live; `.env` is symlinked;
  run `task check` before calling work done. Update the Commands section to mention Taskfile.

## Step 3 — Slim /start-step to call `task wt:new`

Edit `.claude/commands/start-step.md`: keep steps 1–5 and 7–8 (plan reading, type inference,
child issue, parent link, slug, plan-doc status edit, report). Replace step 6 (`EnterWorktree`
and its two quirk notes) with `task wt:new -- <type>/gh-<n>-<desc>`, then point the session at
the printed path (edit the plan doc there, run commands with that as cwd). Remove the quirk
notes. The `.claude/worktrees/` `.gitignore` entry can stay for legacy worktrees.

## Step 4 — Wrap-up

- `task check` passes (ruff + tests).
- Update `docs/requirements.md`/`AGENTS.md` if they describe the workflow; set this plan's
  `Status` to `Complete`.
- New env vars (`DB_PORT`, `WEB_PORT`) go in `backend/.env.example` with comments.

## Verification

1. `task wt:new -- chore/gh-0-smoke` from the main checkout: worktree appears at
   `../solar-map.worktrees/chore-gh-0-smoke`, branch name exact, based on local `main`,
   `backend/.env` present.
2. In that worktree: `task check` passes; `docker compose up -d db` works while the main
   checkout's stack is also running (no port clash).
3. `task wt:rm -- chore/gh-0-smoke` removes folder, volume, and branch.
4. Run `/start-step` on a real plan step end-to-end and confirm it lands in a sibling worktree.
5. Open the repo in Cursor and confirm it picks up `AGENTS.md` (check Cursor's current docs).
