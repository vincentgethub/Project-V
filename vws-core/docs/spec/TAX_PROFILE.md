# TAX PROFILE (owner-supplied, Oct 6 2026)

To Codex: save under `docs/spec/TAX_PROFILE.md` and wire into TX-08 / the tax tracker and `vws setup` defaults. Do not invent rates beyond what TX already requires.

- Filing status: **single**
- State: **Texas** (no state income tax → state rate 0)
- Federal ST / LT / NIIT: use the TX-08 defaults for single; he can override later in setup
- Other accounts for wash-sale awareness (he enters or imports; code never logs into them):
  - IRA or Roth IRA
  - Merrill brokerage (taxable)
  - 401(k)
- Behavior: when he records a sale in Alpaca, prompt/check against lots he has marked from those other accounts (TX wash-sale engine already shared). Never move money. Never claim tax advice; numbers stay estimates; 1099-B wins.
