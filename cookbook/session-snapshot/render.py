#!/usr/bin/env python3
"""Render a snapshot.sh work dir into <stamp>.json and <stamp>.html. Called by snapshot.sh."""
import collections
import datetime
import glob
import json
import os
import re
import shlex
import sys

work, out, stamp, restore_bin = sys.argv[1:5]
home = os.path.expanduser("~")
UUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
SHELLS = {"zsh", "bash", "fish", "sh", "login"}
MAX_TURNS = int(os.environ.get("AGT_SNAP_TURNS", "200"))  # 0 keeps conversation text out of the snapshot
MAX_TEXT = 6000


def tilde(p):
    return "~" + p[len(home):] if p and p.startswith(home) else (p or "")


def prog(argv):
    return os.path.basename(argv[0]).lstrip("-") if argv else ""


def clip(t):
    return t if len(t) <= MAX_TEXT else t[:MAX_TEXT] + f"\n… [{len(t) - MAX_TEXT} more characters]"


def mtime(path):
    return datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")


live = {}
with open(f"{work}/claude.tsv") as f:
    for line in f:
        a, s = line.rstrip("\n").split("\t")
        live[a.upper()] = s.lower()


def blocks(o):
    c = (o.get("message") or {}).get("content")
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return [x for x in c if isinstance(x, dict)] if isinstance(c, list) else []


def text_of(o):
    return "\n".join(b.get("text", "") for b in blocks(o) if b.get("type") == "text").strip()


def transcript(sid):
    m = glob.glob(f"{home}/.claude/projects/*/{sid.lower()}.jsonl") if sid else []
    if not m:
        return None
    info = {"sid": sid.lower(), "path": tilde(m[0]), "size": os.path.getsize(m[0]), "cwd": None, "branch": None,
            "model": None, "version": None, "started": None, "title": None, "prompts": 0, "replies": 0}
    custom, tools, turns = None, collections.Counter(), []
    with open(m[0], errors="replace") as f:
        for line in f:
            if '"type"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            t, ts = o.get("type"), o.get("timestamp")
            if t == "custom-title":
                custom = o.get("customTitle") or custom
            elif t == "ai-title":
                info["title"] = o.get("aiTitle") or info["title"]
            if t not in ("user", "assistant") or o.get("isMeta") or o.get("isSidechain"):
                continue
            info["started"] = info["started"] or ts
            info["cwd"] = info["cwd"] or o.get("cwd")
            info["branch"] = o.get("gitBranch") or info["branch"]
            info["version"] = o.get("version") or info["version"]
            text = text_of(o)
            if t == "assistant":
                info["model"] = (o.get("message") or {}).get("model") or info["model"]
                for b in blocks(o):
                    if b.get("type") == "tool_use":
                        tools[b.get("name") or "?"] += 1
                if text:
                    info["replies"] += 1
                    turns.append({"role": "assistant", "ts": ts, "text": clip(text)})
            elif text and not text.startswith("<"):
                info["prompts"] += 1
                turns.append({"role": "user", "ts": ts, "text": clip(text)})
    info["title"] = custom or info["title"]
    info["modified"] = mtime(m[0])
    info["tools"] = tools.most_common()
    info["omitted"] = max(0, len(turns) - MAX_TURNS)
    info["turns"] = turns[-MAX_TURNS:] if MAX_TURNS > 0 else []
    prompts = [x["text"] for x in turns if x["role"] == "user"]
    info["first"], info["last"] = (prompts[0], prompts[-1]) if prompts and MAX_TURNS > 0 else (None, None)
    return info


def conversation(sess_id, fg):
    """The session's conversation and how it was matched, or (None, None)."""
    found = []
    if live.get(sess_id.upper()):
        found.append((live[sess_id.upper()], "running claude process"))
    if prog(fg) == "claude":
        for i, a in enumerate(fg[:-1]):
            if a in ("-r", "--resume", "--session-id") and UUID.match(fg[i + 1]):
                found.append((fg[i + 1], "claude command line"))
    found.append((sess_id, "transcript named after the agterm session (per-tab wrapper)"))
    for sid, how in found:
        t = transcript(sid)
        if t:
            return t, how
    return None, None


