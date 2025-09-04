import calendar
from datetime import datetime
from collections import defaultdict

from reportlab.lib.pagesizes import letter

import ephemeris.settings as settings
from ephemeris.logger import logger

def get_layout_config(width, height, start_hour=6, end_hour=17):
    # Raw page margins from environment
    page_left   = settings.PDF_MARGIN_LEFT
    page_right  = width - settings.PDF_MARGIN_RIGHT
    page_top    = height - settings.PDF_MARGIN_TOP
    page_bottom = settings.PDF_MARGIN_BOTTOM

    # Fixed dimensions
    time_label_width = 26  # width reserved for the HH:MM column
    heading_size   = 12
    heading_ascent = heading_size * 0.75
    element_pad      = 8
    text_padding     = 5

    # Mini-calendar block dimensions
    mini_block_h   = settings.MINICAL_HEIGHT
    mini_block_gap = settings.MINICAL_GAP
    mini_text_pad = settings.MINICAL_TEXT_PADDING

    # Buffer below time grid
    bottom_buffer = settings.PDF_GRID_BOTTOM_BUFFER

    # Feature Flags Affecting Grid
    minical_mode = settings.minical_mode
    DRAW_MINICALS = settings.DRAW_MINICALS

    # Compute vertical extents for the grid
    grid_top    = page_top - heading_ascent - (4 * element_pad)

    grid_bottom = page_bottom + bottom_buffer

    # Compute horizontal extents for the grid
    grid_left  = page_left + time_label_width
    grid_right = page_right

    # Recompute grid_top so it floats up when we skip the minis or all‑day band
    # Start from the page_top
    if DRAW_MINICALS:
        # subtract the vertical space occupied by the two mini‑cals + padding
        mini_total_height = mini_block_h + (2 * mini_text_pad)
        grid_top -= mini_total_height

    if settings.DRAW_ALL_DAY:
        if not DRAW_MINICALS:
        # note: band_height is mini_h + 2*mini_text_pad in your code
            band_height = mini_block_h + (2 * mini_text_pad)
            grid_top -= band_height

    # How many hours will be shown
    hours_shown  = end_hour - start_hour
    available_h  = grid_top - grid_bottom
    hour_height  = available_h / hours_shown
    
    # Check for problematic values
    if available_h <= 0:
        logger.error("⚠️ LAYOUT ERROR: available_h={} is <= 0! This will cause rendering issues.", available_h)
    if hour_height <= 0:
        logger.error("⚠️ LAYOUT ERROR: hour_height={} is <= 0! This will cause rendering issues.", hour_height)
    if grid_right - grid_left <= 0:
        logger.error("⚠️ LAYOUT ERROR: Grid width={} is <= 0! This will cause rendering issues.", grid_right - grid_left)
    
    usable_width = grid_right - grid_left
    
    # Add hard bounds checking to prevent infinite loops
    MIN_USABLE_WIDTH = 100  # Minimum 100 points width
    MIN_AVAILABLE_HEIGHT = 50  # Minimum 50 points height
    MIN_HOUR_HEIGHT = 2  # Minimum 2 points per hour
    
    if usable_width < MIN_USABLE_WIDTH:
        logger.error("⚠️ FATAL: Usable width {} < minimum {} points. Layout impossible!", 
                    usable_width, MIN_USABLE_WIDTH)
        raise ValueError(f"Page too narrow: usable width {usable_width} < {MIN_USABLE_WIDTH} points")
    
    if available_h < MIN_AVAILABLE_HEIGHT:
        logger.error("⚠️ FATAL: Available height {} < minimum {} points. Layout impossible!", 
                    available_h, MIN_AVAILABLE_HEIGHT) 
        raise ValueError(f"Page too short: available height {available_h} < {MIN_AVAILABLE_HEIGHT} points")
    
    if hour_height < MIN_HOUR_HEIGHT:
        logger.error("⚠️ FATAL: Hour height {} < minimum {} points. Layout impossible!", 
                    hour_height, MIN_HOUR_HEIGHT)
        raise ValueError(f"Hour height too small: {hour_height} < {MIN_HOUR_HEIGHT} points")

    return {
        "grid_top":         grid_top,
        "grid_bottom":      grid_bottom,
        "grid_left":        grid_left,
        "grid_right":       grid_right,
        "hour_height":      hour_height,
        "start_hour":       start_hour,
        "end_hour":         end_hour,
        "time_label_width": time_label_width,
        "heading_size":     heading_size,
        "page_left":        page_left,
        "page_right":       page_right,
        "page_top":         page_top,
        "element_pad":      element_pad,
        "heading_ascent":   heading_ascent,
        "mini_text_pad":    mini_text_pad,
        "mini_block_gap":   mini_block_gap,
        "text_padding":     text_padding,
        "page_bottom":      page_bottom,
        "mini_block_h":     mini_block_h,

    }

def pixels_to_points(pixels, dpi):
    return pixels * 72 / dpi

def time_to_y(dt: datetime, layout: dict[str, float]) -> float:
    """
    Convert a datetime to a vertical position inside the grid.
    """
    elapsed = (dt.hour + dt.minute / 60) - layout["start_hour"]
    return layout["grid_top"] - elapsed * layout["hour_height"]

def get_page_size():
    env_size = settings.PDF_PAGE_SIZE
    env_dpi = settings.PDF_DPI
    try:
        px_width, px_height = map(int, env_size.lower().split("x"))
        width_pt = pixels_to_points(px_width, dpi=env_dpi)
        height_pt = pixels_to_points(px_height, dpi=env_dpi)
        return width_pt, height_pt
    except Exception as e:
        msg = f"⚠️ Invalid PDF_PAGE_SIZE or PDF_DPI: {e}. Using letter as the fallback size."
        logger.error("{}",msg)
        return letter
