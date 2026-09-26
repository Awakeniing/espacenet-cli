"""Structured CLI errors (fail loudly, agents need unambiguous messages)."""


class CliError(Exception):
    def __init__(self, code, message, action="", exit_code=1):
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.exit_code = exit_code
