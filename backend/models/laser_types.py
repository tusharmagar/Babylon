"""Data classes for the laser show pipeline."""
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional


@dataclass
class LaserPoint:
    x: int = 0        # -32768 to 32767
    y: int = 0        # -32768 to 32767
    r: int = 0        # 0-255
    g: int = 0        # 0-255
    b: int = 0        # 0-255
    blanked: bool = False  # True = laser off


@dataclass
class LaserFrame:
    points: List[LaserPoint] = field(default_factory=list)
    timestamp_ms: float = 0.0


@dataclass
class SyncedWord:
    word: str = ""
    start_ms: float = 0.0
    end_ms: float = 0.0


@dataclass
class SyncedLine:
    text: str = ""
    start_ms: float = 0.0
    end_ms: float = 0.0
    words: List[SyncedWord] = field(default_factory=list)


@dataclass
class SongSection:
    label: str = ""
    start_ms: float = 0.0
    end_ms: float = 0.0
    energy: float = 0.0


@dataclass
class ShowDesign:
    color_palette: List[Tuple[int, int, int]] = field(default_factory=list)
    section_effects: Dict[str, str] = field(default_factory=dict)
    text_style: str = "typewriter"
    intensity_curve: str = "dynamic"
    bpm: float = 120.0
    sections: List[SongSection] = field(default_factory=list)
