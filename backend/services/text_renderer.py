"""Stage 5: Hershey Simplex Roman font system for laser text rendering.

Single-stroke vector font — each glyph is a set of polyline strokes.
The beam traces each stroke once. No filled outlines.
"""
import math
import logging
from typing import List, Tuple, Optional
from models.laser_types import LaserPoint

logger = logging.getLogger(__name__)

# Hershey Simplex Roman font data
# Each char: {"left": int, "right": int, "strokes": [[(x,y),...], ...]}
# Coords roughly -10 to +10 range
# Source: Public domain Hershey font data

HERSHEY_SIMPLEX = {
    32: {"left": -8, "right": 8, "strokes": []},  # space
    33: {"left": -5, "right": 5, "strokes": [  # !
        [(0, -12), (0, -2)],
        [(0, 2), (0, 3)]
    ]},
    34: {"left": -8, "right": 8, "strokes": [  # "
        [(-4, -12), (-4, -6)],
        [(4, -12), (4, -6)]
    ]},
    35: {"left": -10, "right": 10, "strokes": [  # #
        [(-2, -12), (-5, 9)],
        [(3, -12), (0, 9)],
        [(-6, -2), (5, -2)],
        [(-5, 4), (6, 4)]
    ]},
    36: {"left": -10, "right": 10, "strokes": [  # $
        [(-1, -14), (-1, 11)],
        [(2, -14), (2, 11)],
        [(7, -9), (5, -11), (2, -12), (-1, -12), (-4, -11), (-6, -9), (-6, -7), (-5, -5), (-4, -4), (-2, -3), (5, 0), (7, 1), (8, 3), (8, 5), (7, 7), (5, 8), (2, 9), (-1, 9), (-4, 8), (-6, 6)]
    ]},
    37: {"left": -12, "right": 12, "strokes": [  # %
        [(9, -12), (-9, 9)],
        [(-4, -12), (-2, -10), (-2, -8), (-3, -6), (-5, -5), (-7, -5), (-9, -7), (-9, -9), (-8, -11), (-6, -12), (-4, -12), (-2, -11), (1, -10), (4, -10), (7, -11), (9, -12)],
        [(5, 2), (3, 3), (2, 5), (2, 7), (4, 9), (6, 9), (8, 8), (9, 6), (9, 4), (7, 2), (5, 2)]
    ]},
    38: {"left": -13, "right": 13, "strokes": [  # &
        [(10, -4), (10, -3), (9, -1), (8, 0), (4, 2), (1, 3), (-1, 5), (-2, 7), (-2, 9), (-1, 9), (0, 8), (0, 6), (-1, 3), (-3, 0), (-6, -4), (-7, -6), (-7, -9), (-6, -11), (-4, -12), (-2, -11), (-1, -9), (-1, -6), (-2, -2), (-4, 2), (-6, 5), (-7, 7), (-7, 9)],
    ]},
    39: {"left": -4, "right": 4, "strokes": [  # '
        [(0, -10), (-1, -11), (0, -12), (1, -11), (0, -10)]
    ]},
    40: {"left": -7, "right": 7, "strokes": [  # (
        [(4, -16), (2, -14), (0, -11), (-2, -7), (-3, -2), (-3, 2), (-2, 7), (0, 11), (2, 14), (4, 16)]
    ]},
    41: {"left": -7, "right": 7, "strokes": [  # )
        [(-4, -16), (-2, -14), (0, -11), (2, -7), (3, -2), (3, 2), (2, 7), (0, 11), (-2, 14), (-4, 16)]
    ]},
    42: {"left": -8, "right": 8, "strokes": [  # *
        [(0, -6), (0, 6)],
        [(-5, -3), (5, 3)],
        [(5, -3), (-5, 3)]
    ]},
    43: {"left": -13, "right": 13, "strokes": [  # +
        [(0, -9), (0, 9)],
        [(-9, 0), (9, 0)]
    ]},
    44: {"left": -4, "right": 4, "strokes": [  # ,
        [(1, 7), (0, 8), (-1, 7), (0, 6), (1, 7), (1, 9), (0, 11), (-1, 12)]
    ]},
    45: {"left": -13, "right": 13, "strokes": [  # -
        [(-9, 0), (9, 0)]
    ]},
    46: {"left": -4, "right": 4, "strokes": [  # .
        [(0, 6), (-1, 7), (0, 8), (1, 7), (0, 6)]
    ]},
    47: {"left": -11, "right": 11, "strokes": [  # /
        [(9, -16), (-9, 16)]
    ]},
    48: {"left": -10, "right": 10, "strokes": [  # 0
        [(-1, -12), (-4, -11), (-6, -8), (-7, -3), (-7, 0), (-6, 5), (-4, 8), (-1, 9), (1, 9), (4, 8), (6, 5), (7, 0), (7, -3), (6, -8), (4, -11), (1, -12), (-1, -12)]
    ]},
    49: {"left": -10, "right": 10, "strokes": [  # 1
        [(-4, -8), (-2, -9), (1, -12), (1, 9)]
    ]},
    50: {"left": -10, "right": 10, "strokes": [  # 2
        [(-6, -8), (-5, -9), (-3, -11), (-1, -12), (2, -12), (4, -11), (5, -10), (6, -8), (6, -6), (5, -4), (3, -1), (-7, 9), (7, 9)]
    ]},
    51: {"left": -10, "right": 10, "strokes": [  # 3
        [(-5, -12), (6, -12), (0, -4), (3, -4), (5, -3), (6, -2), (7, 1), (7, 3), (6, 6), (4, 8), (1, 9), (-2, 9), (-5, 8), (-6, 7), (-7, 5)]
    ]},
    52: {"left": -10, "right": 10, "strokes": [  # 4
        [(3, -12), (-7, 2), (8, 2)],
        [(3, -12), (3, 9)]
    ]},
    53: {"left": -10, "right": 10, "strokes": [  # 5
        [(5, -12), (-5, -12), (-6, -3), (-5, -4), (-2, -5), (1, -5), (4, -4), (6, -2), (7, 1), (7, 3), (6, 6), (4, 8), (1, 9), (-2, 9), (-5, 8), (-6, 7), (-7, 5)]
    ]},
    54: {"left": -10, "right": 10, "strokes": [  # 6
        [(6, -9), (5, -11), (2, -12), (0, -12), (-3, -11), (-5, -8), (-6, -3), (-6, 2), (-5, 6), (-3, 8), (0, 9), (1, 9), (4, 8), (6, 6), (7, 3), (7, 2), (6, -1), (4, -3), (1, -4), (0, -4), (-3, -3), (-5, -1), (-6, 2)]
    ]},
    55: {"left": -10, "right": 10, "strokes": [  # 7
        [(7, -12), (-3, 9)],
        [(-7, -12), (7, -12)]
    ]},
    56: {"left": -10, "right": 10, "strokes": [  # 8
        [(-1, -12), (-4, -11), (-5, -9), (-5, -7), (-4, -5), (-1, -4), (2, -4), (5, -5), (6, -7), (6, -9), (5, -11), (2, -12), (-1, -12)],
        [(-1, -4), (-5, -2), (-6, 0), (-6, 3), (-5, 6), (-3, 8), (0, 9), (3, 9), (6, 8), (7, 6), (7, 3), (6, 0), (5, -2), (2, -4)]
    ]},
    57: {"left": -10, "right": 10, "strokes": [  # 9
        [(6, -5), (5, -2), (3, 0), (0, 1), (-1, 1), (-4, 0), (-6, -2), (-7, -5), (-7, -6), (-6, -9), (-4, -11), (-1, -12), (0, -12), (3, -11), (5, -9), (6, -5), (6, 0), (5, 5), (3, 8), (0, 9), (-2, 9), (-5, 8), (-6, 6)]
    ]},
    58: {"left": -4, "right": 4, "strokes": [  # :
        [(0, -5), (-1, -4), (0, -3), (1, -4), (0, -5)],
        [(0, 6), (-1, 7), (0, 8), (1, 7), (0, 6)]
    ]},
    59: {"left": -4, "right": 4, "strokes": [  # ;
        [(0, -5), (-1, -4), (0, -3), (1, -4), (0, -5)],
        [(1, 7), (0, 8), (-1, 7), (0, 6), (1, 7), (1, 9), (0, 11), (-1, 12)]
    ]},
    60: {"left": -12, "right": 12, "strokes": [  # <
        [(8, -9), (-8, 0), (8, 9)]
    ]},
    61: {"left": -13, "right": 13, "strokes": [  # =
        [(-9, -3), (9, -3)],
        [(-9, 3), (9, 3)]
    ]},
    62: {"left": -12, "right": 12, "strokes": [  # >
        [(-8, -9), (8, 0), (-8, 9)]
    ]},
    63: {"left": -9, "right": 9, "strokes": [  # ?
        [(-5, -8), (-4, -10), (-3, -11), (-1, -12), (2, -12), (4, -11), (5, -10), (6, -8), (6, -6), (5, -4), (4, -3), (0, -1), (0, 2)],
        [(0, 7), (-1, 8), (0, 9), (1, 8), (0, 7)]
    ]},
    64: {"left": -13, "right": 13, "strokes": [  # @
        [(5, -4), (4, -6), (2, -7), (-1, -7), (-3, -6), (-4, -4), (-4, -1), (-3, 1), (-1, 2), (2, 2), (4, 1), (5, -1)],
        [(5, -7), (5, 2), (6, 4), (8, 5), (10, 4), (11, 2), (11, -2), (10, -6), (8, -9), (5, -11), (2, -12), (-1, -12), (-4, -11), (-6, -9), (-8, -6), (-9, -2), (-9, 2), (-8, 6), (-6, 8), (-4, 9)]
    ]},
    65: {"left": -9, "right": 9, "strokes": [  # A
        [(0, -12), (-8, 9)],
        [(0, -12), (8, 9)],
        [(-5, 2), (5, 2)]
    ]},
    66: {"left": -11, "right": 11, "strokes": [  # B
        [(-7, -12), (-7, 9)],
        [(-7, -12), (2, -12), (5, -11), (6, -10), (7, -8), (7, -6), (6, -4), (5, -3), (2, -2)],
        [(-7, -2), (2, -2), (5, -1), (6, 0), (7, 2), (7, 5), (6, 7), (5, 8), (2, 9), (-7, 9)]
    ]},
    67: {"left": -11, "right": 11, "strokes": [  # C
        [(8, -7), (7, -9), (5, -11), (3, -12), (-1, -12), (-3, -11), (-5, -9), (-6, -7), (-7, -4), (-7, 1), (-6, 4), (-5, 6), (-3, 8), (-1, 9), (3, 9), (5, 8), (7, 6), (8, 4)]
    ]},
    68: {"left": -11, "right": 11, "strokes": [  # D
        [(-7, -12), (-7, 9)],
        [(-7, -12), (0, -12), (3, -11), (5, -9), (6, -7), (7, -4), (7, 1), (6, 4), (5, 6), (3, 8), (0, 9), (-7, 9)]
    ]},
    69: {"left": -10, "right": 10, "strokes": [  # E
        [(-6, -12), (-6, 9)],
        [(-6, -12), (7, -12)],
        [(-6, -2), (2, -2)],
        [(-6, 9), (7, 9)]
    ]},
    70: {"left": -10, "right": 10, "strokes": [  # F
        [(-6, -12), (-6, 9)],
        [(-6, -12), (7, -12)],
        [(-6, -2), (2, -2)]
    ]},
    71: {"left": -11, "right": 11, "strokes": [  # G
        [(8, -7), (7, -9), (5, -11), (3, -12), (-1, -12), (-3, -11), (-5, -9), (-6, -7), (-7, -4), (-7, 1), (-6, 4), (-5, 6), (-3, 8), (-1, 9), (3, 9), (5, 8), (7, 6), (8, 4), (8, -1)],
        [(3, -1), (8, -1)]
    ]},
    72: {"left": -11, "right": 11, "strokes": [  # H
        [(-7, -12), (-7, 9)],
        [(7, -12), (7, 9)],
        [(-7, -2), (7, -2)]
    ]},
    73: {"left": -4, "right": 4, "strokes": [  # I
        [(0, -12), (0, 9)]
    ]},
    74: {"left": -8, "right": 8, "strokes": [  # J
        [(4, -12), (4, 4), (3, 7), (2, 8), (0, 9), (-2, 9), (-4, 8), (-5, 7), (-6, 4), (-6, 2)]
    ]},
    75: {"left": -11, "right": 11, "strokes": [  # K
        [(-7, -12), (-7, 9)],
        [(7, -12), (-7, 2)],
        [(-2, -3), (7, 9)]
    ]},
    76: {"left": -10, "right": 10, "strokes": [  # L
        [(-7, -12), (-7, 9)],
        [(-7, 9), (6, 9)]
    ]},
    77: {"left": -12, "right": 12, "strokes": [  # M
        [(-8, -12), (-8, 9)],
        [(-8, -12), (0, 9)],
        [(8, -12), (0, 9)],
        [(8, -12), (8, 9)]
    ]},
    78: {"left": -11, "right": 11, "strokes": [  # N
        [(-7, -12), (-7, 9)],
        [(-7, -12), (7, 9)],
        [(7, -12), (7, 9)]
    ]},
    79: {"left": -11, "right": 11, "strokes": [  # O
        [(-2, -12), (-4, -11), (-6, -9), (-7, -7), (-8, -3), (-8, 0), (-7, 4), (-6, 6), (-4, 8), (-2, 9), (2, 9), (4, 8), (6, 6), (7, 4), (8, 0), (8, -3), (7, -7), (6, -9), (4, -11), (2, -12), (-2, -12)]
    ]},
    80: {"left": -11, "right": 11, "strokes": [  # P
        [(-7, -12), (-7, 9)],
        [(-7, -12), (2, -12), (5, -11), (6, -10), (7, -8), (7, -5), (6, -3), (5, -2), (2, -1), (-7, -1)]
    ]},
    81: {"left": -11, "right": 11, "strokes": [  # Q
        [(-2, -12), (-4, -11), (-6, -9), (-7, -7), (-8, -3), (-8, 0), (-7, 4), (-6, 6), (-4, 8), (-2, 9), (2, 9), (4, 8), (6, 6), (7, 4), (8, 0), (8, -3), (7, -7), (6, -9), (4, -11), (2, -12), (-2, -12)],
        [(1, 5), (7, 11)]
    ]},
    82: {"left": -11, "right": 11, "strokes": [  # R
        [(-7, -12), (-7, 9)],
        [(-7, -12), (2, -12), (5, -11), (6, -10), (7, -8), (7, -6), (6, -4), (5, -3), (2, -2), (-7, -2)],
        [(0, -2), (7, 9)]
    ]},
    83: {"left": -10, "right": 10, "strokes": [  # S
        [(7, -9), (5, -11), (2, -12), (-1, -12), (-4, -11), (-6, -9), (-6, -7), (-5, -5), (-4, -4), (-2, -3), (3, -1), (5, 0), (6, 1), (7, 3), (7, 6), (6, 8), (3, 9), (0, 9), (-3, 8), (-5, 6)]
    ]},
    84: {"left": -8, "right": 8, "strokes": [  # T
        [(0, -12), (0, 9)],
        [(-7, -12), (7, -12)]
    ]},
    85: {"left": -11, "right": 11, "strokes": [  # U
        [(-7, -12), (-7, 3), (-6, 6), (-4, 8), (-1, 9), (1, 9), (4, 8), (6, 6), (7, 3), (7, -12)]
    ]},
    86: {"left": -9, "right": 9, "strokes": [  # V
        [(-8, -12), (0, 9)],
        [(8, -12), (0, 9)]
    ]},
    87: {"left": -12, "right": 12, "strokes": [  # W
        [(-10, -12), (-5, 9)],
        [(0, -12), (-5, 9)],
        [(0, -12), (5, 9)],
        [(10, -12), (5, 9)]
    ]},
    88: {"left": -10, "right": 10, "strokes": [  # X
        [(-7, -12), (7, 9)],
        [(7, -12), (-7, 9)]
    ]},
    89: {"left": -9, "right": 9, "strokes": [  # Y
        [(-8, -12), (0, -2), (0, 9)],
        [(8, -12), (0, -2)]
    ]},
    90: {"left": -10, "right": 10, "strokes": [  # Z
        [(7, -12), (-7, 9)],
        [(-7, -12), (7, -12)],
        [(-7, 9), (7, 9)]
    ]},
    91: {"left": -7, "right": 7, "strokes": [  # [
        [(-3, -16), (-3, 16)],
        [(-3, -16), (4, -16)],
        [(-3, 16), (4, 16)]
    ]},
    92: {"left": -11, "right": 11, "strokes": [  # backslash
        [(-9, -16), (9, 16)]
    ]},
    93: {"left": -7, "right": 7, "strokes": [  # ]
        [(3, -16), (3, 16)],
        [(-4, -16), (3, -16)],
        [(-4, 16), (3, 16)]
    ]},
    94: {"left": -10, "right": 10, "strokes": [  # ^
        [(0, -12), (-5, -5)],
        [(0, -12), (5, -5)]
    ]},
    95: {"left": -10, "right": 10, "strokes": [  # _
        [(-8, 14), (8, 14)]
    ]},
    96: {"left": -4, "right": 4, "strokes": [  # `
        [(0, -12), (-1, -11), (0, -10), (1, -11), (0, -12)]
    ]},
    97: {"left": -9, "right": 9, "strokes": [  # a
        [(6, -5), (6, 9)],
        [(6, -5), (4, -5), (1, -4), (-1, -2), (-2, 1), (-2, 3), (-1, 6), (1, 8), (4, 9), (6, 9)]
    ]},
    98: {"left": -10, "right": 10, "strokes": [  # b
        [(-7, -12), (-7, 9)],
        [(-7, -5), (-5, -5), (-2, -4), (0, -2), (1, 1), (1, 3), (0, 6), (-2, 8), (-5, 9), (-7, 9)]
    ]},
    99: {"left": -9, "right": 9, "strokes": [  # c
        [(6, -5), (4, -5), (1, -4), (-1, -2), (-2, 1), (-2, 3), (-1, 6), (1, 8), (4, 9), (6, 9)]
    ]},
    100: {"left": -9, "right": 9, "strokes": [  # d
        [(6, -12), (6, 9)],
        [(6, -5), (4, -5), (1, -4), (-1, -2), (-2, 1), (-2, 3), (-1, 6), (1, 8), (4, 9), (6, 9)]
    ]},
    101: {"left": -9, "right": 9, "strokes": [  # e
        [(-2, 1), (6, 1), (6, -1), (5, -3), (4, -4), (2, -5), (-1, -5), (-3, -4), (-4, -3), (-5, -1), (-5, 2), (-4, 5), (-3, 7), (-1, 9), (2, 9), (4, 8), (6, 6)]
    ]},
    102: {"left": -7, "right": 7, "strokes": [  # f
        [(5, -12), (3, -12), (1, -11), (0, -8), (0, 9)],
        [(-3, -5), (5, -5)]
    ]},
    103: {"left": -9, "right": 9, "strokes": [  # g
        [(6, -5), (6, 12), (5, 15), (3, 16), (1, 16), (-1, 15)],
        [(6, -5), (4, -5), (1, -4), (-1, -2), (-2, 1), (-2, 3), (-1, 6), (1, 8), (4, 9), (6, 9)]
    ]},
    104: {"left": -9, "right": 9, "strokes": [  # h
        [(-6, -12), (-6, 9)],
        [(-6, -4), (-3, -5), (0, -5), (3, -4), (4, -2), (4, 9)]
    ]},
    105: {"left": -4, "right": 4, "strokes": [  # i
        [(0, -12), (-1, -11), (0, -10), (1, -11), (0, -12)],
        [(0, -5), (0, 9)]
    ]},
    106: {"left": -5, "right": 5, "strokes": [  # j
        [(1, -12), (0, -11), (1, -10), (2, -11), (1, -12)],
        [(1, -5), (1, 12), (0, 15), (-2, 16)]
    ]},
    107: {"left": -9, "right": 9, "strokes": [  # k
        [(-6, -12), (-6, 9)],
        [(6, -5), (-6, 5)],
        [(-1, 1), (6, 9)]
    ]},
    108: {"left": -4, "right": 4, "strokes": [  # l
        [(0, -12), (0, 9)]
    ]},
    109: {"left": -15, "right": 15, "strokes": [  # m
        [(-11, -5), (-11, 9)],
        [(-11, -4), (-8, -5), (-5, -5), (-3, -4), (-2, -2), (-2, 9)],
        [(-2, -4), (1, -5), (4, -5), (6, -4), (7, -2), (7, 9)]
    ]},
    110: {"left": -9, "right": 9, "strokes": [  # n
        [(-6, -5), (-6, 9)],
        [(-6, -4), (-3, -5), (0, -5), (3, -4), (4, -2), (4, 9)]
    ]},
    111: {"left": -9, "right": 9, "strokes": [  # o
        [(-1, -5), (-3, -4), (-4, -3), (-5, -1), (-5, 2), (-4, 5), (-3, 7), (-1, 8), (1, 8), (3, 7), (4, 5), (5, 2), (5, -1), (4, -3), (3, -4), (1, -5), (-1, -5)]
    ]},
    112: {"left": -10, "right": 10, "strokes": [  # p
        [(-7, -5), (-7, 16)],
        [(-7, -5), (-5, -5), (-2, -4), (0, -2), (1, 1), (1, 3), (0, 6), (-2, 8), (-5, 9), (-7, 9)]
    ]},
    113: {"left": -9, "right": 9, "strokes": [  # q
        [(6, -5), (6, 16)],
        [(6, -5), (4, -5), (1, -4), (-1, -2), (-2, 1), (-2, 3), (-1, 6), (1, 8), (4, 9), (6, 9)]
    ]},
    114: {"left": -7, "right": 7, "strokes": [  # r
        [(-4, -5), (-4, 9)],
        [(-4, -1), (-3, -3), (-1, -5), (1, -5), (4, -4), (5, -3)]
    ]},
    115: {"left": -8, "right": 8, "strokes": [  # s
        [(5, -4), (3, -5), (0, -5), (-2, -4), (-3, -3), (-3, -1), (-2, 0), (2, 2), (4, 3), (5, 5), (5, 7), (4, 8), (1, 9), (-1, 9), (-4, 8)]
    ]},
    116: {"left": -6, "right": 6, "strokes": [  # t
        [(0, -12), (0, 8), (1, 9), (3, 9)],
        [(-3, -5), (5, -5)]
    ]},
    117: {"left": -9, "right": 9, "strokes": [  # u
        [(-6, -5), (-6, 5), (-5, 8), (-2, 9), (0, 9), (3, 8), (6, 5)],
        [(6, -5), (6, 9)]
    ]},
    118: {"left": -8, "right": 8, "strokes": [  # v
        [(-6, -5), (0, 9)],
        [(6, -5), (0, 9)]
    ]},
    119: {"left": -11, "right": 11, "strokes": [  # w
        [(-8, -5), (-4, 9)],
        [(0, -5), (-4, 9)],
        [(0, -5), (4, 9)],
        [(8, -5), (4, 9)]
    ]},
    120: {"left": -8, "right": 8, "strokes": [  # x
        [(-6, -5), (6, 9)],
        [(6, -5), (-6, 9)]
    ]},
    121: {"left": -8, "right": 8, "strokes": [  # y
        [(-6, -5), (0, 9)],
        [(6, -5), (0, 9), (-2, 13), (-4, 15), (-6, 16)]
    ]},
    122: {"left": -8, "right": 8, "strokes": [  # z
        [(6, -5), (-6, 9)],
        [(-6, -5), (6, -5)],
        [(-6, 9), (6, 9)]
    ]},
    123: {"left": -7, "right": 7, "strokes": [  # {
        [(2, -16), (0, -15), (-1, -14), (-2, -12), (-2, -10), (-1, -8), (0, -7), (1, -5), (1, -3), (-1, -1)],
        [(-1, -1), (1, 1), (1, 3), (0, 5), (-1, 6), (-2, 8), (-2, 10), (-1, 12), (0, 13), (2, 14)]
    ]},
    124: {"left": -4, "right": 4, "strokes": [  # |
        [(0, -16), (0, 16)]
    ]},
    125: {"left": -7, "right": 7, "strokes": [  # }
        [(-2, -16), (0, -15), (1, -14), (2, -12), (2, -10), (1, -8), (0, -7), (-1, -5), (-1, -3), (1, -1)],
        [(1, -1), (-1, 1), (-1, 3), (0, 5), (1, 6), (2, 8), (2, 10), (1, 12), (0, 13), (-2, 14)]
    ]},
    126: {"left": -12, "right": 12, "strokes": [  # ~
        [(-9, -1), (-9, -3), (-8, -5), (-6, -6), (-4, -6), (-2, -5), (2, -1), (4, 0), (6, 0), (8, -1), (9, -3)],
    ]},
}


