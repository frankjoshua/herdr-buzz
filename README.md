# herdr-buzz

Glue between [Buzz](https://github.com/block/buzz) and [herdr-acp](../herdr-acp). herdr-acp is a
plain ACP agent that wraps a Herdr pane; this repo holds everything Buzz-specific:

- `mint.py` — create a Buzz agent identity owned by Josh from the CLI (keypair, NIP-OA auth tag,
  profile, bot membership). No desktop app involved. Stdlib only.
- `bin/herdr-buzz <agent> <pane> <channel>` — run `buzz-acp` for one pane under that identity,
  with the flags that make the pane feel like a channel member (subscribe all, kind 9 only,
  relay observer, top-level replies).

```
# once: Josh's owner nsec in ~/.config/buzz-acp/owner.env  (BUZZ_OWNER_NSEC=nsec1..., 0600)
python mint.py --name <agent> --channel <channel-id>
# pane shell, before starting the agent:
set -a; . ~/.config/buzz-acp/agents/<agent>.env; set +a
# bridge pane:
bin/herdr-buzz <agent> <pane-id> <channel-id>
```

Self-check: `python mint.py --selfcheck` (NIP-OA test vector + owner pubkey).
See NOTES.md for what buzz-acp / Buzz Desktop need and why.
