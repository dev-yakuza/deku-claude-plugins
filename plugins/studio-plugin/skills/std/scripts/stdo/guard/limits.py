"""Bounds and the time budget (m0d1a-plan §8)."""

import time

MAX_INPUT = 1024 * 1024          # characters
MAX_TOKENS = 200000
MAX_DEPTH = 64
MAX_COMMANDS = 2000
MAX_BRACE = 256
MAX_CWDS = 8
MAX_WRAPPERS = 16
MAX_LOCK_DEPTH = 3
MAX_ALIAS_DEPTH = 16
ALT_MAX = 8                      # alternatives at one alias position
ALT_TOTAL = 64                   # alternative parses of one command
MAX_FILE_READ = 256 * 1024
MAX_FILE_READS = 8
MAX_FS_CALLS = 2000
CPU_BUDGET = 1.5                 # seconds of process time
WALL_BUDGET = 8.0                # seconds of wall time (hook timeout is 20 s)
CHECK_EVERY = 256


class LimitExceeded(Exception):
    def __init__(self, kind):
        Exception.__init__(self, kind)
        self.kind = kind


class Budget(object):
    """CPU and wall clocks; check() raises LimitExceeded('budget')."""

    def __init__(self, cpu=None, wall=None, cpu_clock=None, wall_clock=None):
        self.cpu_clock = cpu_clock or time.process_time
        self.wall_clock = wall_clock or time.monotonic
        self.cpu_limit = CPU_BUDGET if cpu is None else cpu
        self.wall_limit = WALL_BUDGET if wall is None else wall
        self.cpu0 = self.cpu_clock()
        self.wall0 = self.wall_clock()
        self.ticks = 0

    def tick(self):
        self.ticks += 1
        if self.ticks % CHECK_EVERY == 0:
            self.check()

    def check(self):
        if self.cpu_clock() - self.cpu0 > self.cpu_limit or self.wall_clock() - self.wall0 > self.wall_limit:
            raise LimitExceeded("budget")

    def elapsed_ms(self):
        return round((self.wall_clock() - self.wall0) * 1000, 2)
