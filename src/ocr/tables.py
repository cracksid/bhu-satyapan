"""Find the table cells on a prepared page, before any text is read.

A 7/12 is a stack of ruled tables. Rather than throwing the whole page at
Tesseract and hoping it guesses the layout, we use the printed lines: where
horizontal and vertical rules box in a patch of paper, that patch is a cell.

Reading cell by cell also means every piece of text arrives with a position,
which is what later lets the extractor say "this number is the total area"
instead of "this is a number somewhere on the page".
"""

from dataclasses import dataclass

import cv2
import numpy as np

from .preprocess import PreparedPage


@dataclass
class Cell:
    """One box of the table grid, in pixels."""
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def middle_y(self) -> float:
        return self.y + self.height / 2

    @property
    def middle_x(self) -> float:
        return self.x + self.width / 2

    def overlaps_columns(self, other: "Cell") -> float:
        """How much of the narrower cell's width is shared with the other, 0 to 1."""
        overlap = min(self.right, other.right) - max(self.x, other.x)
        return max(overlap, 0) / max(min(self.width, other.width), 1)


def find_cells(page: PreparedPage, min_width: int = 20,
               min_height: int = 15) -> list:
    """Every rectangle enclosed by the printed rules, top-left first."""
    grid = cv2.bitwise_or(page.horizontal, page.vertical)
    interior = cv2.bitwise_not(grid)        # paper that the lines box in

    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        interior, connectivity=4)

    height, width = page.ink.shape
    page_area = float(height * width)
    cells = []
    for index in range(1, count):           # 0 is the background label
        x, y, w, h, area = stats[index]
        if w < min_width or h < min_height:
            continue
        if w > width * 0.97 or h > height * 0.9:
            continue                        # the margin around everything
        if area > page_area * 0.3:
            continue
        if area / float(w * h) < 0.55:      # not really a rectangle
            continue
        cells.append(Cell(int(x), int(y), int(w), int(h)))

    return sorted(_drop_duplicates(cells), key=lambda cell: (cell.y, cell.x))


def _drop_duplicates(cells: list, overlap: float = 0.9,
                     size_ratio: float = 0.8) -> list:
    """Remove near-identical boxes.

    A rule that is a pixel thick on one side can produce two boxes for the
    same cell, a pixel apart. Two boxes count as the same cell only when they
    also have a similar area, so a small cell genuinely sitting inside a large
    one is never thrown away.
    """
    kept = []
    for cell in sorted(cells, key=lambda c: -(c.width * c.height)):
        area = float(cell.width * cell.height)
        duplicate = False
        for other in kept:
            wide = min(cell.right, other.right) - max(cell.x, other.x)
            tall = min(cell.bottom, other.bottom) - max(cell.y, other.y)
            if wide <= 0 or tall <= 0:
                continue
            other_area = float(other.width * other.height)
            if (wide * tall) / area > overlap and area / other_area > size_ratio:
                duplicate = True
                break
        if not duplicate:
            kept.append(cell)
    return kept


def group_rows(cells: list, tolerance: int = 18) -> list:
    """Group cells into rows by their TOP edge.

    A cell that spans several rows - the area block runs down beside every
    owner row - belongs to the row where it starts. Grouping by vertical
    overlap instead lets that one tall cell swallow every row it crosses,
    which is exactly the bug that merged three owners into one row.

    Row tops inside a table line up to within a pixel or two, and rows are at
    least 40 px apart here, so the tolerance is comfortable either way.
    """
    rows = []
    for cell in sorted(cells, key=lambda c: (c.y, c.x)):
        for row in rows:
            if abs(row[0].y - cell.y) <= tolerance:
                row.append(cell)
                break
        else:
            rows.append([cell])
    for row in rows:
        row.sort(key=lambda c: c.x)
    return rows


def group_tables(rows: list, gap: int = 26) -> list:
    """Split rows into tables wherever there is a clear blank band between them."""
    tables, current = [], []
    previous_bottom = None
    for row in rows:
        top = min(cell.y for cell in row)
        bottom = max(cell.bottom for cell in row)
        if previous_bottom is not None and top - previous_bottom > gap and current:
            tables.append(current)
            current = []
        current.append(row)
        previous_bottom = bottom
    if current:
        tables.append(current)
    return tables


def debug_overlay(page: PreparedPage, cells: list) -> np.ndarray:
    """The page with every detected cell outlined - for checking by eye."""
    canvas = cv2.cvtColor(page.gray, cv2.COLOR_GRAY2BGR)
    for cell in cells:
        cv2.rectangle(canvas, (cell.x, cell.y), (cell.right, cell.bottom),
                      (0, 140, 255), 2)
    return canvas
