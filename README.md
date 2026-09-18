# herdr-buzz

Glue between [Buzz](https://github.com/block/buzz) and
[herdr-acp](https://github.com/frankjoshua/herdr-acp). herdr-acp is a plain ACP agent that wraps a
Herdr pane; this repo holds everything Buzz-specific. Press `prefix+y` on any pane and it becomes a
Buzz channel: messages typed into the pane, everything the agent does posted back, people in the
channel able to prompt it.

## Setting up a machine

1. Herdr with the `herdr` CLI on PATH; Tailscale access to the relay.
2. [herdr-acp](https://github.com/frankjoshua/herdr-acp) cloned to `~/development/workspace/herdr-acp`
   and installed into its `.venv` (or point `HERDR_ACP` at the `herdr-acp` binary).
3. Buzz: the `buzz` CLI on PATH and a built `buzz-acp` at `~/buzz/target/release/buzz-acp`
   (or `BUZZ_ACP=<path>`). Both come from the [buzz](https://github.com/block/buzz) repo.
4. `~/.config/buzz-acp/owner.env` (mode 0600) with your Buzz private key and the relay:
   ```
   BUZZ_OWNER_NSEC=nsec1...
   BUZZ_RELAY_URL=wss://your-relay.example
   ```
   Optional: `~/.config/buzz-acp/members`, one pubkey per line, added to every channel the plugin
   creates; `~/.config/buzz-acp/herdr-buzz.flags`, extra buzz-acp flags.
5. `herdr plugin link ~/development/workspace/herdr-buzz` and the `prefix+y` binding below.
6. Check: `python3 mint.py --selfcheck` prints your owner pubkey.

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
