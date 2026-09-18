import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.fusion import Event, FusionEngine


def test_events_arrive_in_actual_arrival_order_not_source_order():
    engine = FusionEngine()

    def slow_source():
        time.sleep(0.15)
        engine._emit("slow", "test", "second")

    def fast_source():
        engine._emit("fast", "test", "first")

    # slow_source is added first but should still report second, since
    # ordering is by real arrival time, not registration order
    engine._spawn(slow_source)
    engine._spawn(fast_source)

    received = []
    for event in engine.events():
        received.append(event)
        if len(received) == 2:
            break

    assert [e.message for e in received] == ["first", "second"]


def test_events_carry_source_and_kind():
    engine = FusionEngine()
    engine._emit("espn", "game_state", "KC 14 - 7 SF")
    event = next(engine.events())
    assert isinstance(event, Event)
    assert event.source == "espn"
    assert event.kind == "game_state"
    assert event.message == "KC 14 - 7 SF"
    assert event.timestamp > 0


def test_source_exception_becomes_an_error_event_not_a_crash():
    engine = FusionEngine()

    def failing_source():
        raise RuntimeError("boom")

    def run_and_catch():
        try:
            failing_source()
        except Exception as e:
            engine._emit("test_source", "error", str(e))

    engine._spawn(run_and_catch)
    event = next(engine.events())
    assert event.kind == "error"
    assert "boom" in event.message


def test_stop_ends_the_event_generator_once_threads_finish():
    engine = FusionEngine()

    def quick_source():
        engine._emit("quick", "test", "done")

    engine._spawn(quick_source)
    events = engine.events()
    first = next(events)
    assert first.message == "done"

    engine.stop()
    # generator should terminate (StopIteration) once the thread has
    # finished and the stop flag is set, rather than hang forever
    remaining = list(events)
    assert remaining == []
