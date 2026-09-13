# herdr-buzz

Glue between [Buzz](https://github.com/block/buzz) and [herdr-acp](../herdr-acp). herdr-acp is a
plain ACP agent that wraps a Herdr pane; this repo holds everything Buzz-specific:

- `mint.py` — create a Buzz agent identity owned by Josh from the CLI (keypair, NIP-OA auth tag,
  profile, bot membership). No desktop app involved. Stdlib only.
- `tee.py` — sits between buzz-acp and herdr-acp. Reduces prompts to `who: message`, posts tool
  calls and the final reply to the channel as the agent. The pane agent needs no key, env, or
  instructions.
- `bin/herdr-buzz <agent> <pane> <channel>` — run `buzz-acp` + tee for one pane under that
  identity (subscribe all, kind 9 only, relay observer).

```
# once: Josh's owner nsec in ~/.config/buzz-acp/owner.env  (BUZZ_OWNER_NSEC=nsec1..., 0600)
python mint.py --name <agent> --channel <channel-id>
# bridge pane:
bin/herdr-buzz <agent> <pane-id> <channel-id>
```

Self-checks: `python mint.py --selfcheck`, `python tee.py --selfcheck`.
See NOTES.md for what buzz-acp / Buzz Desktop need and why.
