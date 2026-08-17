"""domain-mcp — the domain plugin server.

Loads registered domain plugins and routes ``domain.*`` tool calls to them.
No domain logic lives here; plugins contribute adapters, content types, and
tools through the contract in ``research_shared.domain_plugin``.
"""
