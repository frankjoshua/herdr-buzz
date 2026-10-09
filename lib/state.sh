# Sourced by bin/*: sets $state, this herdr session's state dir. Herdr hands every session the same
# HERDR_PLUGIN_STATE_DIR and pane ids repeat across sessions, so a named session keeps its records in
# sessions/<name>/ below it. The default session (no HERDR_SESSION) stays at the top.
state=${HERDR_PLUGIN_STATE_DIR:-$HOME/.local/state/herdr/plugins/herdr-buzz}
[ "${HERDR_SESSION:-default}" = default ] || state="$state/sessions/$HERDR_SESSION"
mkdir -p "$state"
