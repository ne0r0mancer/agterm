#!/bin/bash
# Recreate sessions from a snapshot.sh JSON in the frontmost agterm window.
# Usage: restore.sh [--dry-run] SNAPSHOT.json SESSION_ID...
#        restore.sh [--dry-run] SNAPSHOT.json --workspace WORKSPACE_ID
# A session that is still open is selected instead of duplicated.
set -eu
AGTERMCTL=${AGTERMCTL:-agtermctl}
dry=
if [ "${1:-}" = --dry-run ]; then dry=1; shift; fi
snap=${1:?usage: restore.sh [--dry-run] SNAPSHOT.json SESSION_ID... | --workspace WS_ID}
shift
[ -f "$snap" ] || { echo "no such snapshot: $snap" >&2; exit 1; }
if [ "${1:-}" = --workspace ]; then
  ids=$(jq -r --arg w "${2:?workspace id}" '.sessions[] | select(.workspaceId == $w) | .id' "$snap")
else
  ids="$*"
fi
[ -n "$ids" ] || { echo "nothing to restore" >&2; exit 1; }
exec 3>&1  # dry-run lines bypass the /dev/null redirects below
run() { if [ -n "$dry" ]; then echo "  would run: ${*%$'\n'}" >&3; else "$@"; fi; }

open_ids=$("$AGTERMCTL" window list --json | jq -r '.result.windows[] | select(.open) | .id' | while read -r w; do
  "$AGTERMCTL" tree --window "$w" --json | jq -r '.result.tree.workspaces[].sessions[].id'
done)

for id in $ids; do
  s=$(jq -c --arg id "$id" '.sessions[] | select(.id == $id)' "$snap")
  [ -n "$s" ] || { echo "not in snapshot: $id"; continue; }
  ws=$(jq -r .workspace <<< "$s")
  name=$(jq -r .name <<< "$s")
  if grep -qix "$id" <<< "$open_ids"; then
    run "$AGTERMCTL" session select --target "$id" > /dev/null 2>&1 || true
    echo "${dry:+[dry-run] }still open, selected: $ws / $name"
    continue
  fi
  cwd=$(jq -r .cwd <<< "$s")
  line=$(jq -r '.restore // empty' <<< "$s")
  if [ -n "$dry" ]; then
    new=NEW_SESSION
    echo "  would run: $AGTERMCTL session new --workspace-name '$ws' --create-workspace --name '$name' --cwd '$cwd'"
  else
    new=$("$AGTERMCTL" session new --workspace-name "$ws" --create-workspace --name "$name" --cwd "$cwd" --json |
          jq -r .result.id)
  fi
  [ -z "$line" ] || run "$AGTERMCTL" session type --target "$new" "$line"$'\n' > /dev/null
  if [ "$(jq -r '.split != null' <<< "$s")" = true ]; then
    run "$AGTERMCTL" session split on --target "$new" > /dev/null
    sline=$(jq -r '.split.restore // empty' <<< "$s")
    if [ -n "$sline" ]; then
      # the new pane's shell needs a moment before it takes input
      [ -n "$dry" ] || sleep 1
      run "$AGTERMCTL" session type --target "$new" --pane right "$sline"$'\n' > /dev/null ||
        echo "  split pane not ready, run by hand: $sline"
    fi
  fi
  echo "${dry:+[dry-run] }restored: $ws / $name${line:+  ($line)}"
done
