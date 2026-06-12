"""Terminal UI (TUI) control panel for the job-swipe pipeline — runs in the terminal.

    .venv/bin/python -m scripts.tui

Keys: q quit · r refresh · s scrape · m match · u summary · b start bot · x stop bot
Or click the buttons. Live log streams at the bottom; counts + fit% + top matches
update automatically.
"""
from __future__ import annotations

import asyncio
import sys

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label, RichLog, Static,
)

from src import config, store

PY = sys.executable
ROOT = str(config.ROOT)

ACTIONS = {
    "build_profile": ("📄 Profile", "scripts.build_profile", []),
    "scrape": ("🔎 Scrape", "scripts.scrape_jobs", []),
    "match": ("🎯 Match", "scripts.match_jobs", []),
    "summary": ("📊 Summary", "scripts.summary", []),
    "reset": ("🗑 Reset", "scripts.reset_jobs", ["--yes"]),
}

# friendly labels for the raw DB status values
STATUS_LABELS = {
    "pending": "⏳ not swiped",
    "applied": "✅ applied",
    "skipped": "❌ skipped",
    "saved": "🔖 saved",
}

SETTINGS = [
    ("JOB_SOURCES", "Portals (linkedin,indeed,naukri)", "linkedin,indeed,naukri"),
    ("JOB_TITLES", "Job titles (comma-sep)", ""),
    ("JOB_LOCATIONS", "Locations (comma-sep)", ""),
    ("EXPERIENCE_LEVELS", "Experience f_E (1 intern,2 entry,3 assoc,4 mid)", "2,3"),
    ("JOBS_PER_RUN", "Jobs per scrape", "60"),
    ("MIN_MATCH_SCORE", "Min score shown in bot", "50"),
]


