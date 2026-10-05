# If an account, key or computer may be compromised

Run `python -m vws ops panic --operator YOUR_NAME --reason "suspected compromise"`
on the host. It saves a local halt before contacting any service. Manual mode
has no order capability. Future auto mode cancels unfilled entries while retaining
protective orders. Panic never sells all holdings; decide that in the broker app.

From your phone, open Alpaca **API Keys** and regenerate the affected key pair.
Review withdrawals and orders you do not recognize. In Telegram, tell BotFather
`/revoke` for the affected bot. Secure your recovery email, revoke affected GitHub
tokens and rotate the Plaid secret or remove the affected item.

Use `python -m vws ops rotate-secret NAME` to replace affected credentials.
Never paste keys into chat or logs. The app validates replacement keys before
swapping them. Check Telegram Devices and enable its two-step password.

**Leaked key:** revoke first, inspect the broker account, then rotate every
affected secret. Keep the account halted until you have explained every change.

**Lost laptop:** revoke from your phone immediately. Restore an encrypted backup
on a clean, updated computer with disk encryption and a standard user account.
Rotate every credential. A missing backup key means backups cannot be restored;
keep the recovery key in your password manager.

**Telegram takeover:** revoke the bot token, remove unfamiliar Telegram devices,
secure the recovery email and rotate the token from the host. Telegram cannot
resume trading or enable live mode.

Run `python -m vws ops restore-test --file PATH.vwsbak` and
`python -m vws ledger verify-anchor --seq N --hash HASH` against an anchor saved
before the incident on another device or in Telegram. Restore-test verifies the
plaintext digest and every ledger chain in temporary storage. Do not resume on
an unexplained mismatch. Then run `python -m vws doctor`. The audited host reset
requires your explicit confirmation; never reset a halt simply to silence it.

Account-security checklist items are owner attestations, not remotely verified
settings. Broker logins/IPs are not assumed available through the API; review
its dashboard and email notices directly.
