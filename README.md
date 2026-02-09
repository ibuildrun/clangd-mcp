# clangd-mcp

MCP server for C/C++ code analysis using clangd and clang tools. Provides diagnostics, symbol search, include analysis, function listing, and code formatting.

## Features

- **check_file** — run clangd diagnostics on a C/C++ file (errors, warnings)
- **find_symbol** — search for symbol definitions across source files (regex)
- **get_includes** — list and analyze #include directives
- **list_functions** — extract function/method declarations from a file
- **clang_format** — format code using clang-format (dry-run or in-place)

Falls back to compiler syntax checking if clangd is not available.

## Requirements

- Python 3.10+
- Optional: clangd, clang-format, ctags (for full functionality)
- Works with fallback even without clang tools installed

## Installation

```bash
pip install clangd-mcp
```

Or from source:
```bash
git clone https://github.com/ibuildrun/clangd-mcp.git
cd clangd-mcp
pip install -e .
```

## MCP Configuration

Add to your `.kiro/settings/mcp.json`:

```json
{
  "mcpServers": {
    "clangd": {
      "command": "clangd-mcp",
      "disabled": false
    }
  }
}
```

Or with uvx:
```json
{
  "mcpServers": {
    "clangd": {
      "command": "uvx",
      "args": ["clangd-mcp"],
      "disabled": false
    }
  }
}
```

## Usage Examples

```
> check_file "src/game/client/components/menus.cpp" "build"
> find_symbol "RenderBackground" "src"
> get_includes "src/game/client/ui.h"
> list_functions "src/game/client/components/menus.cpp"
> clang_format "src/game/client/ui.cpp" "file" true
```

## License

MIT
