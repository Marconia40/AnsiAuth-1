from dataclasses import dataclass


@dataclass
class RetryDecision:
    should_retry: bool
    classification: str
    reason: str
    max_attempts_override: "int | None" = None
    categoria: "str | None" = None
