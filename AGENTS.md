# EasyInvio.com project instructions

## Authorized automatic Git synchronization

The user explicitly requested automatic commits and pushes after changes made
in response to their instructions. This authorization persists across sessions.

- Work directly in this project. After completing a requested change, run the
  relevant checks, review the diff, commit the changes and push to `origin`.
  Do not ask for confirmation again for these routine commits and pushes.
- Use the current working branch unless the user asks for a different branch.
  The configured repository is currently `sync4ai-lab/veloce.ai` on GitHub.
  Verify the remote before pushing; explicit user changes to the destination
  take precedence over this recorded repository name.
- Commit coherent, completed work, not every intermediate edit. Use a clear
  commit message explaining the change. Report the branch, commit and whether
  the push succeeded in the final response.
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

This workflow covers agent-made changes. It does not install a file watcher or
automatically upload edits the user makes directly in their editor.
