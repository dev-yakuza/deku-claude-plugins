"""guildcore.adapters.clock — `capture_signal.py --now` format (`YYYY-MM-DDTHH:MM:SSZ`, UTC,
whole seconds) so engine timestamps compare with loop-back `at:` and audit `invocation:` lines."""

import time


def iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(epoch)))


class Clock(object):
    def now(self):
        return iso(time.time())


class FixedClock(object):
    def __init__(self, ts):
        self.ts = ts

    def now(self):
        return self.ts
