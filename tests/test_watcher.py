import threading
import time
import unittest

from sentinel.watcher import Scheduler


class SchedulerTests(unittest.TestCase):
    def test_ticks_immediately_then_on_interval(self):
        ticks = []

        def tick():
            ticks.append(time.monotonic())

        scheduler = Scheduler(0.02, tick)
        thread = threading.Thread(target=scheduler.run)
        thread.start()
        time.sleep(0.07)
        scheduler.stop()
        thread.join(timeout=2)

        self.assertGreaterEqual(len(ticks), 2)  # immediate + at least one interval

    def test_invalid_interval(self):
        with self.assertRaises(ValueError):
            Scheduler(0, lambda: None)


if __name__ == "__main__":
    unittest.main()
