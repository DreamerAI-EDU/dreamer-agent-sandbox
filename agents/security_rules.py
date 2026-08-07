"""
Dreamer AI Phase 3 — Security Rules Engine
AST-based code audit rules. Zero external dependencies.
"""

import ast
import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Finding:
    rule_id: str
    severity: str  # critical, high, medium
    file: str
    line: int
    description: str
    recommendation: str


# ── Rule registry ──────────────────────────────────────

class RuleRegistry:
    """All registered security rules."""

    _rules: List = []

    @classmethod
    def register(cls, rule_func):
        cls._rules.append(rule_func)
        return rule_func

    @classmethod
    def all(cls) -> List:
        return cls._rules


# ── Helpers ────────────────────────────────────────────

def _get_line(code: str, node: ast.AST) -> int:
    return getattr(node, "lineno", 1)


def _is_var(node) -> bool:
    """Check if node is a variable reference (not a literal)."""
    return isinstance(node, ast.Name)


def _find_calls(tree: ast.AST, func_names: List[str]) -> List[ast.Call]:
    """Find all ast.Call nodes matching given function names."""
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            full = f"{ast.unparse(func.value)}.{func.attr}"
            if full in func_names:
                calls.append(node)
        elif isinstance(func, ast.Name) and func.id in func_names:
            calls.append(node)
    return calls


def _has_string_formatting(node: ast.AST, code: str) -> bool:
    """Check if an AST node involves string formatting / concatenation."""
    if isinstance(node, ast.JoinedStr):  # f-string
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):  # %
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "format":
            return True
    # Heuristic: string concatenation with variables
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        source = ast.get_source_segment(code, node)
        if source and '"' in source and ("+" in source):
            return _contains_var_walk(node)
    return False


def _contains_var_walk(node: ast.AST) -> bool:
    """Walk subtree to check if any Name node exists (variable reference)."""
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            return True
    return False


# ── Rule: SEC-001 ──────────────────────────────────────

@RuleRegistry.register
def sec001_sql_injection(code: str, filename: str) -> List[Finding]:
    """Detect SQL queries using string formatting instead of parameterized queries."""
    findings = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return findings

    db_calls = _find_calls(tree, ["cursor.execute", "conn.execute", "db.execute", "self.cursor.execute"])
    for call in db_calls:
        if call.args and _has_string_formatting(call.args[0], code):
            line = _get_line(code, call)
            findings.append(Finding(
                rule_id="SEC-001",
                severity="critical",
                file=filename,
                line=line,
                description="SQL query uses string formatting — may be vulnerable to SQL injection",
                recommendation="Use parameterized query: cursor.execute('SELECT ... WHERE id = ?', (user_id,))",
            ))
    return findings


# ── Rule: SEC-002 ──────────────────────────────────────

HARDCODED_SECRET_NAMES = [
    "API_KEY", "SECRET", "PASSWORD", "TOKEN", "AUTH_TOKEN",
    "ACCESS_KEY", "PRIVATE_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
    "DATABASE_URL", "DB_PASSWORD",
]


@RuleRegistry.register
def sec002_hardcoded_secrets(code: str, filename: str) -> List[Finding]:
    """Detect hardcoded API keys, passwords, and tokens."""
    findings = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return findings

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            name_upper = target.id.upper()
            # Match exact name or partial pattern
            matched = any(
                name_upper == kw.upper() or kw.upper() in name_upper
                for kw in HARDCODED_SECRET_NAMES
            )
            if matched and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                val = node.value.value
                # Skip obvious placeholders
                if val in ("", "your-secret-here", "changeme", "TODO", "xxx"):
                    continue
                findings.append(Finding(
                    rule_id="SEC-002",
                    severity="critical",
                    file=filename,
                    line=_get_line(code, node),
                    description=f"Hardcoded secret detected: {target.id}",
                    recommendation="Load secrets from environment variables or a vault. Use os.environ.get('KEY').",
                ))
    return findings


# ── Helpers: user-input heuristics ─────────────────────

