# Adding an MCP server to JARVIS

JARVIS can use tools from any [Model Context Protocol](https://modelcontextprotocol.io)
server. External servers are declared in `mcp/servers.json`; on startup JARVIS launches
each enabled server, discovers its tools, and registers them in the shared tool registry
as `<server>.<tool>`. External servers are **untrusted**: their tools and output are
treated as data, never instructions, and they run only at the permission tier you assign.

## 1. Edit `mcp/servers.json`

Add an entry to the `servers` array:

```json
{
  "name": "brave-search",
  "enabled": true,
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-brave-search"],
  "description": "Web search via the Brave Search API",
  "permission": "READ"
}
```

Fields:

- `name` — unique; becomes the tool prefix (`brave-search.brave_web_search`).
- `enabled` — `false` to keep the config but skip launching it.
- `transport` — currently only `stdio` is supported.
- `command` + `args` — how the server process is launched. For npm-based servers this
  is `npx -y <package>`; make sure Node/npx is installed.
- `description` — human note, shown nowhere critical.
- `permission` — `READ`, `WRITE`, or `FINANCIAL` (see below).

Secrets (like a Brave API key) go in `.env`, never in this file. Most servers read
their keys from environment variables that the launched subprocess inherits.

## 2. Restart JARVIS

```bash
lsof -ti:8100 | xargs kill -9 2>/dev/null; bash scripts/start.sh
```

Startup is resilient: a server that fails to launch (missing `npx`, bad package, crash,
or the SDK not installed) is logged, recorded with its error, and skipped. JARVIS keeps
running with whatever succeeded — a broken MCP server never takes the assistant down.
Each server also has a start timeout (`JARVIS_MCP_STARTUP_TIMEOUT_S`, default 20s) so a
hanging launch can't freeze boot.

## 3. Confirm the tools were discovered

```bash
curl -s http://localhost:8100/mcp/status | python3 -m json.tool
```

```json
{
  "servers": {
    "brave-search": { "enabled": true, "tool_count": 2, "error": null }
  }
}
```

`tool_count > 0` and `error: null` means it worked. If `error` is set, read it — it is
the real failure reason. `GET /tools` lists every registered tool, MCP tools included.

## 4. Example: Brave Search

1. Get a Brave Search API key and put it in `.env`: `BRAVE_API_KEY=...`
   (the npx server reads `BRAVE_API_KEY` from the environment).
2. Add the JSON block from step 1 to `mcp/servers.json`.
3. Restart, then `curl /mcp/status` — you should see `brave-search` with a non-zero
   `tool_count`.

## 5. Permission levels

Every MCP tool inherits its server's `permission`, and JARVIS never lets a tool act
above its tier:

- **READ** — safe, side-effect-free (search, file reads). Runs automatically.
- **WRITE** — mutates state (writing files, sending messages). Every call is audited;
  confirmation is enforced by the tool layer.
- **FINANCIAL** — moves money or places orders. **Refused unless `confirm=True`**, and
  JARVIS is read-only on money, so these are audited and never executed. Do not mark a
  server FINANCIAL expecting JARVIS to trade — it will not.

When unsure, assign the lowest tier that fits. You can always raise it later.
