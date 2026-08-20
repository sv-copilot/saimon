"""Offline A/B eval harness for saimon.

Pure, offline evaluation tooling: run a committed golden fixture suite and
produce a JSON report, or diff two run reports to detect regressions. Never
touches the network or constructs a live LLM client.
"""