# Variable names that suggest user-controlled input
USER_INPUT_NAMES = {
    "request", "params", "param", "input", "user_input",
    "form", "query", "data", "body", "arg", "args",
    "payload", "raw", "message", "content",
}

# Variable name patterns that suggest constants or config (not user input)
CONSTANT_NAME_PATTERNS = [
    r"^[A-Z_]+$",          # ALL_CAPS
    r".*_(PATH|DIR|HOME|ROOT|BASE)$",
    r"^(path|dir|home|base|root|config)_",
    r"^(DEFAULT|DEFAULT_).*",
]


def _looks_like_user_input(node: ast.AST) -> bool:
    """Heuristic: does the expression contain variables that look like user input?"""
    var_names: set = set()

    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            var_names.add(child.id)

    if not var_names:
        return False  # pure literal

    for name in var_names:
        name_lower = name.lower()
        # If name explicitly matches user input patterns
        if name_lower in USER_INPUT_NAMES:
            return True

        # If name looks like a constant (ALL_CAPS or config prefix), it's not user input
        is_constant = any(re.match(p, name) for p in CONSTANT_NAME_PATTERNS)
        if is_constant:
            continue

        # Anything in between: unknown provenance → flag conservatively
        return True

    # All variables look like constants → not user input
    return False


# ── Rule: SEC-003 ──────────────────────────────────────

@RuleRegistry.register
def sec003_command_injection(code: str, filename: str) -> List[Finding]:
    """Detect command injection via os.system / subprocess with shell=True and variable input."""
    findings = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return findings

    # os.system(), os.popen()
    os_calls = _find_calls(tree, ["os.system", "os.popen"])
    for call in os_calls:
        if call.args and not isinstance(call.args[0], ast.Constant):
            if _looks_like_user_input(call.args[0]):
                findings.append(Finding(
                    rule_id="SEC-003",
                    severity="critical",
                    file=filename,
                    line=_get_line(code, call),
                    description="os.system/os.popen called with non-literal argument — potential command injection",
                    recommendation="Use subprocess.run() with a list of arguments (no shell=True).",
                ))

    # subprocess.*(shell=True)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        subp_funcs = ["subprocess.call", "subprocess.run", "subprocess.Popen", "subprocess.check_output"]
        is_subp = (
            (isinstance(func, ast.Attribute) and ast.unparse(func) in subp_funcs) or
            (isinstance(func, ast.Name) and func.id in ["call", "run", "Popen", "check_output"])
        )
        if is_subp:
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    if node.args and not isinstance(node.args[0], ast.Constant):
                        if _looks_like_user_input(node.args[0]):
                            findings.append(Finding(
                                rule_id="SEC-003",
                                severity="critical",
                                file=filename,
                                line=_get_line(code, node),
                                description="subprocess with shell=True and non-literal input — command injection risk",
                                recommendation="Remove shell=True and pass arguments as a list.",
                            ))
    return findings


# ── Rule: SEC-004 ──────────────────────────────────────

@RuleRegistry.register
def sec004_path_traversal(code: str, filename: str) -> List[Finding]:
    """Detect file operations with unsanitized user input that may allow path traversal."""
    findings = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return findings

    file_funcs = ["open", "os.remove", "os.unlink", "os.rmdir", "shutil.rmtree"]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_file_op = (
            (isinstance(func, ast.Name) and func.id in file_funcs) or
            (isinstance(func, ast.Attribute) and ast.unparse(func) in file_funcs)
        )
        if is_file_op and node.args:
            arg0 = node.args[0]
            # Flag if path involves variables or concatenation without abspath/basename validation
            if (isinstance(arg0, ast.BinOp) and isinstance(arg0.op, ast.Add)) or isinstance(arg0, ast.JoinedStr):
                # Check if os.path.abspath or os.path.basename is used nearby
                source = ast.get_source_segment(code, node)
                if source and "abspath" not in source and "basename" not in source:
                    findings.append(Finding(
                        rule_id="SEC-004",
                        severity="high",
                        file=filename,
                        line=_get_line(code, node),
                        description="File operation with dynamic path and no abspath/basename validation — path traversal risk",
                        recommendation="Validate the path with os.path.abspath() and ensure it stays within expected directory.",
                    ))
    return findings


