"""Runs however many of the available signal sources are configured - ESPN
score/state, live radio transcription, CV catch-prediction, and X injury
news - concurrently, each in its own thread, and merges them into one
timestamped event stream ordered by actual arrival.

That ordering is the entire point of combining sources at all: whichever
source reports something first is what you see first. A touchdown might hit
radio commentary half a second before the ESPN feed posts the updated
score, or CV might flag a contested catch before either does. No single
source here is authoritative or complete on its own - this is what makes
combining them worth doing over picking just one.

Every `add_*` method is independent and optional - build up to "all four"
one source at a time, and a FusionEngine with nothing added simply produces
no events rather than erroring.
"""

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class Event:
    source: str    # "espn" | "radio" | "cv" | "news"
    kind: str       # e.g. "game_state", "play_event", "catch_prediction", "injury_news", "error"
    message: str
    timestamp: float
    data: Any = None


class FusionEngine:
    def __init__(self):
        self._queue = queue.Queue()
        self._threads = []
        self._stop = threading.Event()

    def add_espn(self, home_abbr, away_abbr, poll_interval_sec=3.0, event_id=None):
        from src import espn_feed

        def run():
            eid = event_id or espn_feed.find_event_id(home_abbr, away_abbr)
            if not eid:
                self._emit("espn", "error", f"No ESPN event found for {away_abbr} @ {home_abbr}")
                return
            try:
                for state in espn_feed.watch(eid, home_abbr, away_abbr, poll_interval_sec=poll_interval_sec):
                    if self._stop.is_set():
                        return
                    msg = (f"{away_abbr} {state.away_score} - {state.home_score} {home_abbr}  "
                           f"Q{state.quarter} {state.clock_seconds // 60}:{state.clock_seconds % 60:02d}")
                    self._emit("espn", "game_state", msg, data=state)
            except Exception as e:  # noqa: BLE001 - surface any source failure as an event, don't crash the fusion
                self._emit("espn", "error", str(e))

        self._spawn(run)
        return self

    def add_radio(self, stream_url, model_size="base", chunk_seconds=5.0):
        from src import radio_feed

        def run():
            try:
                transcriber = radio_feed.RadioTranscriber(model_size=model_size, chunk_seconds=chunk_seconds)
                for text, events, ts in transcriber.transcribe_stream(stream_url):
                    if self._stop.is_set():
                        return
                    if events:
                        self._emit("radio", "play_event", f"[radio] {', '.join(events)}: \"{text}\"",
                                    timestamp=ts, data={"text": text, "events": events})
            except Exception as e:
                self._emit("radio", "error", str(e))

        self._spawn(run)
        return self

    def add_cv(self, source, detector, tracker, is_browser=False, sample_every_n_frames=1):
        from src.cv import play_watcher

        def run():
            try:
                watch_fn = play_watcher.watch_browser if is_browser else play_watcher.watch_video
                for prediction in watch_fn(source, detector, tracker, sample_every_n_frames=sample_every_n_frames):
                    if self._stop.is_set():
                        return
                    self._emit("cv", "catch_prediction", prediction.message, data=prediction)
            except Exception as e:
                self._emit("cv", "error", str(e))

        self._spawn(run)
        return self

    def add_news(self, team_or_player, poll_interval_sec=60.0):
        from src import news_signal

        def run():
            seen_ids = set()
            while not self._stop.is_set():
                try:
                    for t in news_signal.search_injury_news(team_or_player):
                        tid = t.get("id")
                        if tid in seen_ids:
                            continue
                        seen_ids.add(tid)
                        self._emit("news", "injury_news", t.get("text", ""), data=t)
                except Exception as e:
                    self._emit("news", "error", str(e))
                self._stop.wait(poll_interval_sec)

        self._spawn(run)
        return self

    def events(self):
        """Generator yielding Events in the order they actually arrive across
        all active sources - the merged, low-latency stream."""
        while True:
            try:
                yield self._queue.get(timeout=1.0)
            except queue.Empty:
                if self._stop.is_set() and not any(t.is_alive() for t in self._threads):
                    return
                continue

    def stop(self):
        self._stop.set()

    def _spawn(self, target):
        t = threading.Thread(target=target, daemon=True)
        t.start()
        self._threads.append(t)

    def _emit(self, source, kind, message, timestamp=None, data=None):
        self._queue.put(Event(source, kind, message, timestamp or time.time(), data))
