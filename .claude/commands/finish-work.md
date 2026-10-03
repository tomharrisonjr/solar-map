---
description: Finish the current issue's work — verify (tests, lint, build, packages), get approval, commit, open a PR, return to the main checkout and pull.
argument-hint: [worktree-path-or-branch]
---

Wrap up the work for one issue and open its PR. Optional argument: `$ARGUMENTS` — a
worktree path or branch name. Follow this procedure in order; stop and report if any
verification step fails (don't commit or open a PR on red).

1. **Pick the worktree.**
   - Run `git worktree list`. The first entry is the primary checkout (the "main code
     window"); remember its path for step 8.
   - If the session is already inside a non-primary worktree (`git rev-parse
     --show-toplevel` differs from the primary path), use it.
   - Otherwise use `$ARGUMENTS` if given. If not: with no non-primary worktrees, say so
     and stop; with exactly one, use it and say which (`AskUserQuestion` rejects
     single-option questions); with several, list them with `AskUserQuestion` (branch +
     path) and let the user choose.
   - If the chosen worktree isn't the session's current directory, switch in with
     `EnterWorktree` (`path` parameter), and do all remaining work from it.

2. **Identify the issue.** Branches are named `<type>/gh-<n>-<desc>`; parse `<n>` from
   `git branch --show-current`. Fetch it with `gh issue view <n> --json title,body,url`.
   Refuse to continue on `main` or a branch without an issue number — ask the user instead.

3. **Verify, from the worktree.** Run all of these and report each result; don't skip one
   because an earlier one passed:
   - `task check` — ruff lint + Django tests (the repo's "before done" gate).
   - **Build:** `docker compose build web` (catches Dockerfile/requirements breakage).
   - **Packages up to date:**
     - `docker compose run --rm web pip check` — installed packages are mutually
       consistent.
     - `docker compose run --rm web pip list --outdated` — report anything outdated. Don't
       upgrade unprompted: show the list and ask whether to bump (only if the issue is about
       dependencies) or note it in the PR as out of scope.
     - Confirm `backend/requirements*.txt` changes, if any, are intentional (`git diff
       main -- backend/requirements*.txt`).
   - **Migrations:** `docker compose run --rm web python manage.py makemigrations --check
     --dry-run` — fail if model changes lack a migration.
   - **Docs:** per `AGENTS.md`, confirm affected docs (`README.md`, `docs/requirements.md`,
     the plan doc) are updated, the plan step is `✅ Done`, and the plan's overall `Status`
     is `Complete` if this was its last step. Fix these now if not; any new env vars must be
     in the relevant `.env.example`.

4. **Show the changes and ask for approval.** Print `git status --short` and `git diff
   --stat` against `main`, plus a short summary of what changed and the verification
   results. Then use `AskUserQuestion`: *Commit and open PR* / *Make more changes first*.
   Do nothing further until approved. Never `git add -A` blindly — stage by path and make
   sure no `.env`, dataset, or other gitignored/local state is included.

5. **Commit.** Message: imperative summary line referencing the issue (e.g. `Add nearest
   facility endpoint (#42)`), a short body on the why if non-obvious, and the attribution
   trailer from the session's system reminder. Use a HEREDOC for the message.

6. **Push and open the PR.** `git push -u origin <branch>`, then `gh pr create` using
   `.github/PULL_REQUEST_TEMPLATE/template.md` as the body structure (fill "What", "Why",
   "Related issue" with `Closes #<n>`, and "Related doc" with the plan doc path if any),
   ending with the PR attribution line from the system reminder. If the plan has a parent
   issue, don't `Close` it — only the step's child issue.

7. **Report** the PR URL and the verification summary.

8. **Return to the main checkout and pull.** Call `ExitWorktree` with `action: "keep"` —
   **never `remove`**: the PR isn't merged and the branch must survive. Then, in the primary
   checkout path from step 1: `git switch main && git pull --ff-only`. If the primary
   checkout has uncommitted changes or `ExitWorktree` isn't available, say so and print the
   path instead of forcing it.

9. **Tell the user the cleanup step**: once the PR merges, run `task wt:rm -- <branch>` to
    stop the worktree's compose stack, delete its DB volume, and remove the worktree and
    branch. Don't run it yourself — the PR isn't merged yet.
