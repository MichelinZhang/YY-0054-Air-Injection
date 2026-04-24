from __future__ import annotations

from abc import ABC, abstractmethod


class MotionController(ABC):
    """Reserved motion controller contract for future linear stage support."""

    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def move_to_mm(self, target_mm: float) -> None:
        raise NotImplementedError


class NullMotionController(MotionController):
    """No-op placeholder implementation for V1."""

    def connect(self) -> None:
        return

    def disconnect(self) -> None:
        return

    def move_to_mm(self, target_mm: float) -> None:
        _ = target_mm
        return

