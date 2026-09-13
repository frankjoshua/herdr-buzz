# herdr-buzz

Glue between [Buzz](https://github.com/block/buzz) and [herdr-acp](../herdr-acp). herdr-acp is a
plain ACP agent that wraps a Herdr pane; this repo holds everything Buzz-specific:

- `mint.py` — create a Buzz agent identity owned by Josh from the CLI (keypair, NIP-OA auth tag,
  profile, bot membership). No desktop app involved. Stdlib only.
- `tee.py` — sits between buzz-acp and herdr-acp. Reduces prompts to `who: message`; posts tool
  calls and agent text to the channel as the agent, and pane input as the pane's owner. The pane agent needs no key, env, or
  instructions.
- `bin/herdr-buzz <agent> <pane> <channel>` — run `buzz-acp` + tee for one pane under that
  identity (subscribe all, kind 9 only, relay observer).

## As a Herdr plugin (the normal way)

`herdr plugin link ~/development/workspace/herdr-buzz` once, then in `~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "prefix+y"
type = "plugin_action"
command = "herdr-buzz.toggle"
```

Focus any pane (Claude, Codex, a shell) and press `prefix+y`. The workspace label becomes the
agent name and the channel name (channel created if missing, identity minted on first use), a
bridge pane opens below, and the sidebar shows `claude ⇄ #<channel>` on the pane. Press
`prefix+y` again to detach. Extra buzz-acp flags (e.g. `--respond-to anyone`) go in
`~/.config/buzz-acp/herdr-buzz.flags`.

## By hand

```
# once: Josh's owner nsec in ~/.config/buzz-acp/owner.env  (BUZZ_OWNER_NSEC=nsec1..., 0600)
python mint.py --name <agent> --channel <channel-id>
# bridge pane:
bin/herdr-buzz <agent> <pane-id> <channel-id>
```

Self-checks: `python mint.py --selfcheck`, `python tee.py --selfcheck`.
See NOTES.md for what buzz-acp / Buzz Desktop need and why.
