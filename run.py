"""Launcher: `python run.py`, and the container's CMD.

Two things happen here that cannot happen anywhere else. Logging is configured *before* the
first `bot.*` import, so a fatal boot error — a malformed .env value, a backend that is not
answering yet — is formatted and logged instead of vanishing. And SystemExit is reported
rather than swallowed: the interpreter only prints a SystemExit's message when it reaches
the top level uncaught, so catching it and passing (as this file used to) turned three
carefully written diagnostics in bot/main.py into an empty log and an `Exited (0)` in
`docker ps -a` that reads like a clean shutdown.
"""
import datetime as dt
import logging
import os
import signal
import sys
import time

from dotenv import load_dotenv

log = logging.getLogger("tracker-bot")

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
# At INFO these emit one line per outbound API call and one per inbound webhook POST, which
# buries the bot's own events; aiogram's `aiogram.event` already logs one line per update.
_NOISY = ("httpx", "httpcore", "aiohttp.access", "asyncio")


def _setup_logging() -> None:
    # .env is loaded here rather than left to bot.config, because the level has to be known
    # before the first project import. load_dotenv() does not overwrite variables already in
    # the environment, so config.py's own call is a no-op repeat.
    load_dotenv()
    name = (os.environ.get("LOG_LEVEL") or "INFO").strip().upper()
    level = logging.getLevelNamesMapping().get(name)
    logging.basicConfig(level=level or logging.INFO, format=_FORMAT, datefmt=_DATEFMT,
                        stream=sys.stdout)
    if level is None:
        log.warning("LOG_LEVEL=%r is not a level name (DEBUG, INFO, WARNING, ERROR) — using INFO.", name)
    if (level or logging.INFO) > logging.DEBUG:
        for noisy in _NOISY:
            logging.getLogger(noisy).setLevel(logging.WARNING)


def _stamp_logs_in_local_time(tz: dt.tzinfo) -> None:
    """Timestamp every line in the owner's own clock, whatever the container thinks the time is.

    A slim base image may ship no tzdata, in which case glibc quietly ignores TZ and falls
    back to UTC — and an incident timeline read five hours off is worse than no timestamps.
    Deriving the stamp from clock.TZ makes the log agree with the dates the bot writes.
    """
    def converter(secs: float) -> time.struct_time:
        return dt.datetime.fromtimestamp(secs, tz).timetuple()

    # The zone is a fixed offset, so its "+0500" never changes and can be baked into datefmt
    # as a literal; %z would be re-evaluated by time.strftime against the *container's* zone.
    suffix = dt.datetime.now(tz).strftime("%z")
    for handler in logging.getLogger().handlers:
        if handler.formatter is not None:
            handler.formatter.converter = converter
            handler.formatter.datefmt = f"{_DATEFMT}{suffix}"


def _install_early_sigterm_handler() -> None:
    """Make `docker stop` work during boot, before aiohttp installs its own handler.

    PID 1 is exempt from the kernel's default signal actions: a signal with no handler
    installed is discarded, not fatal. aiohttp installs one for SIGTERM in AppRunner.setup()
    — but the bot spends its first seconds ahead of that, fetching the webhook config from
    the backend, and on a restart loop that is exactly where `docker stop` finds it. Without
    this the stop waits out the full grace period and ends in SIGKILL.
    """
    def terminate(signum: int, _frame: object) -> None:
        # Logged, because this is the one exit path with no exception to explain itself.
        log.info("%s received during startup — shutting down.", signal.Signals(signum).name)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)


def _run() -> int:
    """Import and start the bot; return the process exit status."""
    try:
        from bot import clock  # first touch of bot.config — .env is parsed and validated here
        _stamp_logs_in_local_time(clock.TZ)
        # The date is the half of the clock a timestamp does not prove: a container an hour
        # into the Tashkent day is still on yesterday in UTC, and that is the bug this line
        # lets you rule out at a glance.
        log.info("Owner clock: %s — today is %s.", clock.TZ, clock.today_iso())
        from bot.main import main
        main()
    except KeyboardInterrupt:
        log.info("Interrupted — shutting down.")
        return 0
    except SystemExit as exc:
        # Fatal boot errors are raised as SystemExit("a sentence the owner can act on").
        # Log it and keep a non-zero status so `docker ps -a` says Exited (1), not Exited (0).
        code = exc.code
        if isinstance(code, str):
            log.error("%s", code)
            return 1
        return code if isinstance(code, int) else 0
    except Exception:
        log.exception("Fatal error — the bot is stopping.")
        return 1
    return 0


if __name__ == "__main__":
    _setup_logging()
    _install_early_sigterm_handler()
    sys.exit(_run())