def candidates(cwd, n=5):
    """Recent conversations started in cwd, for a session no conversation could be matched to."""
    d = f"{home}/.claude/projects/{re.sub(r'[^A-Za-z0-9]', '-', cwd)}"
    found = []
    for path in sorted(glob.glob(f"{d}/*.jsonl"), key=os.path.getmtime, reverse=True)[:n]:
        title, custom, first = None, None, None
        with open(path, errors="replace") as f:
            for line in f:
                if not ('"custom-title"' in line or '"ai-title"' in line or (first is None and '"type":"user"' in line)):
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                t = o.get("type")
                if t == "custom-title":
                    custom = o.get("customTitle") or custom
                elif t == "ai-title":
                    title = o.get("aiTitle") or title
                elif t == "user" and not o.get("isMeta"):
                    txt = text_of(o)
                    if txt and not txt.startswith("<"):
                        first = clip(txt[:300]) if MAX_TURNS > 0 else None
        sid = os.path.basename(path)[:-6]
        found.append({"sid": sid, "title": custom or title, "modified": mtime(path), "first": first,
                      "resume": f"cd {shlex.quote(cwd)} && claude --resume {sid}"})
    return found


def restore_line(conv, fg, cwd):
    """What restore.sh types into the new session: the program it ran, else claude --resume, else nothing."""
    p = prog(fg)
    if p and p not in SHELLS and p != "claude":
        return shlex.join([p] + fg[1:])
    if conv:
        line = f"claude --resume {conv['sid']}"
        return line if not conv["cwd"] or conv["cwd"] == cwd else f"cd {shlex.quote(conv['cwd'])} && {line}"
    return None


snap_file = tilde(f"{out}/{stamp}.json")
snap = {"stamp": stamp, "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "file": snap_file,
        "windows": [], "sessions": []}
with open(f"{work}/windows.json") as f:
    windows = json.load(f)["result"]["windows"]
for w in windows:
    path = f"{work}/tree-{w['id']}.json"
    if not os.path.exists(path):
        continue
    with open(path) as f:
        tree = json.load(f)["result"]["tree"]
    win = {"id": w["id"], "name": w.get("name") or "window", "workspaces": []}
    for ws in tree.get("workspaces", []):
        wsn = {"id": ws["id"], "name": ws.get("name", ""), "sessions": [],
               "snippet": f"{tilde(restore_bin)} {snap_file} --workspace {ws['id']}"}
        for s in ws.get("sessions", []):
            fg, cwd = s.get("foreground") or [], s.get("cwd") or home
            conv, matched = conversation(s["id"], fg)
            split = None
            if s.get("hasSplit") or s.get("split"):
                sfg, scwd = s.get("splitForeground") or [], s.get("splitCwd") or cwd
                sline = shlex.join(sfg) if sfg and prog(sfg) not in SHELLS else None
                if scwd != cwd:
                    sline = f"cd {shlex.quote(scwd)}" + (f" && {sline}" if sline else "")
                split = {"cwd": scwd, "foreground": sfg, "restore": sline}
            try:
                with open(f"{work}/screen-{s['id']}.txt", errors="replace") as f:
                    screen = f.read().rstrip()
            except OSError:
                screen = ""
            rec = {"id": s["id"], "name": s.get("name", ""), "title": s.get("title"), "workspace": wsn["name"],
                   "workspaceId": ws["id"], "window": win["name"], "cwd": cwd, "foreground": fg,
                   "flagged": bool(s.get("flagged")), "status": s.get("status"), "claude": conv,
                   "restore": restore_line(conv, fg, cwd), "split": split, "screen": screen, "matched": matched,
                   "resume": conv and f"cd {shlex.quote(conv['cwd'] or cwd)} && claude --resume {conv['sid']}",
                   "candidates": [] if conv else candidates(cwd),
                   "snippet": f"{tilde(restore_bin)} {snap_file} {s['id']}"}
            snap["sessions"].append(rec)
            wsn["sessions"].append(rec["id"])
        win["workspaces"].append(wsn)
    snap["windows"].append(win)

by_conv = collections.defaultdict(list)
for s in snap["sessions"]:
    if s["claude"]:
        by_conv[s["claude"]["sid"]].append(s)
for group in by_conv.values():
    for s in group:
        s["sharedWith"] = [f"{o['workspace']} / {o['name']}" for o in group if o is not s]

with open(f"{out}/{stamp}.json", "w") as f:
    json.dump(snap, f, indent=1, ensure_ascii=False)

# escaped so nothing in a command line or a conversation can close the <script> it is embedded in
data = json.dumps(snap, ensure_ascii=False)
for ch, esc in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), (" ", "\\u2028"), (" ", "\\u2029")):
    data = data.replace(ch, esc)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "page.html")) as f:
    page = f.read()
hpath = f"{out}/{stamp}.html"
with open(hpath, "w") as f:
    f.write(page.replace("/*__SNAPSHOT__*/null", data, 1))
latest = f"{out}/latest.html"
if os.path.lexists(latest):
    os.remove(latest)
os.symlink(os.path.basename(hpath), latest)
print(hpath)
