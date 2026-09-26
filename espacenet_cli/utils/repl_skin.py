"""Minimal REPL skin: banner, colored messages, prompt input.

Deliberately small: the REPL is the human fallback path — agents drive the CLI
through subcommands with --json. Plain ANSI colors, no dependencies of its own;
prompt_toolkit is used only when already installed and a console exists.
"""

import sys

_RESET, _BOLD, _DIM = "\033[0m", "\033[1m", "\033[2m"
_CYAN = "\033[38;5;80m"      # brand
_GREEN = "\033[38;5;78m"
_YELLOW = "\033[38;5;220m"
_RED = "\033[38;5;196m"
_GRAY = "\033[38;5;245m"


class ReplSkin:
    """Same interface the REPL needs: banner / input / messages / help."""

    def __init__(self, name, version=""):
        self.name, self.version = name, version

    # -- frame --------------------------------------------------------------

    def print_banner(self):
        print(f"{_CYAN}{_BOLD}◆ {self.name}{_RESET} {_GRAY}{self.version}{_RESET}")
        print(f"{_GRAY}Espacenet 命令行 · 输入 help 查看命令 · quit 退出{_RESET}")

    def print_goodbye(self):
        print(f"{_GRAY}再见。检索记录保留在 ./espacenet-journal/{_RESET}")

    # -- input ---------------------------------------------------------------

    def create_prompt_session(self):
        try:
            from prompt_toolkit import PromptSession

            return PromptSession()
        except Exception:  # no interactive console / prompt_toolkit unavailable
            return None

    def get_input(self, pt_session, project_name="", modified=False):
        mark = f"{_YELLOW}*{_RESET}" if modified else ""
        text = f"{_CYAN}{_BOLD}{self.name}{_RESET}{mark} {_DIM}[{project_name}]{_RESET} › "
        if pt_session is not None:
            return pt_session.prompt(text)
        return input(text)

    # -- output ---------------------------------------------------------------

    def _say(self, mark, color, msg):
        print(f"{color}{mark}{_RESET} {msg}")

    def success(self, msg):
        self._say("✔", _GREEN, msg)

    def error(self, msg):
        self._say("✗", _RED, msg)

    def warning(self, msg):
        self._say("!", _YELLOW, msg)

    def info(self, msg):
        self._say("·", _GRAY, msg)

    def hint(self, msg):
        self._say("→", _CYAN, msg)

    def status(self, key, value):
        print(f"{_GRAY}{key}{_RESET}: {value}")

    def help(self, commands):
        for line in commands.values():
            print(f"  {line}")
