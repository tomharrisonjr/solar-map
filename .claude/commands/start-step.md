---
description: Begin implementing one step of a docs/plans/ plan doc — child GitHub issue, isolated worktree, branch.
argument-hint: <plan-doc-path> <step-number>
---

Start implementing a single step of a plan doc. Arguments: `$ARGUMENTS` — a path to a
plan doc under `docs/plans/` and a step number (e.g. `docs/plans/foo.md 3`). If either is
missing or ambiguous, ask.

Follow this procedure exactly:

1. **Read the plan doc.** Find the `GitHub Issue:` header line (the parent issue) and the
   steps table row for the requested step number, plus that step's `## Step N — <title>`
   section.
   - If the header is still `TBD (#___)` (an older plan predating this convention),
     create the parent issue now: `gh issue create --title "<plan title>" --body
     "<one-paragraph summary from the plan's Context section>\n\nSee docs/plans/<file>."`,
     then update the header in place to `GitHub Issue: #<n>` (this is a small edit to the
     plan doc, not implementation work — fine to commit directly on the current branch).

2. **Confirm the change type** — `chore`, `bug`, or `feature`. Infer it from the step's
   content if obvious (e.g. "fix" → bug, new capability → feature, tooling/docs/config →
   chore); otherwise ask with AskUserQuestion.

3. **Create the child issue**, linked to the parent:
   ```
   gh issue create --title "<plan title> — Step N: <step title>" \
     --body "Part of #<parent-issue-number>

   <the step's section body from the plan doc, verbatim>"
   ```
   Capture the new issue number from the output URL.

4. **Link it from the parent** so the parent shows sub-issue progress: fetch the parent's
   current body (`gh issue view <parent> --json body -q .body`), append a
   `- [ ] #<child-issue-number>` line (creating a `## Steps` section in the body if one
   doesn't exist yet), and write it back with `gh issue edit <parent> --body-file -`.

5. **Slugify the step title** into `<desc>`: lowercase, spaces/punctuation → `-`, trimmed
   to roughly 40 characters, no trailing hyphen.

6. **Create an isolated worktree on the new branch** — this is what keeps step work from
   colliding with whatever branch or process is currently running in the main checkout.
   Use the `EnterWorktree` tool with
   `name: "<type>/gh-<child-issue-number>-<desc>"` (e.g. `feature/gh-42-nearest-facility-api`).
   Do not use raw `git worktree` commands — `EnterWorktree` is the supported mechanism in
   this environment and handles branch creation, base ref, and later cleanup.

7. **Update the plan doc inside the new worktree**: set the step's row status to
   `🔄 In Progress` and note the issue number next to the step title (e.g.
   `## Step 3 — Minimal map UI (#43)`). Leave this as an uncommitted change — it becomes
   part of the step's first commit alongside the actual implementation.

8. **Report back**: the child issue URL, the branch name, and confirmation that the
   session is now working inside the new worktree. Do not start writing implementation
   code yet unless the user's original request also asked for that — this command's job
   is to get the workspace ready.
