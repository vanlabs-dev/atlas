"""Trusted pytest entrypoint, mounted outside the read-only candidate checkout.

Run with Python -I: import the trusted pytest distribution before allowing app
imports from /repo. Candidate config, conftest and entrypoint plugins are not
part of this harness. A session-finish receipt defeats stdout-only spoofing and
abrupt exits, NOT hostile Python that tampers with this interpreter or receipt.
Independent review and the operator-only harness gate remain required.
"""
import json
import os
import sys

os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
import pytest  # noqa: E402 -- intentionally before adding candidate import paths


class SessionReceipt:
    def __init__(self):
        self.counts = dict.fromkeys(
            ('passed', 'failed', 'errors', 'skipped', 'deselected', 'xfailed', 'xpassed'), 0)

    def pytest_runtest_logreport(self, report):
        if hasattr(report, 'wasxfail'):
            outcome = 'xfailed' if report.skipped else 'xpassed'
        elif report.failed:
            outcome = 'failed' if report.when == 'call' else 'errors'
        elif report.skipped:
            outcome = 'skipped'
        elif report.when == 'call' and report.passed:
            outcome = 'passed'
        else:
            return
        self.counts[outcome] += 1

    def pytest_collectreport(self, report):
        if report.failed:
            self.counts['errors'] += 1
        elif report.skipped:
            self.counts['skipped'] += 1

    def pytest_deselected(self, items):
        self.counts['deselected'] += len(items)

    def pytest_sessionfinish(self, session, exitstatus):
        # Separate bounded channel: ordinary pytest stdout never supplies counts.
        with open('/trusted/test-receipt.json', 'w', encoding='utf-8') as handle:
            json.dump({'version': 1, 'event': 'sessionfinish', 'exit_code': int(exitstatus),
                       'collected': session.testscollected, 'counts': self.counts}, handle)


def main():
    sys.path[:0] = [os.getcwd(), '/repo']
    return pytest.main([*sys.argv[1:], '-c', '/dev/null', '--noconftest'],
                       plugins=[SessionReceipt()])


if __name__ == '__main__':
    raise SystemExit(main())
