# NOTES (herdr-buzz)

## Decisions
- **The pane agent is oblivious** (Josh, 2026-09-13). It gets no Buzz key, no footer, no
  instructions, and burns no tokens on Buzz. `tee.py` sits on the stdio pipe between buzz-acp and
  herdr-acp: it strips buzz-acp's prompt down to `who: message`, and posts tool calls
  (`▸ Bash: pwd` / `✓ Bash: pwd`) and the final assistant text to the channel as the agent.
  Templates are module-level strings in tee.py; `--tools none` posts only the reply;
  `--raw-prompt` forwards buzz-acp's prompt untouched.
- **Everything in the pane mirrors to the channel** (2026-09-13): `⌨ <text>` when a human types in
  the pane, every assistant text block as it appears, `▸`/`✓`/`✗` per tool call. Verified both
  directions on the real relay. buzz-acp accepts updates between turns without complaint.
- **Pane input posts as Josh** (2026-09-13). `user_message_chunk` is sent with `BUZZ_OWNER_NSEC`
  (no auth tag) so it reads as a message from the pane's owner, not from the agent. Buzz then hands
  that message back to the bridge as a prompt; the tee recognises its own recent owner posts and
  answers `end_turn` without touching the pane (`drop_echoes`).
- **The tee opens a session at startup** (`session/new`, id `tee-session`) because buzz-acp only
  opens one on the first channel message; without it nothing typed in the pane is mirrored until
  someone posts in Buzz. herdr-acp restarts its tail under buzz-acp's real session when it comes.
- buzz-acp still sees the full ACP stream, so typing indicator and observer feed are unchanged.
- Caveat: a Claude session that previously received Buzz instructions keeps replying itself
  from memory. Start a fresh session when switching a pane to the tee.

## Run it (no desktop involved)
```
# once: Josh's owner nsec in ~/.config/buzz-acp/owner.env  (BUZZ_OWNER_NSEC=nsec1..., 0600)
python mint.py --name <agent> --channel <id>   # keypair + NIP-OA auth tag + profile + bot member
# pane shell:  set -a; . ~/.config/buzz-acp/agents/<agent>.env; set +a   (before herdr agent start)
# bridge pane: bin/herdr-buzz <agent> <pane> <channel> [--respond-to ...]
```
Verified 2026-09-01 with agent `herdr-test` (14525e4e…): buzz-acp logs "owner resolved from
BUZZ_AUTH_TAG", replies post as the new agent, observer frames enabled.

## Run it (old way, raw flags)
```
# in its own pane in the target Space (never a service):
set -a; . ~/.config/buzz-acp/agent.env; set +a
~/buzz/target/release/buzz-acp --agent-command $REPO/.venv/bin/herdr-acp --agent-args=--pane,<PANE> \
  --subscribe all --no-mention-filter --agent-owner <josh-pubkey> --channels <channel-id> \
  --idle-timeout 120 --multiple-event-handling queue
```
`--agent-args` is comma-delimited in clap (`--pane,w47:p1`); a quoted `"--pane w47:p1"` is rejected.
The pane's process env must carry `BUZZ_PRIVATE_KEY`/`BUZZ_RELAY_URL` (`herdr workspace create --env ...`).

Self-checks: `python -m herdr_acp.reader`, `python -m herdr_acp.transport <pane>`,
`python tests/roundtrip.py <pane> "pwd"`.

## Buzz UI facts (learned the hard way)
- "View activity" (owner-only tool-call/thought transcript) only appears on members whose channel
  role is `bot`. A key that *creates* a channel is `owner`, and cannot change its own role
  (`missing p tag`); another admin/owner must set it: `buzz channels add-member --pubkey <agent> --role bot`.
- Channels created by the agent key are invisible to Josh until he is added as a member.

- **Tool calls / thoughts in Buzz Desktop** show in the per-agent session panel (click the agent in a
  channel), fed by relay observer frames (kind 24200, encrypted to the owner). Two prerequisites:
  1. buzz-acp `--relay-observer` (now on in the test pane).
  2. The agent key's kind:0 profile must carry a NIP-OA `auth` tag signed by Josh's owner key.
     That is what turns "owner unavailable" into "managed by josh" AND what makes the desktop ingest
     the observer frames (`ownerByPubkey == me`). Only Buzz Desktop's create-agent flow mints one;
     no CLI does. Managed agents' `auth_tag` lives in
     `~/.local/share/xyz.block.buzz.app/agents/managed-agents.json`, the nsec in the OS keyring.
     Josh's decision (2026-09-01): no desktop at all. His owner nsec lives on this box in
     `owner.env`; `herdr_acp.mint` signs the tag itself (BIP-340 in stdlib Python, checked
     against the NIP-OA test vector). Test-only key for now; he can rotate it any time.

