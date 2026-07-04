#!/usr/bin/env python3
"""
run_tests.py
Master test runner for the Triple-Fusion-Engine.

Discovers and runs all pytest tests with configurable options:
  - Selective module execution (--module risk, --module ml, --module all)
  - Verbosity levels (--verbose, --log-level DEBUG)
  - Coverage reporting (--coverage)
  - HTML report generation (--html)
  - Log file output (--log-file)

Usage:
    python run_tests.py                          # Run all tests
    python run_tests.py --module risk            # Risk manager tests only
    python run_tests.py --module ml              # ML module tests
    python run_tests.py --module sentiment       # Sentiment tests
    python run_tests.py --verbose --log-level DEBUG
    python run_tests.py --coverage
    python run_tests.py --html report.html
    pytest tests/test_risk_manager.py -v         # Direct pytest invocation

Author: BullLogic
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

BASE_DIR = Path(__file__).resolve().parent
TESTS_DIR = BASE_DIR / "tests"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# ── Module Mapping ──────────────────────────────────────────────────────────────

MODULE_MAP = {
    "risk":          ["tests/test_risk_manager.py"],
    "smart":         ["tests/test_smart_router.py"],
    "sentiment":     ["tests/test_sentiment.py"],
    "calendar":      ["tests/test_economic_calendar.py"],
    "quality":       ["tests/test_data_quality.py"],
    "data_quality":  ["tests/test_data_quality.py"],
    "gamification":  ["tests/test_gamification.py"],
    "config":        ["tests/test_config.py"],
    "walk_forward":  ["tests/test_walk_forward.py"],
    "ml":            ["tests/test_stacking_ensemble.py", "tests/test_data_pipeline.py"],
    "stacking":      ["tests/test_stacking_ensemble.py"],
    "pipeline":      ["tests/test_data_pipeline.py"],
    "auth":          ["tests/test_auth.py", "tests/test_auth_flows.py"],
    "admin":         ["tests/test_admin.py"],
    "payments":      ["tests/test_payments.py"],
    "alphas":        ["tests/test_alphas.py"],
    "pyth":          ["tests/test_pyth.py"],
    "paper":         ["tests/test_paper_engine.py"],
    "accuracy":      ["tests/test_accuracy.py"],
    "quota":         ["tests/test_quota.py"],
    "theme":         ["tests/test_theme.py"],
    "ethics":        ["tests/test_ethics.py"],
    "all":           [],  # Empty = discover all
}


def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None) -> logging.Logger:
    """Configure logging for the test runner."""
    logger = logging.getLogger("run_tests")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                       datefmt="%H:%M:%S"))
    logger.addHandler(ch)

    # File handler
    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)

    return logger


def build_pytest_args(
    module: str,
    verbose: bool = False,
    log_level: str = "INFO",
    coverage: bool = False,
    html_report: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """Build the pytest command-line arguments list."""
    args = ["-x"]  # Stop on first failure

    # Verbosity
    if verbose:
        args.extend(["-v", "-s"])
    else:
        args.append("-v")

    # Log level
    if log_level.upper() == "DEBUG":
        args.append("--log-cli-level=DEBUG")

    # Test selection
    if module == "all" or not module:
        args.append(str(TESTS_DIR))
    else:
        test_files = MODULE_MAP.get(module, [])
        if not test_files:
            print(f"Unknown module: {module}")
            print(f"Available modules: {', '.join(sorted(MODULE_MAP.keys()))}")
            sys.exit(1)
        for tf in test_files:
            args.append(str(BASE_DIR / tf))

    # Coverage
    if coverage:
        args.extend([
            "--cov=.",
            "--cov-report=term-missing",
            "--cov-report=html:htmlcov",
            "--cov-report=xml:coverage.xml",
        ])

    # HTML report
    if html_report:
        args.extend(["--html", html_report, "--self-contained-html"])

    # Extra args passthrough
    if extra_args:
        args.extend(extra_args)

    return args


def run_tests(
    module: str = "all",
    verbose: bool = False,
    log_level: str = "INFO",
    coverage: bool = False,
    html_report: Optional[str] = None,
    log_file: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
) -> int:
    """Run the test suite and return exit code."""
    log = setup_logging(log_level, log_file)

    start_time = time.time()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log.info("=" * 60)
    log.info("  Triple-Fusion-Engine Test Suite")
    log.info("  Started: %s", timestamp)
    log.info("  Module:  %s", module)
    log.info("=" * 60)

    pytest_args = build_pytest_args(module, verbose, log_level, coverage, html_report, extra_args)
    log.info("pytest %s", " ".join(pytest_args))

    # Run pytest
    result = subprocess.run(
        [sys.executable, "-m", "pytest"] + pytest_args,
        cwd=str(BASE_DIR),
    )

    elapsed = time.time() - start_time
    log.info("=" * 60)
    log.info("  Finished in %.1f seconds", elapsed)
    log.info("  Exit code: %d", result.returncode)
    log.info("=" * 60)

    # Generate summary
    _write_summary(result.returncode, elapsed, module, log_file)

    return result.returncode


def _write_summary(exit_code: int, elapsed: float, module: str, log_file: Optional[str]) -> None:
    """Write a test summary to the logs directory."""
    summary_path = LOGS_DIR / f"test_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    status = "PASSED" if exit_code == 0 else "FAILED"
    with open(summary_path, "w") as f:
        f.write(f"Test Suite Summary\n")
        f.write(f"{'=' * 50}\n")
        f.write(f"Module:     {module}\n")
        f.write(f"Status:     {status}\n")
        f.write(f"Duration:   {elapsed:.1f}s\n")
        f.write(f"Timestamp:  {datetime.now().isoformat()}\n")
        if log_file:
            f.write(f"Log file:   {log_file}\n")
    print(f"\nSummary saved → {summary_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Triple-Fusion-Engine Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--module", default="all", metavar="NAME",
                        help=f"Test module to run. Choices: {', '.join(sorted(MODULE_MAP.keys()))}")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output (-v -s passed to pytest)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Logging level (default: INFO)")
    parser.add_argument("--coverage", action="store_true",
                        help="Generate coverage report (requires pytest-cov)")
    parser.add_argument("--html", metavar="PATH",
                        help="Generate HTML report (requires pytest-html)")
    parser.add_argument("--log-file", metavar="PATH",
                        help="Write runner log to file")
    parser.add_argument("pytest_args", nargs="*", metavar="ARGS",
                        help="Additional arguments passed directly to pytest")

    args = parser.parse_args()

    # Default log file
    log_file = args.log_file
    if not log_file:
        log_file = str(LOGS_DIR / f"test_runner_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

    exit_code = run_tests(
        module=args.module,
        verbose=args.verbose,
        log_level=args.log_level,
        coverage=args.coverage,
        html_report=args.html,
        log_file=log_file,
        extra_args=args.pytest_args,
    )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
