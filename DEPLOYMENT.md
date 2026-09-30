# Windows production deployment

The deployed release is in the sibling directory `unlock_bot_release_20260930`,
on branch `feat/max-production`. The original `unlock_bot` directory, its local
changes, configuration, and database have been retained for recovery.

The release uses its own `.env` and `users-live.db`. SQLite migration backups
are beside that database. Do not copy a database while it is running; use the
SQLite backup API. Do not start the original and new bots simultaneously.

## Startup and diagnostics

Task Scheduler task `UnlockBotTelegramMax` starts
`.venv\Scripts\python.exe -m unlock_bot.scripts.start` with the release directory
as its working directory. It starts at the bot account's logon and retries
failed execution every minute. Logs are in the release's `Logs` directory.

The task currently uses an **interactive logon**. Disconnecting remote access
does not sign out the account, but signing out stops the bot. After a reboot,
the account must log in. Unattended boot requires a separately configured
domain service account or password-backed task with AD and proxy access;
do not switch to LocalSystem or S4U without verifying domain authentication.

```powershell
Get-ScheduledTask -TaskName UnlockBotTelegramMax
Get-ScheduledTaskInfo -TaskName UnlockBotTelegramMax
Start-ScheduledTask -TaskName UnlockBotTelegramMax
Stop-ScheduledTask -TaskName UnlockBotTelegramMax
```

## Migration and rollback

Migration preserves each distinct Telegram identity and its permissions.
Exact duplicate legacy rows are collapsed; conflicting rows for the same
Telegram ID abort migration. Shared AD accounts retain independent profiles.
New approved registrations for a shared AD account receive guest permissions,
never an arbitrarily selected owner's administrator permissions.

Before rollback, stop and disable the scheduled task and back up the current
release database. The original database is a pre-deployment snapshot: returning
to it loses subsequent registrations and approvals unless reconciled. The old
version only serves Telegram. Restore its original startup only after checking
that no new-release Python process remains.

## Acceptance check

In MAX, start the bot, submit a work email, and approve the request in the
existing Telegram admin chat. Verify that confirmation arrives in MAX. Test
`/unlock` in both messengers using the tester's own approved AD identity.
Check logs and confirm that pending notifications have been delivered.
