# herdr-buzz — agent brief

Everything Buzz-specific for bridging a Herdr pane into a Buzz channel, on top of
[herdr-acp](https://github.com/frankjoshua/herdr-acp) (the client-agnostic ACP agent; keep it that way).

Owner: Joshua Frank. Routine calls: make them, note them in `NOTES.md` (decisions, verified vs.
assumed, dated). Never send Buzz messages as Joshua during tests; mint a throwaway identity.

## Pieces
- `tee.py` — sits on the stdio pipe between `buzz-acp` and `herdr-acp`. Downstream: strips
  buzz-acp's prompt to the humans' messages (owner unlabeled, others `name: text`), swallows the
  echo of our own owner-posted pane input. Upstream: forwards `session/update` to buzz-acp only
  during a turn (it never reads between turns; a full pipe stalls everything), and posts to the
  channel: tool calls with result excerpts as the agent, pane input as the owner. Templates and
  limits are the constants at the top.
- `mint.py` — a Buzz agent identity owned by Josh, from the CLI: keypair, NIP-OA auth tag
  (BIP-340 in stdlib, checked against the spec vector), profile, bot membership, env file.
- `bin/herdr-buzz <agent> <pane> <channel>` — runs buzz-acp + tee for one pane.
- `bin/toggle` + `herdr-plugin.toml` — the Herdr plugin action: `prefix+y` attaches/detaches the
  focused pane (channel named after the workspace, created if missing; members from
  `~/.config/buzz-acp/members`; a 2-row bridge pane below; sidebar decoration `agent ⇄ #channel`).

Config lives in `~/.config/buzz-acp/`: `owner.env` (Josh's nsec, never committed), `agents/*.env`
(minted identities, `BUZZ_CHANNEL` pinned per agent), `members`, `herdr-buzz.flags`.

Self-checks: `python3 tee.py --selfcheck`, `python3 mint.py --selfcheck`, `bash -n bin/*`.
Live check: attach a pane in your own Herdr Space and post from a throwaway key.
