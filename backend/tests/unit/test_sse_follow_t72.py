"""T7.2: `follow_events` đợi sự kiện mới của lượt đang chạy, không cần DB hay đồng hồ thật."""

from typing import Any

from app.api.sse import TERMINAL_EVENTS, follow_events
from app.domain.chat import EventBatch
from app.domain.enums import AgentRunStatus

RUNNING = AgentRunStatus.running


def event(name: str) -> dict[str, Any]:
    return {"event": name, "data": {}}


class Timeline:
    """Kho sự kiện lớn dần: mỗi lần `read` (hoặc `sleep`) là một "tick" của thời gian giả."""

    def __init__(self, steps: list[tuple[AgentRunStatus, list[dict[str, Any]]]]) -> None:
        self.steps = steps
        self.reads: list[int] = []
        self.sleeps: list[float] = []

    def read(self, after: int) -> EventBatch:
        self.reads.append(after)
        status, events = self.steps[min(len(self.reads) - 1, len(self.steps) - 1)]
        return EventBatch(status=status, events=events[after:])

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


async def collect(timeline: Timeline, after: int = 0) -> list[tuple[int, str]]:
    return [
        (position, record["event"])
        async for position, record in follow_events(
            timeline.read, after, interval=0.5, sleep=timeline.sleep
        )
    ]


async def test_events_that_arrive_while_following_are_delivered_in_order_and_once() -> None:
    plan, start, end, final = event("plan"), event("tool_start"), event("tool_end"), event("final")
    timeline = Timeline(
        [
            (RUNNING, []),
            (RUNNING, [plan]),
            (RUNNING, [plan, start, end]),
            (AgentRunStatus.succeeded, [plan, start, end, final]),
        ]
    )

    seen = await collect(timeline)

    assert seen == [(0, "plan"), (1, "tool_start"), (2, "tool_end"), (3, "final")]
    assert timeline.reads == [0, 0, 1, 3]  # mỗi lần đọc bắt đầu sau sự kiện đã phát
    assert timeline.sleeps == [0.5, 0.5, 0.5]


async def test_following_stops_right_after_a_terminal_event_even_if_the_run_is_still_open() -> None:
    for name in sorted(TERMINAL_EVENTS):
        timeline = Timeline([(RUNNING, [event("plan"), event(name), event("tool_start")])])

        seen = await collect(timeline)

        assert seen == [(0, "plan"), (1, name)]  # không phát gì sau sự kiện cuối
        assert timeline.sleeps == []


async def test_a_run_closed_without_a_terminal_event_ends_the_stream() -> None:
    timeline = Timeline([(RUNNING, [event("plan")]), (AgentRunStatus.failed, [event("plan")])])

    assert await collect(timeline) == [(0, "plan")]
    assert timeline.reads == [0, 1]


async def test_a_closed_run_with_no_events_ends_immediately() -> None:
    timeline = Timeline([(AgentRunStatus.failed, [])])

    assert await collect(timeline) == []
    assert timeline.sleeps == []


async def test_starting_after_a_position_skips_earlier_events() -> None:
    events = [event("plan"), event("tool_start"), event("tool_end"), event("final")]
    timeline = Timeline([(AgentRunStatus.succeeded, events)])

    assert await collect(timeline, after=2) == [(2, "tool_end"), (3, "final")]
    assert await collect(Timeline([(AgentRunStatus.succeeded, events)]), after=4) == []


async def test_a_negative_start_position_means_from_the_beginning() -> None:
    timeline = Timeline([(AgentRunStatus.succeeded, [event("plan"), event("final")])])

    assert await collect(timeline, after=-5) == [(0, "plan"), (1, "final")]


async def test_a_consumer_that_stops_early_does_not_keep_polling() -> None:
    timeline = Timeline([(RUNNING, [event("plan")])] * 50)
    generator = follow_events(timeline.read, 0, interval=0.5, sleep=timeline.sleep)

    first = await anext(generator)
    await generator.aclose()

    assert first[1]["event"] == "plan"
    assert len(timeline.reads) == 1
