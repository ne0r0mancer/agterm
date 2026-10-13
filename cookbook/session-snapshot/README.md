# Session snapshot

Close the sessions you are done with for now and bring any of them back later, each with its own Claude Code conversation.

From [discussion #737](https://github.com/umputun/agterm/discussions/737).

## What it does

Workspaces and sessions pile up, most of them Claude Code agents you are finished with for now but may want again. They crowd the sidebar and hold memory, and closing them means losing track of which conversation ran where, especially when several ran in the same directory.

`snapshot.sh` records every open window before you close anything: per session its workspace, name, directory, the command it is running, its Claude conversation and its last 60 screen lines. It writes them to a JSON file and to an HTML page you can browse, search, and click through to see what each session was, including the conversation's title and messages.

Every session and workspace on that page has a **copy** button. It copies one `restore.sh` line, which recreates the session in a workspace of the same name, in its directory, and types into it what brings it back: `claude --resume <conversation-id>` for a Claude session, the program for anything else, nothing for a plain shell. Because a conversation is resumed by id, several sessions that shared a directory each come back to their own.

The snapshot closes nothing. You close the sessions yourself, and that kills what runs in them; *Limits* says what does not come back.

## Requirements

- agterm 0.7.0 or later. `session type --pane`, used to restore a split's right pane, shipped in that release; the rest is older. The split's own directory (`splitCwd`) is read from 0.28.0 on, and earlier versions restore it into the main pane's directory.
- `jq`
- `python3` 3.9 or later, standard library only. The one in macOS's Command Line Tools is enough.
- Claude Code, only for the conversation part. Without it, sessions restore with their directory and command.

## Setup

Copy the whole directory, keeping its layout: `snapshot.sh` finds `render.py` and `assets/page.html` next to itself, and writes the path of `restore.sh` into every snippet.

```sh
mkdir -p ~/.local/share/agterm
cp -R session-snapshot ~/.local/share/agterm/
chmod +x ~/.local/share/agterm/session-snapshot/*.sh
```

Variables, all optional:

- `AGT_SNAP_DIR`: where snapshots go, `~/agterm-snapshots` by default.
- `AGT_SNAP_TURNS`: how many conversation messages each session keeps, 200 by default. `0` leaves conversation text out; titles, ids and counts are still recorded.
- `AGTERMCTL`: the full path of `agtermctl` when it is not on `PATH`.

To take a snapshot from the action palette, add to `~/.config/agterm/keymap.conf`:

```
command "snapshot sessions"  ~/.local/share/agterm/session-snapshot/snapshot.sh --open
```

Run from the palette or a chord, the script gets the app's `PATH` rather than your shell's, which is the launchd default: `/usr/local/bin` and the system directories, without `/opt/homebrew/bin`. `agtermctl` resolves there once **Help ▸ Install Command Line Tool…** has linked it, and `jq` and `python3` resolve there when they are the ones macOS ships. A Homebrew-only `jq` does not, so install the system one or run the snapshot from a shell. Variables exported in your shell profile do not reach a palette run either.

## Usage

```sh
snapshot.sh --open     # snapshot every open window and open the page
```

On the page, click a session to see its details, and press **copy** on a session or a workspace to copy its restore line. Paste the line into any agterm shell:

```sh
~/.local/share/agterm/session-snapshot/restore.sh ~/agterm-snapshots/2026-10-13-120000.json <session-id>
~/.local/share/agterm/session-snapshot/restore.sh ~/agterm-snapshots/2026-10-13-120000.json --workspace <workspace-id>
```

Add `--dry-run` after `restore.sh` to print the commands without running them. A session that is still open is selected rather than created twice. `latest.html` in the snapshot directory always points at the newest page.

The details panel also has **copy id** and **copy resume command** (`cd <dir> && claude --resume <id>`), for resuming a conversation in any terminal.

## How it works

`snapshot.sh` reads `window list` and, for each open window, `tree --window` and `session text --lines 60` per session. `render.py` turns that into the JSON and embeds the JSON in a copy of `assets/page.html`, which builds the page in the browser and loads nothing from the network.

Finding a session's conversation is the part that took the most work. Matching by process name misses too much: an npm install of Claude Code runs as `node`, and an SDK-hosted one runs under its own path. So the snapshot reads Claude Code's own registry instead, `~/.claude/sessions/<pid>.json`, which names the conversation each live Claude process is running. For each live process, `ps eww` reads `AGTERM_SESSION_ID` from its environment, which ties the conversation to its agterm session. For a session where no Claude is running at the moment of the snapshot, two fallbacks follow: a `--resume` or `--session-id` in the session's foreground command, then a transcript file named after the agterm session id, which is what a per-tab wrapper such as the `claude-session-resume` recipe creates. The page says which rule matched. A session with no match lists the five most recent conversations started in its directory, each with its own resume command.

Resuming by id, not by `claude --continue`, is what keeps sessions that shared a directory apart: `--continue` picks that directory's newest conversation for all of them.

`restore.sh` creates the session with `session new --workspace-name --create-workspace --name --cwd` and then types the restore line into its shell with `session type`, rather than passing it as `--command`. Typed into an interactive shell, the line runs with your full `PATH` and aliases. A `--command` value runs under the app's launchd `PATH`, where a Homebrew `claude` is not found.

Everything a snapshot holds can contain secrets, so `snapshot.sh` sets `umask 077` and makes the snapshot directory `0700`. JSON embedded in the page has `<`, `>`, `&` and the two Unicode line separators escaped, so text from a terminal or a conversation cannot break out of the page's script.

## Limits

**This recipe closes nothing, but the workflow it serves does: closing a session after the snapshot kills every process in it.** A build, a dev server, an SSH connection or an agent running there ends.

**A restored session is a fresh shell running the saved line, with no scrollback.** A Claude conversation comes back whole, from its transcript. Any other program is started again from its command line, without its state.

**A snapshot holds full command lines, the last screen lines of every session and up to 200 messages per Claude conversation**, any of which can include a token or a password. Files are created `0600` in a `0700` directory. Do not commit or share a snapshot, and set `AGT_SNAP_TURNS=0` to keep conversation text out.

Only open windows are captured, since `tree` reports open windows only. Scratch terminals and overlays are not captured.

A conversation open in two sessions at once is flagged **shared** on the page. Two Claude processes writing to one conversation interleave its history, so exit one of them.

A split is restored by turning the split on and typing the right pane's command after a one-second wait. On a slow machine the pane may not be ready yet; `restore.sh` then prints the line to run by hand.

A command line is re-quoted from its argv, the way `foreground` reports it. A shell function or alias is not a process and is not captured by name.

Restore always creates the session in the frontmost window, in the workspace with the saved name, creating that workspace if it is missing.
