"""Usage stats + habit analytics. Everything stays on this machine.

Two layers:
  - STATS_FILE (stats.json): small daily aggregates driving the menu display
    (takes, chars, per-app, per-hour, zh/en balance)
  - TAKES_FILE (takes.jsonl): one line per take, transcript text included —
    the corpus behind "Generate AI usage report". Set STATS_LOG_TEXT = False
    to stop collecting text; delete the file to forget everything.
"""

import json
import re
import subprocess
from datetime import date, datetime
from pathlib import Path

import config

# vs hand-typing mixed zh/en at roughly this many chars per minute
_TYPING_CPM = 80


def _path():
    return Path(config.STATS_FILE).expanduser()


def _takes_path():
    return Path(config.TAKES_FILE).expanduser()


def _load():
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _cjk_latin(text):
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    latin = len(re.findall(r"[A-Za-z]+", text))
    return cjk, latin


def record(text, mode=None, app=""):
    if not config.STATS_ENABLED:
        return
    try:
        data = _load()
        day = data.setdefault(date.today().isoformat(), {"takes": 0, "chars": 0})
        day["takes"] += 1
        day["chars"] += len(text)
        cjk, latin = _cjk_latin(text)
        day["cjk"] = day.get("cjk", 0) + cjk
        day["latin"] = day.get("latin", 0) + latin
        app_short = app.rsplit(".", 1)[-1] if app else "unknown"
        for key, val in (("modes", mode or "dictate"), ("apps", app_short),
                         ("hours", f"{datetime.now().hour:02d}")):
            bucket = day.setdefault(key, {})
            bucket[val] = bucket.get(val, 0) + 1
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

        if config.STATS_LOG_TEXT:
            entry = {"ts": datetime.now().isoformat(timespec="seconds"),
                     "text": text, "mode": mode or "dictate", "app": app_short}
            takes = _takes_path()
            with open(takes, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            # Rotate: the corpus is append-only; cap it so years of use don't
            # accumulate an ever-growing file (analysis only reads the tail).
            if takes.stat().st_size > 8_000_000:
                lines = takes.read_text(encoding="utf-8").splitlines()[-5000:]
                takes.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass  # stats are never worth breaking a dictation over


def summary():
    """Aggregates for the menu display."""
    data = _load()
    today = data.get(date.today().isoformat(), {})
    total_takes = sum(d.get("takes", 0) for d in data.values())
    total_chars = sum(d.get("chars", 0) for d in data.values())
    cjk = sum(d.get("cjk", 0) for d in data.values())
    latin = sum(d.get("latin", 0) for d in data.values())
    apps = today.get("apps", {})
    return {
        "today_takes": today.get("takes", 0),
        "today_chars": today.get("chars", 0),
        "takes": total_takes,
        "chars": total_chars,
        "saved_min": total_chars / _TYPING_CPM,
        "cjk_pct": 100 * cjk / (cjk + latin) if cjk + latin else 0,
        "top_app": max(apps, key=apps.get) if apps else None,
    }


def _recent_takes(limit=150, max_chars=6000):
    """Newest takes from the corpus, oldest-first, budgeted for the LLM."""
    try:
        lines = _takes_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    takes = []
    for line in reversed(lines[-limit:]):
        try:
            takes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if sum(len(t.get("text", "")) for t in takes) > max_chars:
            break
    return list(reversed(takes))


def generate_report(cleaner):
    """Build a markdown usage report (deterministic stats + LLM analysis of
    the transcript corpus) and return its path. Blocking — run off-thread."""
    data = _load()
    s = summary()
    lines = [
        "# Whisperflow 使用报告",
        f"*生成于 {datetime.now():%Y-%m-%d %H:%M} · 全部分析在本机完成*",
        "",
        "## 总览",
        f"- 累计 **{s['takes']}** 条 · **{s['chars']:,}** 字 · "
        f"约省 **{s['saved_min']:.0f}** 分钟打字",
        f"- 今天 {s['today_takes']} 条 · {s['today_chars']:,} 字",
        f"- 语言构成:{s['cjk_pct']:.0f}% 中文字符 / {100 - s['cjk_pct']:.0f}% 英文词",
        "",
        "## 常用应用",
    ]
    app_totals, hour_totals, mode_totals = {}, {}, {}
    for day in data.values():
        for k, v in day.get("apps", {}).items():
            app_totals[k] = app_totals.get(k, 0) + v
        for k, v in day.get("hours", {}).items():
            hour_totals[k] = hour_totals.get(k, 0) + v
        for k, v in day.get("modes", {}).items():
            mode_totals[k] = mode_totals.get(k, 0) + v
    for app, n in sorted(app_totals.items(), key=lambda kv: -kv[1])[:8]:
        lines.append(f"- {app}: {n} 条")
    if mode_totals:
        lines += ["", "## 模式使用"]
        for m, n in sorted(mode_totals.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {m}: {n} 条")
    if hour_totals:
        blocks = " ▁▂▃▄▅▆▇█"
        peak = max(hour_totals.values())
        bar = "".join(
            blocks[min(8, round(8 * hour_totals.get(f"{h:02d}", 0) / peak))]
            for h in range(24)
        )
        lines += ["", "## 时段分布(0-23 点)", f"`{bar}`"]

    takes = _recent_takes()
    lines += ["", "## AI 分析"]
    if len(takes) < 10:
        lines.append(f"(样本还太少 — 目前 {len(takes)} 条,多用几天再来生成)")
    elif cleaner is None:
        lines.append("(Ollama 不可用)")
    else:
        corpus = "\n".join(
            f"[{t['app']}/{t['mode']}] {t['text']}" for t in takes
        )
        lines.append(cleaner.analyze(corpus))

    path = Path(config.REPORT_FILE).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def open_report(path):
    subprocess.Popen(["open", str(path)])


# ── Adaptive style profile ─────────────────────────────────────────────────────

def build_style_profile(cleaner):
    """Distill the corpus into a style profile file; returns the bullets
    ('' if not enough data). Blocking (LLM call) — run off-thread."""
    takes = _recent_takes(limit=200, max_chars=6000)
    if cleaner is None or len(takes) < 30:
        return ""
    corpus = "\n".join(f"[{t['app']}/{t['mode']}] {t['text']}" for t in takes)
    bullets = cleaner.style_profile(corpus)
    if not bullets:
        return ""
    path = Path(config.STYLE_FILE).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    total = summary()["takes"]
    path.write_text(
        f"<!-- takes:{total} generated:{datetime.now():%Y-%m-%d %H:%M} -->\n"
        f"{bullets}\n",
        encoding="utf-8",
    )
    return bullets


def _profile_take_count():
    """Take count recorded when the profile was last generated (-1 if none)."""
    try:
        first = Path(config.STYLE_FILE).expanduser().read_text(
            encoding="utf-8"
        ).splitlines()[0]
        return int(re.search(r"takes:(\d+)", first).group(1))
    except Exception:
        return -1


def maybe_refresh_profile(cleaner, spawn):
    """Regenerate the style profile in the background when it's stale
    (never built, or STYLE_REFRESH_EVERY takes have passed). `spawn` is a
    callable that runs a thunk off-thread."""
    if not (config.STYLE_ADAPT and config.STATS_LOG_TEXT) or cleaner is None:
        return
    total = summary()["takes"]
    if total < 30:
        return
    last = _profile_take_count()
    if last < 0 or total - last >= config.STYLE_REFRESH_EVERY:
        spawn(lambda: build_style_profile(cleaner))
