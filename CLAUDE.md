# herdr-buzz — agent brief

Everything Buzz-specific for bridging a Herdr pane into a Buzz channel, on top of
[herdr-acp](https://github.com/frankjoshua/herdr-acp) (the client-agnostic ACP agent; keep it that way).

Routine calls: make them, note them in `NOTES.md` (decisions and their reasons, dated). Never send
Buzz messages as the owner during tests; mint a throwaway identity.

## Pieces
- `tee.py` — sits on the stdio pipe between `buzz-acp` and `herdr-acp`. Downstream: strips
  buzz-acp's prompt to the humans' messages (owner unlabeled, others `name: text`), swallows the
  echo of our own owner-posted pane input. Upstream: forwards `session/update` to buzz-acp only
  during a turn (it never reads between turns; a full pipe stalls everything), and posts to the
  channel: tool calls with result excerpts as the agent, pane input as the owner. Templates and
  limits are the constants at the top.
- `mint.py` — a Buzz agent identity owned by the user, from the CLI: keypair, NIP-OA auth tag
  (BIP-340 in stdlib, checked against the spec vector), profile, bot membership, env file.
- `bin/herdr-buzz <agent> <pane> <channel>` — runs buzz-acp + tee for one pane.
- `bin/bridge attach|detach|delete|status|log <pane>` — the engine: channel named after the
  workspace (created if missing), identity minted on first use, members added, buzz-acp started
  in the background (`setsid`, pid in the session's state dir, log beside it; `lib/state.sh`). `delete` = detach + delete
  the pinned channel. `status` is the interface for supervisors (rostr): line 1 `attached`/`died`/`detached`,
  then the running `agent:`/`channel:`. The state files are private; keep them that way.
  `bin/menu` is the `prefix+y` popup over it; `bin/toggle` is the `prefix+y` action:
  attach when detached, otherwise open the popup; `bin/on-pane-closed` detaches when the pane goes away.
- `skills/buzz-messaging/SKILL.md` — the agent-facing skill (portable; installed copies elsewhere are
  copies of this one, so edit here and recopy). Keep it in step with `bridge status` and the tee's prompt format.

Config lives in `~/.config/buzz-acp/`: `owner.env` (the owner's nsec, never committed), `agents/*.env`
(minted identities, `BUZZ_CHANNEL` pinned per agent), `members`, `herdr-buzz.flags`.

Self-checks: `python3 tee.py --selfcheck`, `python3 mint.py --selfcheck`, `bash -n bin/*`.
Live check: attach a pane in your own Herdr Space and post from a throwaway key.