# ── Rule: SEC-005 ──────────────────────────────────────

@RuleRegistry.register
def sec005_unsafe_deserialization(code: str, filename: str) -> List[Finding]:
    """Detect pickle.loads without a trust boundary."""
    findings = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return findings

    pickle_calls = _find_calls(tree, ["pickle.load", "pickle.loads"])
    for call in pickle_calls:
        if call.args and _contains_var_walk(call.args[0]):
            findings.append(Finding(
                rule_id="SEC-005",
                severity="high",
                file=filename,
                line=_get_line(code, call),
                description="pickle.load/loads called with variable input — unsafe deserialization",
                recommendation="Use json.loads() instead of pickle if possible, or validate input is from a trusted source.",
            ))
    return findings


# ── Rule: SEC-006 ──────────────────────────────────────

@RuleRegistry.register
def sec006_missing_param_query(code: str, filename: str) -> List[Finding]:
    """Detect SQL string construction without parameter placeholders."""
    findings = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return findings

    db_calls = _find_calls(tree, ["cursor.execute", "conn.execute", "db.execute", "self.cursor.execute"])
    for call in db_calls:
        if not call.args:
            continue
        arg0 = call.args[0]
        source = ast.get_source_segment(code, arg0) if hasattr(ast, 'get_source_segment') else ""
        # Check if string uses f-string/format/% but has no '?' or '%s' placeholder
        if _has_string_formatting(arg0, code):
            if source and "?" not in source and "%s" not in source:
                findings.append(Finding(
                    rule_id="SEC-006",
                    severity="high",
                    file=filename,
                    line=_get_line(code, call),
                    description="SQL query string uses formatting but lacks parameterized placeholders",
                    recommendation="Use '?' placeholders with cursor.execute(query, params) for parameterized queries.",
                ))
    return findings


# ── Rule: SEC-007 ──────────────────────────────────────

@RuleRegistry.register
def sec007_dangerous_eval(code: str, filename: str) -> List[Finding]:
    """Detect eval() or exec() with variable input."""
    findings = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return findings

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_eval = isinstance(func, ast.Name) and func.id in ("eval", "exec")
        if is_eval and node.args:
            if not isinstance(node.args[0], ast.Constant):
                findings.append(Finding(
                    rule_id="SEC-007",
                    severity="high",
                    file=filename,
                    line=_get_line(code, node),
                    description=f"{func.id}() called with non-literal argument — arbitrary code execution risk",
                    recommendation="Remove eval/exec entirely if possible, or strictly validate and sandbox input.",
                ))
    return findings


# ── Rule: SEC-008 ──────────────────────────────────────

INSECURE_RANDOM_FUNCTIONS = [
    "random.randint", "random.choice", "random.random",
    "random.randrange", "random.sample",
]


@RuleRegistry.register
def sec008_insecure_random(code: str, filename: str) -> List[Finding]:
    """Detect use of random module for security-sensitive contexts (tokens, passwords, session IDs)."""
    findings = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return findings

    # Only flag if the file imports random and uses it near security-related variable names
    has_random_import = any(
        isinstance(node, ast.Import) and any(alias.name == "random" for alias in node.names)
        for node in ast.walk(tree)
    ) or any(
        isinstance(node, ast.ImportFrom) and node.module == "random"
        for node in ast.walk(tree)
    )

    if not has_random_import:
        return findings

    rand_calls = _find_calls(tree, INSECURE_RANDOM_FUNCTIONS)
    for call in rand_calls:
        # Check surrounding context for security keywords
        source = ast.get_source_segment(code, call) if hasattr(ast, 'get_source_segment') else ""
        if source and any(kw in source.lower() for kw in ("token", "password", "secret", "session", "auth", "nonce", "salt")):
            findings.append(Finding(
                rule_id="SEC-008",
                severity="medium",
                file=filename,
                line=_get_line(code, call),
                description="random module used in security-sensitive context — not cryptographically secure",
                recommendation="Use secrets module (secrets.token_hex, secrets.choice) for tokens/passwords.",
            ))
    return findings
