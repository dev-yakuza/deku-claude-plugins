"""M0c: lock.py's signal state machine (Wrapper) with an injected clock and killpg (m0c-plan §15, §16).

The window "the group got a signal after the watcher's handlers but before the child was exec'd"
is a few milliseconds wide and cannot be hit reliably from a process test, so the rule is tested
here on the state machine.
"""

import signal
import unittest

import helpers  # noqa: F401  (import path)
from stdo import lockcli


class Clock(object):
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def wrapper():
    w = lockcli.Wrapper()
    w.clock = Clock()
    w.sent = []
    w._killpg_impl = lambda pgid, sig: w.sent.append(sig)
    w.pgid = 4242
    return w


class WrapperRules(unittest.TestCase):
    def test_got_before_ready_does_not_suppress(self):
        w = wrapper()
        w._on_signal(signal.SIGTERM, None)
        w.watcher_reported(signal.SIGTERM)  # the group got it before the child was exec'd
        w.mark_ready()
        w.clock.t += lockcli.FORWARD_GRACE + 0.01
        w.poll()
        self.assertEqual(w.sent, [signal.SIGTERM])
        w.poll()
        self.assertEqual(w.sent, [signal.SIGTERM])  # once

    def test_got_after_ready_near_the_first_signal_suppresses(self):
        w = wrapper()
        w.mark_ready()
        w._on_signal(signal.SIGTERM, None)
        w.clock.t += 0.1
        w.watcher_reported(signal.SIGTERM)
        w.poll()
        w.clock.t += 1
        w.poll()
        self.assertEqual(w.sent, [])
        self.assertTrue(w.suppressed)

    def test_an_old_got_does_not_suppress_a_later_signal(self):
        w = wrapper()
        w.mark_ready()
        w.watcher_reported(signal.SIGTERM)  # someone signalled the group long before
        w.clock.t += 5
        w._on_signal(signal.SIGTERM, None)
        w.clock.t += lockcli.FORWARD_GRACE + 0.01
        w.poll()
        self.assertEqual(w.sent, [signal.SIGTERM])

    def test_no_forward_before_the_grace(self):
        w = wrapper()
        w.mark_ready()
        w._on_signal(signal.SIGTERM, None)
        w.clock.t += lockcli.FORWARD_GRACE / 2
        w.poll()
        self.assertEqual(w.sent, [])

    def test_duplicate_within_the_window_is_one_and_later_forces(self):
        w = wrapper()
        w.mark_ready()
        w._on_signal(signal.SIGTERM, None)
        w.clock.t += lockcli.DUP_WINDOW - 0.01
        w._on_signal(signal.SIGTERM, None)
        self.assertNotIn(signal.SIGKILL, w.sent)
        w.clock.t += 0.02
        w._on_signal(signal.SIGTERM, None)
        self.assertIn(signal.SIGKILL, w.sent)

    def test_another_kind_forces_at_once(self):
        w = wrapper()
        w._on_signal(signal.SIGTERM, None)
        w._on_signal(signal.SIGINT, None)
        self.assertEqual(w.sent, [signal.SIGKILL])


if __name__ == "__main__":
    unittest.main()