MAX_WIDTH = 52000


def text_to_points(
    text: str,
    center_x: int = 0,
    center_y: int = 0,
    scale: float = 800.0,
    color: Tuple[int, int, int] = (0, 255, 0)
) -> List[LaserPoint]:
    """Convert text to laser points using Hershey Simplex Roman font.
    
    1. Calculate total text width
    2. Auto-scale to fit within ~80% of ILDA range (52000)
    3. Render each character's strokes with blanking and dwell points
    """
    if not text:
        return []
    
    # Calculate total width
    total_width = 0
    for ch in text:
        code = ord(ch)
        glyph = HERSHEY_SIMPLEX.get(code, HERSHEY_SIMPLEX.get(32))  # fallback to space
        total_width += glyph["right"] - glyph["left"]
    
    if total_width <= 0:
        return []
    
    # Auto-scale to fit 80% of coordinate range
    max_text_width = MAX_WIDTH * 0.8
    pixel_width = total_width * scale
    if pixel_width > max_text_width:
        scale = max_text_width / total_width
    
    final_scale = scale
    
    # Start cursor at left edge
    cursor_x = center_x - (total_width * final_scale / 2)
    
    points = []
    r, g, b = color
    
    for ch in text:
        code = ord(ch)
        glyph = HERSHEY_SIMPLEX.get(code, HERSHEY_SIMPLEX.get(32))
        
        char_offset_x = cursor_x - glyph["left"] * final_scale
        
        for stroke in glyph["strokes"]:
            if len(stroke) < 2:
                continue
            
            # Blanking point at stroke start (laser off, move to position)
            sx = int(char_offset_x + stroke[0][0] * final_scale)
            sy = int(center_y - stroke[0][1] * final_scale)  # Y flipped
            sx = max(-32768, min(32767, sx))
            sy = max(-32768, min(32767, sy))
            
            points.append(LaserPoint(x=sx, y=sy, r=0, g=0, b=0, blanked=True))
            
            # 2 dwell points at stroke start
            points.append(LaserPoint(x=sx, y=sy, r=r, g=g, b=b, blanked=False))
            points.append(LaserPoint(x=sx, y=sy, r=r, g=g, b=b, blanked=False))
            
            # Visible points along the stroke
            for px, py in stroke[1:]:
                lx = int(char_offset_x + px * final_scale)
                ly = int(center_y - py * final_scale)
                lx = max(-32768, min(32767, lx))
                ly = max(-32768, min(32767, ly))
                points.append(LaserPoint(x=lx, y=ly, r=r, g=g, b=b, blanked=False))
        
        # Advance cursor
        cursor_x += (glyph["right"] - glyph["left"]) * final_scale
    
    return points


