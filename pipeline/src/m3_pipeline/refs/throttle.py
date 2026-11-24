import time
from collections.abc import Callable


class Throttle:
    def __init__(
        self,
        min_interval_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval_s = min_interval_s
        self.clock = clock
        self.sleep = sleep
        self._last: dict[str, float] = {}

    def wait(self, key: str = "", min_interval_s: float | None = None) -> None:
        interval = self.min_interval_s if min_interval_s is None else min_interval_s
        if key in self._last:
            remaining = self._last[key] + interval - self.clock()
            if remaining > 0:
                self.sleep(remaining)
        self._last[key] = self.clock()

    def pause(self, seconds: float) -> None:
        self.sleep(seconds)
