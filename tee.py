"""Sits between buzz-acp and herdr-acp on stdio. The agent in the pane stays oblivious.

    buzz-acp --agent-command python --agent-args=tee.py,--channel,<id>,--pane,<pane>

Downstream (buzz-acp → herdr-acp): every JSON-RPC line is forwarded unchanged, except
`session/prompt`, whose text is reduced to just the humans' messages ("josh: hello") so the
agent burns no context on Buzz's routing boilerplate.
Upstream (herdr-acp → buzz-acp): every line is forwarded unchanged so buzz-acp keeps its typing
indicator and observer feed; on the side, everything the pane does (humans typing in it, the
agent's text, tool calls) is posted to the channel as the agent via the `buzz` CLI, so the
channel and the pane are one shared session. Env comes from bin/herdr-buzz.

Edit the templates below to change what gets posted. `--tools none` skips tool calls.
"""

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading

# ---- what gets posted (edit freely) ----------------------------------------------------
TOOL_START = "▸ {title}"
TOOL_DONE = "✓ {title}"
TOOL_FAIL = "✗ {title}"
AGENT_TEXT = "{text}"          # every assistant text block, as it appears
PANE_INPUT = "⌨ {text}"        # a human typing directly in the pane
TITLE_MAX = 120

# buzz-acp's prompt, one block per event:  "From: josh (npub…, hex: …)\n…\nContent: <text>\nTags: […]"
EVENT = re.compile(r"^From: (\S+).*?^Content: ?(.*?)\n(?:Tags:|\Z)", re.S | re.M)


def reduce_prompt(blocks: list[str]) -> list[str]:
    """Collapse buzz-acp's prompt blocks (standing context, [Context], events) to 'who: what' lines.
    Prompts with no recognizable event pass through unchanged."""
    events = [e for b in blocks for e in EVENT.findall(b)]
    if not events:
        return blocks
    return ["\n\n".join(f"{who}: {what.strip()}" for who, what in events)]


def render(update: dict, titles: dict, tools: bool = True) -> str | None:
    kind = update.get("sessionUpdate")
    if kind == "agent_message_chunk":
        return AGENT_TEXT.format(text=update["content"].get("text", ""))
    if kind == "user_message_chunk":
        return PANE_INPUT.format(text=update["content"].get("text", ""))
    if not tools:
        return None
    if kind == "tool_call":
        title = (update.get("title") or "tool")[:TITLE_MAX]
        titles[update.get("toolCallId")] = title
        return TOOL_START.format(title=title)
    if kind == "tool_call_update":
        title = titles.get(update.get("toolCallId"), "tool")
        st = update.get("status")
        if st == "completed":
            return TOOL_DONE.format(title=title)
        if st == "failed":
            return TOOL_FAIL.format(title=title)
    return None


# ---- plumbing --------------------------------------------------------------------------
class Poster:
    """Posts to the channel in order, off the pipe threads."""

    def __init__(self, channel: str):
        self.channel, self.q = channel, queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def post(self, text: str) -> None:
        if text.strip():
            self.q.put(text)

    def _run(self) -> None:
        while True:
            text = self.q.get()
            r = subprocess.run(["buzz", "messages", "send", "--channel", self.channel, "--content", "-"],
                               input=text, capture_output=True, text=True)
            if r.returncode:
                print(f"tee: post failed: {r.stderr.strip()[:300]}", file=sys.stderr, flush=True)


def downstream(src, dst, raw: bool) -> None:
    for line in src:
        if not raw:
            try:
                msg = json.loads(line)
                if msg.get("method") == "session/prompt":
                    blocks = msg["params"].get("prompt", [])
                    texts = [b["text"] for b in blocks if b.get("type") == "text"]
                    if len(texts) == len(blocks):
                        msg["params"]["prompt"] = [{"type": "text", "text": t} for t in reduce_prompt(texts)]
                    line = (json.dumps(msg) + "\n").encode()
            except (ValueError, KeyError, TypeError):
                pass
        dst.write(line)
        dst.flush()
    dst.close()


def upstream(src, dst, poster: Poster, tools: bool) -> None:
    titles = {}
    for line in src:
        dst.write(line)
        dst.flush()
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("method") == "session/update":
            out = render(msg["params"]["update"], titles, tools)
            if out:
                poster.post(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--pane", required=True)
    ap.add_argument("--tools", choices=["all", "none"], default="all")
    ap.add_argument("--raw-prompt", action="store_true", help="forward buzz-acp's prompt untouched")
    ap.add_argument("--herdr-acp", default=os.environ.get(
        "HERDR_ACP", os.path.expanduser("~/development/workspace/herdr-acp/.venv/bin/herdr-acp")))
    a = ap.parse_args()
    child = subprocess.Popen([a.herdr_acp, "--pane", a.pane], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    poster = Poster(a.channel)
    t = threading.Thread(target=downstream, args=(sys.stdin.buffer, child.stdin, a.raw_prompt), daemon=True)
    t.start()
    upstream(child.stdout, sys.stdout.buffer, poster, a.tools == "all")
    sys.exit(child.wait())


def _selfcheck() -> None:
    p = ["[Base] You are operating inside the Buzz platform…",
         "[Context]\nScope: channel\nChannel: t (#abc)\nHint: blah\nIMPORTANT: use --reply-to x",
         "[Buzz events — 2 events]\n\n--- Event 1 (all) ---\nEvent ID: e1\nChannel: t\nKind: 9\n"
         "From: josh (npub1x, hex: a0)\nTime: now\nContent: hello\nthere\nTags: [[\"h\",\"abc\"]]\n\n"
         "--- Event 2 (all) ---\nFrom: sam (hex: b1)\nTime: now\nContent: run pwd\nTags: []\n"]
    assert reduce_prompt(p) == ["josh: hello\nthere\n\nsam: run pwd"], repr(reduce_prompt(p))
    assert reduce_prompt(["plain heartbeat"]) == ["plain heartbeat"]
    titles = {}
    assert render({"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "Bash: pwd"}, titles) == "▸ Bash: pwd"
    assert render({"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed"}, titles) == "✓ Bash: pwd"
    assert render({"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "in_progress"}, titles) is None
    assert render({"sessionUpdate": "agent_thought_chunk"}, titles) is None
    assert render({"sessionUpdate": "agent_message_chunk", "content": {"text": "hi"}}, titles) == "hi"
    assert render({"sessionUpdate": "user_message_chunk", "content": {"text": "fix it"}}, titles) == "⌨ fix it"
    assert render({"sessionUpdate": "tool_call", "toolCallId": "t2", "title": "x"}, titles, tools=False) is None
    print("tee ok")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