def animated_text_frame(
    text: str,
    progress: float,
    style: str,
    color: Tuple[int, int, int],
    center_x: int = 0,
    center_y: int = 0,
    scale: float = 800.0
) -> List[LaserPoint]:
    """Render text with animation style.
    
    progress: 0.0-1.0 within the lyric line's duration.
    """
    if not text:
        return []
    
    r, g, b = color
    
    if style == "typewriter":
        # Reveal characters left-to-right
        visible_chars = max(1, int(len(text) * progress))
        partial_text = text[:visible_chars]
        return text_to_points(partial_text, center_x, center_y, scale, color)
    
    elif style == "fade":
        # Full text, brightness ramps to 1.0 over first 30%
        brightness = min(1.0, progress / 0.3) if progress < 0.3 else 1.0
        faded_color = (int(r * brightness), int(g * brightness), int(b * brightness))
        return text_to_points(text, center_x, center_y, scale, faded_color)
    
    elif style == "wave":
        # Full text with vertical sine offset per character
        points = []
        total_width = 0
        for ch in text:
            code = ord(ch)
            glyph = HERSHEY_SIMPLEX.get(code, HERSHEY_SIMPLEX.get(32))
            total_width += glyph["right"] - glyph["left"]
        
        if total_width <= 0:
            return []
        
        max_text_width = MAX_WIDTH * 0.8
        pixel_width = total_width * scale
        if pixel_width > max_text_width:
            scale = max_text_width / total_width
        
        cursor_x = center_x - (total_width * scale / 2)
        
        for i, ch in enumerate(text):
            code = ord(ch)
            glyph = HERSHEY_SIMPLEX.get(code, HERSHEY_SIMPLEX.get(32))
            
            # Wave offset
            wave_offset = int(math.sin(i * 0.3 + progress * 2 * math.pi) * 2000)
            char_center_y = center_y + wave_offset
            
            char_offset_x = cursor_x - glyph["left"] * scale
            
            for stroke in glyph["strokes"]:
                if len(stroke) < 2:
                    continue
                sx = int(char_offset_x + stroke[0][0] * scale)
                sy = int(char_center_y - stroke[0][1] * scale)
                sx = max(-32768, min(32767, sx))
                sy = max(-32768, min(32767, sy))
                points.append(LaserPoint(x=sx, y=sy, r=0, g=0, b=0, blanked=True))
                points.append(LaserPoint(x=sx, y=sy, r=r, g=g, b=b, blanked=False))
                points.append(LaserPoint(x=sx, y=sy, r=r, g=g, b=b, blanked=False))
                for px, py in stroke[1:]:
                    lx = int(char_offset_x + px * scale)
                    ly = int(char_center_y - py * scale)
                    lx = max(-32768, min(32767, lx))
                    ly = max(-32768, min(32767, ly))
                    points.append(LaserPoint(x=lx, y=ly, r=r, g=g, b=b, blanked=False))
            
            cursor_x += (glyph["right"] - glyph["left"]) * scale
        
        return points
    
    elif style == "word_highlight":
        # All words rendered. Active word bright, others dim.
        words = text.split()
        if not words:
            return []
        
        active_idx = int(progress * len(words))
        active_idx = min(active_idx, len(words) - 1)
        
        points = []
        # Render each word separately
        total_text = " ".join(words)
        total_width = sum(
            HERSHEY_SIMPLEX.get(ord(c), HERSHEY_SIMPLEX.get(32))["right"] -
            HERSHEY_SIMPLEX.get(ord(c), HERSHEY_SIMPLEX.get(32))["left"]
            for c in total_text
        )
        
        if total_width <= 0:
            return []
        
        max_text_width = MAX_WIDTH * 0.8
        used_scale = scale
        if total_width * used_scale > max_text_width:
            used_scale = max_text_width / total_width
        
        cursor_x = center_x - (total_width * used_scale / 2)
        
        for w_idx, word in enumerate(words):
            is_active = (w_idx == active_idx)
            if is_active:
                w_color = color
            else:
                w_color = (r // 3, g // 3, b // 3)
            
            for ch in word:
                code = ord(ch)
                glyph = HERSHEY_SIMPLEX.get(code, HERSHEY_SIMPLEX.get(32))
                char_offset_x = cursor_x - glyph["left"] * used_scale
                
                for stroke in glyph["strokes"]:
                    if len(stroke) < 2:
                        continue
                    sx = int(char_offset_x + stroke[0][0] * used_scale)
                    sy = int(center_y - stroke[0][1] * used_scale)
                    sx = max(-32768, min(32767, sx))
                    sy = max(-32768, min(32767, sy))
                    points.append(LaserPoint(x=sx, y=sy, r=0, g=0, b=0, blanked=True))
                    points.append(LaserPoint(x=sx, y=sy, r=w_color[0], g=w_color[1], b=w_color[2], blanked=False))
                    points.append(LaserPoint(x=sx, y=sy, r=w_color[0], g=w_color[1], b=w_color[2], blanked=False))
                    for px, py in stroke[1:]:
                        lx = int(char_offset_x + px * used_scale)
                        ly = int(center_y - py * used_scale)
                        lx = max(-32768, min(32767, lx))
                        ly = max(-32768, min(32767, ly))
                        points.append(LaserPoint(x=lx, y=ly, r=w_color[0], g=w_color[1], b=w_color[2], blanked=False))
                
                cursor_x += (glyph["right"] - glyph["left"]) * used_scale
            
            # Add space between words
            if w_idx < len(words) - 1:
                space_glyph = HERSHEY_SIMPLEX[32]
                cursor_x += (space_glyph["right"] - space_glyph["left"]) * used_scale
        
        return points
    
    # Default: just render the text
    return text_to_points(text, center_x, center_y, scale, color)
