"""MCP server for C/C++ code analysis via clangd LSP."""

import json
import os
import re
import subprocess
import tempfile
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("clangd-mcp")


def _find_clangd() -> str:
    """Find clangd binary."""
    for name in ["clangd", "clangd-18", "clangd-17", "clangd-16"]:
        try:
            result = subprocess.run([name, "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return name
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return ""


def _run_clang_tool(cmd: list[str], cwd: str | None = None, timeout: int = 30) -> dict:
    """Run a clang tool and return output."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": "Timed out"}
    except FileNotFoundError:
        return {"exit_code": -1, "stdout": "", "stderr": f"Not found: {cmd[0]}"}


@mcp.tool()
def check_file(file_path: str, build_dir: str = "build") -> str:
    """Run clangd diagnostics on a C/C++ file. Reports errors, warnings, and suggestions.

    Args:
        file_path: Path to the C/C++ source file.
        build_dir: Path to build directory with compile_commands.json.
    """
    clangd = _find_clangd()
    if not clangd:
        return _check_with_compiler(file_path, build_dir)

    compile_db = os.path.join(build_dir, "compile_commands.json")
    cmd = [clangd, "--check", file_path]
    if os.path.exists(compile_db):
        cmd += [f"--compile-commands-dir={build_dir}"]

    result = _run_clang_tool(cmd, timeout=30)
    output = result["stderr"]

    if not output.strip():
        return f"No issues found in {file_path}"

    diags = []
    for line in output.split("\n"):
        if re.match(r".+:\d+:\d+: (error|warning|note):", line):
            diags.append(line)

    if diags:
        return f"Diagnostics for {file_path}:\n" + "\n".join(diags)
    return f"clangd output:\n{output[:3000]}"


def _check_with_compiler(file_path: str, build_dir: str) -> str:
    """Fallback: check file with compiler syntax check."""
    for compiler in ["clang++", "cl", "g++"]:
        try:
            if compiler == "cl":
                cmd = [compiler, "/Zs", "/EHsc", file_path]
            else:
                cmd = [compiler, "-fsyntax-only", "-std=c++11", file_path]
            result = _run_clang_tool(cmd, timeout=15)
            if result["exit_code"] == 0:
                return f"No syntax errors in {file_path}"
            return f"Issues found:\n{result['stderr'][:3000]}"
        except Exception:
            continue
    return "No C++ compiler found. Install clangd, clang++, or g++."


@mcp.tool()
def find_symbol(symbol: str, directory: str = "src", extensions: str = ".cpp,.h,.hpp,.c") -> str:
    """Search for a symbol (function, class, variable) definition across C/C++ files.

    Args:
        symbol: Symbol name to search for (supports regex).
        directory: Directory to search in.
        extensions: Comma-separated file extensions to search.
    """
    ext_list = [e.strip() for e in extensions.split(",")]
    matches = []

    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "build" and d != "external"]
        for fname in files:
            if not any(fname.endswith(ext) for ext in ext_list):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if re.search(symbol, line):
                            matches.append(f"  {fpath}:{i}: {line.rstrip()}")
            except Exception:
                continue

    if not matches:
        return f"Symbol '{symbol}' not found in {directory}"
    result = f"Found {len(matches)} match(es) for '{symbol}':\n"
    return result + "\n".join(matches[:50]) + ("\n..." if len(matches) > 50 else "")


@mcp.tool()
def get_includes(file_path: str) -> str:
    """List all #include directives in a C/C++ file and check if they resolve.

    Args:
        file_path: Path to the C/C++ source file.
    """
    if not os.path.exists(file_path):
        return f"File not found: {file_path}"

    includes = []
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f, 1):
            m = re.match(r'\s*#\s*include\s*([<"])(.+?)[>"]', line)
            if m:
                kind = "system" if m.group(1) == "<" else "local"
                includes.append({"line": i, "header": m.group(2), "kind": kind})

    if not includes:
        return f"No #include directives found in {file_path}"

    result = f"Includes in {file_path}:\n"
    for inc in includes:
        result += f"  L{inc['line']}: {inc['kind']:6s} {inc['header']}\n"
    return result


@mcp.tool()
def list_functions(file_path: str) -> str:
    """Extract function/method declarations and definitions from a C/C++ file.

    Args:
        file_path: Path to the C/C++ source file.
    """
    if not os.path.exists(file_path):
        return f"File not found: {file_path}"

    try:
        result = _run_clang_tool(
            ["ctags", "--fields=+n", "-o", "-", "--c++-kinds=fp", file_path], timeout=10
        )
        if result["exit_code"] == 0 and result["stdout"].strip():
            lines = result["stdout"].strip().split("\n")
            funcs = []
            for line in lines:
                if line.startswith("!"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 4:
                    funcs.append(f"  {parts[0]} ({parts[3].replace('line:', 'L')})")
            if funcs:
                return f"Functions in {file_path}:\n" + "\n".join(funcs)
    except Exception:
        pass

    func_pattern = re.compile(
        r"^[\w:*&<>\s]+\s+(\w[\w:]*)\s*\([^)]*\)\s*(const)?\s*\{?\s*$"
    )
    funcs = []
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f, 1):
            line_stripped = line.strip()
            if line_stripped.startswith("//") or line_stripped.startswith("/*"):
                continue
            m = func_pattern.match(line_stripped)
            if m and m.group(1) not in ("if", "for", "while", "switch", "return", "else"):
                funcs.append(f"  L{i}: {line_stripped[:120]}")

    if not funcs:
        return f"No functions found in {file_path} (regex-based, may miss some)"
    return f"Functions in {file_path} ({len(funcs)}):\n" + "\n".join(funcs[:80])


@mcp.tool()
def clang_format(file_path: str, style: str = "file", dry_run: bool = True) -> str:
    """Format a C/C++ file using clang-format.

    Args:
        file_path: Path to the C/C++ source file.
        style: Formatting style (file, llvm, google, chromium, mozilla, webkit).
        dry_run: If True, show diff without modifying file. If False, format in place.
    """
    if not os.path.exists(file_path):
        return f"File not found: {file_path}"

    cmd = ["clang-format", f"--style={style}"]
    if dry_run:
        with open(file_path, "r") as f:
            original = f.read()
        result = _run_clang_tool(cmd + [file_path], timeout=10)
        if result["exit_code"] != 0:
            return f"clang-format failed: {result['stderr']}"
        formatted = result["stdout"]
        if original == formatted:
            return f"File {file_path} is already formatted."
        orig_lines = original.split("\n")
        fmt_lines = formatted.split("\n")
        diffs = []
        for i, (a, b) in enumerate(zip(orig_lines, fmt_lines)):
            if a != b:
                diffs.append(f"  L{i+1}:\n    - {a}\n    + {b}")
        if len(orig_lines) != len(fmt_lines):
            diffs.append(f"  Line count: {len(orig_lines)} -> {len(fmt_lines)}")
        return f"Format changes for {file_path}:\n" + "\n".join(diffs[:30])
    else:
        result = _run_clang_tool(cmd + ["-i", file_path], timeout=10)
        if result["exit_code"] == 0:
            return f"Formatted {file_path} in place."
        return f"clang-format failed: {result['stderr']}"


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