class ConfirmScreen(ModalScreen[bool]):
    """Yes/No modal (used for the destructive Reset)."""

    CSS = """
    ConfirmScreen { align: center middle; }
    #box { width: 50; height: auto; border: round $error; padding: 1 2; background: $surface; }
    #box Button { margin: 1 1 0 0; }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Static(id="box"):
            yield Label(self.message)
            with Horizontal():
                yield Button("Yes, delete", id="yes", variant="error")
                yield Button("Cancel", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class SettingsScreen(ModalScreen):
    """Edit search preferences -> saved to .env."""

    CSS = """
    SettingsScreen { align: center middle; }
    #box { width: 80; height: auto; border: round $primary; padding: 1 2; background: $surface; }
    #box Input { margin-bottom: 1; }
    #box Button { margin-top: 1; margin-right: 1; }
    """

    def compose(self) -> ComposeResult:
        with Static(id="box"):
            yield Label("⚙ Search Settings — edit, Save, then Scrape again")
            self.inputs: dict[str, Input] = {}
            for key, label, default in SETTINGS:
                yield Label(label)
                inp = Input(value=config.get(key, default) or "", id=f"in_{key}")
                self.inputs[key] = inp
                yield inp
            with Horizontal():
                yield Button("💾 Save", id="save", variant="success")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            for key, inp in self.inputs.items():
                config.set_env(key, inp.value.strip())
            self.dismiss("saved")
        else:
            self.dismiss(None)


class JobTUI(App):
    CSS = """
    #status { height: 1; padding: 0 1; color: $text-muted; }
    #buttons { height: 3; }
    #buttons Button { margin: 0 1; }
    #top { height: 12; margin: 1 1; }
    #log { height: 1fr; border: round $primary; margin: 0 1 1 1; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("s", "act('scrape')", "Scrape"),
        ("m", "act('match')", "Match"),
        ("u", "act('summary')", "Summary"),
        ("b", "bot_start", "Bot"),
        ("x", "bot_stop", "Stop"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("loading…", id="status")
        with Horizontal(id="buttons"):
            for key, (label, _m, _e) in ACTIONS.items():
                yield Button(label, id=key, variant="error" if key == "reset" else "primary")
            yield Button("▶ Bot", id="bot_start", variant="success")
            yield Button("⏹ Stop", id="bot_stop")
            yield Button("⚙ Settings", id="settings")
        yield DataTable(id="top")
        yield RichLog(id="log", highlight=True, markup=False, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.busy = False
        self.bot_proc: asyncio.subprocess.Process | None = None
        table = self.query_one("#top", DataTable)
        table.add_columns("Score", "Title", "Company", "Swipe")
        self.query_one("#log", RichLog).write("Ready. Pick an action above.")
        self.set_interval(2.0, self.refresh_status)
        self.refresh_status()

    # ---- buttons / actions ----
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid in ACTIONS:
            self.start_action(bid)
        elif bid == "bot_start":
            self.action_bot_start()
        elif bid == "bot_stop":
            self.action_bot_stop()
        elif bid == "settings":
            self.push_screen(SettingsScreen(), self._after_settings)

    def _after_settings(self, result) -> None:
        if result == "saved":
            self.query_one("#log", RichLog).write("⚙ settings saved — Scrape to apply.")

    def action_act(self, key: str) -> None:
        self.start_action(key)

    def start_action(self, key: str) -> None:
        if self.busy:
            self.notify("Busy — wait for the current task.", severity="warning")
            return
        if key == "reset":
            self.push_screen(
                ConfirmScreen("Delete ALL jobs from the database?"),
                lambda ok: self._run(key) if ok else None,
            )
        else:
            self._run(key)

    def _run(self, key: str) -> None:
        _label, module, extra = ACTIONS[key]
        self.busy = True
        self.query_one("#log", RichLog).write(f"\n$ -m {module} {' '.join(extra)}")
        self._stream(module, extra)

    @work(exclusive=False)
    async def _stream(self, module: str, extra: list[str]) -> None:
        log = self.query_one("#log", RichLog)
        proc = await asyncio.create_subprocess_exec(
            PY, "-m", module, *extra, cwd=ROOT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        async for raw in proc.stdout:
            log.write(raw.decode(errors="replace").rstrip())
        await proc.wait()
        log.write(f"--- done (exit {proc.returncode}) ---")
        self.busy = False
        self.refresh_status()

    # ---- bot ----
    def action_bot_start(self) -> None:
        if self.bot_proc and self.bot_proc.returncode is None:
            return
        self._run_bot()

    @work(exclusive=False)
    async def _run_bot(self) -> None:
        log = self.query_one("#log", RichLog)
        self.bot_proc = await asyncio.create_subprocess_exec(
            PY, "-m", "scripts.run_bot", cwd=ROOT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        log.write("▶ bot started")
        async for raw in self.bot_proc.stdout:
            log.write(raw.decode(errors="replace").rstrip())
        log.write("⏹ bot exited")
        self.bot_proc = None

    def action_bot_stop(self) -> None:
        if self.bot_proc and self.bot_proc.returncode is None:
            self.bot_proc.terminate()
            self.query_one("#log", RichLog).write("⏹ stopping bot…")

    # ---- status ----
    def action_refresh(self) -> None:
        self.refresh_status()

    @work(thread=True, exclusive=True, group="refresh")
    def refresh_status(self) -> None:
        try:
            data = {
                "backend": store.backend(),
                "counts": store.counts(),
                "fit": store.fit_pct(),
                "top": store.top_matches(limit=10),
            }
        except Exception as e:  # noqa: BLE001
            data = {"error": str(e)}
        self.call_from_thread(self._apply_status, data)

    def _apply_status(self, data: dict) -> None:
        status = self.query_one("#status", Static)
        if data.get("error"):
            status.update(f"DB error: {data['error'][:80]}")
            return
        counts = "  ".join(f"{STATUS_LABELS.get(k, k)}:{v}"
                           for k, v in sorted(data["counts"].items())) or "no jobs"
        fit = data["fit"]
        bot = "🤖 on" if (self.bot_proc and self.bot_proc.returncode is None) else "bot off"
        fit_txt = (f"🎯 {fit['pct']}% good fit ({fit['good']}/{fit['total']})"
                   if fit["total"] else "no scores yet")
        status.update(f"DB {data['backend']}  ·  {counts}  ·  {fit_txt}  ·  {bot}")

        table = self.query_one("#top", DataTable)
        table.clear()
        for r in data["top"]:
            table.add_row(str(r["match_score"]), (r["title"] or "")[:48],
                          (r["company"] or "")[:24],
                          STATUS_LABELS.get(r["status"], r["status"]))


def main() -> None:
    JobTUI().run()


if __name__ == "__main__":
    main()
