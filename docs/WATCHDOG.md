# Watchdog

`scripts/watchdog.py` asks every service what it thinks of itself and reports only when the answer
changes.

The failure it exists for: nine containers read `healthy` for twenty hours while five had no
database. Docker watched the process; nothing watched the claim.

```bash
python scripts/watchdog.py --once            # one pass
python scripts/watchdog.py --once --strict   # exit 1 if anything is not ok
```

Installed as a cron entry every five minutes:

```
*/5 * * * * /home/hermes/bin/saimon-watchdog.sh >> /home/hermes/.saimon-watchdog-cron.log 2>&1
```

## What counts as healthy

A service is `ok` when `status` is `ok` and no value in `checks` is failing. It is not required to
have a database: `export` is stateless and `evaluate` reports its model connection. Values that
count as failing: unavailable, error, failed, disconnected, down, unreachable, degraded.

That rule is what catches `status: ok` beside `database: unavailable`, which is the exact shape of
the outage that started this.

## Alerts

State lives in `~/.saimon-watchdog.json`, so a service degraded for a day is announced once.
Recovery is announced too — silence about a fix teaches people to ignore silence.

Delivery needs `TELEGRAM_BOT_TOKEN` and `SAIMON_ALERT_CHAT_ID`; without them the transition is
written to `~/.saimon-watchdog.log` and logged. The wrapper script reads the token from the
director profile's env file and sets the chat id.

## Why it is not a Docker health check

A container's health check answers "is this process serving". It cannot answer "is this process
telling the truth", and the second question is the one that cost twenty hours.
