# EasyInvio.com project instructions

## Authorized automatic Git synchronization

The user explicitly requested automatic commits and pushes after changes made
in response to their instructions. This authorization persists across sessions.

- Work directly in this project. After completing a requested change, run the
  relevant checks, review the diff, commit the changes and push to `origin`.
  Do not ask for confirmation again for these routine commits and pushes.
- The user requires completed changes, including future tasks, to be carefully
  integrated and pushed to `origin/main` after verification. Develop on the current
  feature branch as appropriate, then merge into main without rewriting history.
  Use a clean isolated worktree for integration when the working checkout contains
  unrelated edits. Review conflicts and run relevant checks on the merged result.
  The configured repository is currently `sync4ai-lab/easyinvio` on GitHub.
  Verify the remote before pushing; explicit user changes to the destination
  take precedence over this recorded repository name.
- Commit coherent, completed work, not every intermediate edit. Use a clear
  commit message explaining the change. Report the feature/main commits and
  whether the pushes succeeded in the final response.
- Inspect the initial working-tree and staging state. Preserve unrelated user
  edits and staged changes; commit only the changes belonging to the task.
- Run checks appropriate to the change. For documentation-only changes, review
  the diff and run `git diff --check`; application tests are not required.
- Never stage `.env`, private keys, real credentials, tokens, customer exports
  or database dumps. Keep `.env.example` free of actual credentials.
- Never force-push, discard user changes or rewrite published history. Handle
  remote updates safely. If authentication, conflicts or required checks block
  synchronization, report the blocker rather than claiming the push succeeded.
- Git synchronization does not authorize deployments or additional database
  mutations. Preserve the task's existing database and integration boundaries.
  Keep automatic Git-triggered Vercel deployments disabled: the user will create
  the day's production deployment manually from the latest main commit.

This workflow covers agent-made changes. It does not install a file watcher or
automatically upload edits the user makes directly in their editor.

## Local/UAT-first workflow (user update, 21 November 2026)

The user's newer instruction supersedes automatic integration into main above:
work on a feature branch based on latest main, test locally, then integrate into
`uat` for a deliberately requested UAT deployment. Do not merge future changes
into main or deploy Production until the user approves that tested release.
Production domain: easyinvio.com. Intended UAT domain: uat.easyinvio.com.
Keep Git-triggered deployments disabled. Commit/push completed work to its
feature branch; a push is not a deployment. Do not move domains without checking
that a ready target deployment exists and reporting the resulting assignment.
The user requests one shared database. Do not claim data isolation: preserve
sandbox tenant/provider checks and never run competing local/UAT/Production
WhatsApp consumers for the same app/queue. No database changes are implied.
