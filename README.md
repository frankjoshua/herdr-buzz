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

Focus any pane (Claude, Codex, OMP, a shell) and press `prefix+y`. A small popup shows the pane's
bridge: attached or not, the agent and channel, the log tail, and the controls:

```
[a] attach   [d] detach   [x] detach + delete channel   [l] full log   [r] refresh   [q] close
```

Attaching names the agent and the channel after the workspace label (channel created if missing,
identity minted on first use, people from `~/.config/buzz-acp/members` added) and runs the bridge
in the background; no pane is taken. Closing the agent pane stops its bridge. Logs live in the
plugin's state dir. Extra buzz-acp flags (e.g. `--respond-to owner-only`) go in
`~/.config/buzz-acp/herdr-buzz.flags`. The binding, if you'd rather add it yourself:

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
