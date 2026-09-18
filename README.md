# herdr-buzz

Glue between [Buzz](https://github.com/block/buzz) and
[herdr-acp](https://github.com/frankjoshua/herdr-acp). herdr-acp is a plain ACP agent that wraps a
Herdr pane; this repo holds everything Buzz-specific. Press `prefix+y` on any pane and it becomes a
Buzz channel: messages typed into the pane, everything the agent does posted back, people in the
channel able to prompt it.

## Install

1. Install [Buzz Desktop](https://github.com/block/buzz/releases) (the package ships the `buzz` CLI
   and `buzz-acp`) and sign in to your relay.
2. `herdr plugin install frankjoshua/herdr-buzz` — builds a venv with
   [herdr-acp](https://github.com/frankjoshua/herdr-acp) inside the plugin.
3. `herdr plugin pane open --plugin herdr-buzz --entrypoint setup` — paste your Buzz private key
   and relay URL (kept in `~/.config/buzz-acp/owner.env`, mode 600), and let it add the
   `prefix+y` binding.

Optional: `~/.config/buzz-acp/members` (pubkeys added to every channel the plugin creates, one per
line) and `~/.config/buzz-acp/herdr-buzz.flags` (extra buzz-acp flags).

## Use

Focus any pane (Claude, Codex, a shell) and press `prefix+y`. The workspace label becomes the
agent name and the channel name (channel created if missing, identity minted on first use), a
bridge pane opens below, and the sidebar shows `claude ⇄ #<channel>` on the pane. Press
`prefix+y` again to detach. The binding, if you'd rather add it yourself:

```toml
[[keys.command]]
key = "prefix+y"
type = "plugin_action"
command = "herdr-buzz.toggle"
```

Developing: `herdr plugin link <checkout>` uses the checkout in place; run `scripts/install.sh`
once for the venv.

## By hand

```
# once: your owner nsec in ~/.config/buzz-acp/owner.env  (BUZZ_OWNER_NSEC=nsec1..., 0600)
python mint.py --name <agent> --channel <channel-id>
# bridge pane:
bin/herdr-buzz <agent> <pane-id> <channel-id>
```

Self-checks: `python mint.py --selfcheck`, `python tee.py --selfcheck`.
See NOTES.md for what buzz-acp / Buzz Desktop need and why.
