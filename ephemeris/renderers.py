from io import BytesIO
import os
from datetime import datetime, time, tzinfo
import calendar
from tempfile import NamedTemporaryFile
from loguru import logger
import cairosvg
import subprocess
from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black, white
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.utils import ImageReader
from pypdf import PdfMerger




import ephemeris.settings as settings
from ephemeris.layout import get_layout_config, time_to_y, get_page_size
from ephemeris.event_processing import assign_stacks
from ephemeris.utils import css_color_to_hex, fmt_time


def init_text_helpers(hour_height):
    H30 = hour_height / 2.0
    H15 = H30 / 2.0

    # title sizes
    title15 = 0.75 * H15
    title30 = 0.50 * H30

    # time sizes (cap 15‑min at the 30‑min size)
    time30       = 0.33 * H30
    time15_uncap = 0.75 * H15
    time15       = min(time15_uncap, time30)

    # grab font metrics
    face = pdfmetrics.getFont("Montserrat-Regular").face

    def compute_baseline_offset(box_h, fs):
        ascent  = face.ascent  / 1000 * fs
        descent = face.descent / 1000 * fs
        return (box_h + ascent + descent) / 2.0

    def get_title_font_and_offset(d):
        fs = title15 if d == 15 else title30
        if   d == 15: box_h = H15
        elif d <= 30: box_h = H30 * (d / 30.0)
        else:          box_h = H30
        return fs, compute_baseline_offset(box_h, fs)

    def get_time_font_and_offset(d):
        fs = time15 if d == 15 else time30
        if   d == 15: box_h = H15
        elif d <= 30: box_h = H30 * (d / 30.0)
        else:          box_h = H30
        return fs, compute_baseline_offset(box_h, fs)

    return get_title_font_and_offset, get_time_font_and_offset

def draw_gray_strip(c, page_width, strip_height=20):
    """
    Draws a horizontal strip of gray0–gray15 at the bottom of the canvas.
    - c: ReportLab canvas
    - page_width: width of the page in points
    - strip_height: height of the strip in points
    """
    swatch_width = page_width / 16.0
    y = 0  # bottom of page
    for i in range(16):
        hexcode = css_color_to_hex(f"gray{i}")
        c.setFillColor(HexColor(hexcode))
        c.rect(i * swatch_width, y, swatch_width, strip_height, stroke=0, fill=1)

def draw_mini_cal(
    c,
    year,
    month,
    weeks,
    x,
    y,
    mini_w,
    mini_h,
    highlight_day=None,
    *,
    draw_text=True,
    draw_shapes=True,
):
    # Month label
    month_name = calendar.month_name[month]
    if draw_text:
        c.setFont("Montserrat-Regular", 6)
        c.drawCentredString(x + mini_w/2, y + mini_h + 4, f"{month_name} {year}")
    logger.log("VISUAL","Drawing mini-calendar for {}.", month_name)
    logger.log("VISUAL","    Height: {h:.2f}, Width: {w:.2f}",h=mini_h,w=mini_w)
    # Weekday headers
    days   = ['S','M','T','W','T','F','S']
    cell_w = mini_w / 7
    cell_h = 8
    if draw_text:
        c.setFont("Montserrat-Regular", 6)
        for i, d in enumerate(days):
            hx = x + i*cell_w + cell_w/2
            c.drawCentredString(hx, y + mini_h - 6, d)

    valid = getattr(c, "_valid_destinations", set())
    # Day numbers
    for row_i, week in enumerate(weeks):
        for col_i, day in enumerate(week):
            if day == 0:
                continue

            # compute the top‑left of this cell
            xx = x + col_i*cell_w
            yy = y + mini_h - 8 - (row_i+1)*cell_h

            # center of the cell
            cx = xx + cell_w/2
            # vertical offset: roughly center. adjust v_off if you like.
            v_off = cell_h/2 - 2
            if draw_text:
                c.setFont("Montserrat-Regular", 6)

            if highlight_day and day == highlight_day:
                if draw_shapes:
                    c.setFillColor(black)
                    c.rect(xx, yy, cell_w, cell_h, stroke=0, fill=1)

                if draw_text:
                    c.setFillColor(white)
                    c.setFont("Montserrat-SemiBold", 6)
                    c.drawCentredString(cx, yy + v_off, str(day))
                    c.setFillColor(black)
                    c.setFont("Montserrat-Regular", 6)

            else:
                # internal link rectangle
                dest_name = f"{year:04d}-{month:02d}-{day:02d}"
                if dest_name in valid:
                    if settings.CREATE_LINKS:
                        x1, y1 = xx, yy
                        x2, y2 = xx + cell_w, yy + cell_h
                        c.linkAbsolute(
                            "", dest_name,
                            Rect=(x1, y1, x2, y2),
                            Border='[0 0 0]'
                        )
                    if settings.INDICATE_DAYS:
                        c.setFont("Montserrat-Medium", 6)
                # normal day, centered
                if draw_text:
                    c.drawCentredString(cx, yy + v_off, str(day))

def draw_rect_with_optional_round(c, x, y, w, h, radius,
                                  round_top=True, round_bottom=True,
                                  stroke=1, fill=1):
    """
    Draws a rectangle at (x,y) of width w, height h.
    If round_bottom is True, rounds the bottom two corners with `radius`.
    If round_top is   True, rounds the top two corners.
    Otherwise corners are square.
    """
    p = c.beginPath()
    # start at bottom-left
    if round_bottom:
        p.moveTo(x + radius, y)
    else:
        p.moveTo(x, y)

    # bottom edge
    if round_bottom:
        p.lineTo(x + w - radius, y)
        p.arcTo(x + w - 2*radius, y, x + w, y + 2*radius,
                startAng=270, extent=90)
    else:
        p.lineTo(x + w, y)

    # right edge
    if round_top:
        p.lineTo(x + w, y + h - radius)
        p.arcTo(x + w - 2*radius, y + h - 2*radius, x + w, y + h,
                startAng=0, extent=90)
    else:
        p.lineTo(x + w, y + h)

    # top edge
    if round_top:
        p.lineTo(x + radius, y + h)
        p.arcTo(x, y + h - 2*radius, x + 2*radius, y + h,
                startAng=90, extent=90)
    else:
        p.lineTo(x, y + h)

    # left edge
    if round_bottom:
        p.lineTo(x, y + radius)
        p.arcTo(x, y, x + 2*radius, y + 2*radius,
                startAng=180, extent=90)
    else:
        p.lineTo(x, y)

    c.drawPath(p, stroke=stroke, fill=fill)

def draw_centered_multiline(
    c,
    lines,
    font_name,
    font_size,
    x,
    band_bottom,
    band_height,
    line_spacing=1.2,
    *,
    draw_text=True,
):
    face     = pdfmetrics.getFont(font_name).face
    ascent   = face.ascent  / 1000 * font_size
    descent  = abs(face.descent) / 1000 * font_size

    line_height  = font_size * line_spacing

    # ── BASELINE CALCULATION ────────────────────────
    # center of band minus half of (text block center offset)
    y_first = (
        band_bottom
        + (band_height / 2)
        - (line_height + ascent - descent) / 2
    )

    if draw_text:
        c.setFont(font_name, font_size)
        for i, line in enumerate(lines):
            y = y_first + (len(lines)-1 - i) * line_height
            c.drawString(x, y, line)

def render_time_grid(
    c,
    date_label,
    layout,
    override_label_hour: int | None = None,
    override_label_text: list[str] | None = None,
    *,
    draw_text=True,
    draw_shapes=True,
):
    GRIDLINE_COLOR = settings.GRIDLINE_COLOR
    text_padding = layout["text_padding"]

    # Vertical line
    if draw_shapes:
        c.setStrokeColor(css_color_to_hex(GRIDLINE_COLOR))
        c.setLineWidth(0.5)
        c.line(
            layout["grid_left"] +0.25,
            layout["grid_bottom"] + 1,
            layout["grid_left"] +0.25,
            layout["grid_top"] + 0.25
        )
    logger.log("VISUAL","Drawing time grid between {} - {}.", layout["start_hour"], layout["end_hour"])
    logger.log("VISUAL","    Top: {t:.2f}, Bottom: {b:.2f}",t=layout["grid_top"],b=layout["grid_bottom"])
    logger.log("VISUAL","    Left: {l:.2f}, Right: {l:.2f}",l=layout["grid_left"] ,r=layout["grid_right"])
    
    # Draw the grid heading
    if draw_text:
        c.setStrokeColor(css_color_to_hex(GRIDLINE_COLOR))
        c.setFont("Montserrat-SemiBold", 10)
        c.drawString((layout["grid_left"] +0.25), (layout["grid_top"] + 0.25 + text_padding), "Schedule")

    # Draw the horizontal hour lines and labels
    for hour in range(layout["start_hour"], layout["end_hour"] + 1):
        y = time_to_y(datetime.combine(date_label, time(hour=hour)), layout)
        # Emphasize the start hour
        if draw_shapes:
            if hour == layout["start_hour"]:
                c.setStrokeGray(0)
                c.setLineWidth(1)
            else:
                c.setStrokeColor(css_color_to_hex(GRIDLINE_COLOR))
                c.setLineWidth(0.5)
            c.line(layout["grid_left"], y, layout["grid_right"], y)
        # Draw either the override text or the normal time
        if override_label_hour is not None \
           and override_label_text is not None \
           and hour == override_label_hour:
            # two-line centered label inside this hour-slot
            if draw_text:
                if settings.MONOCHROME:
                    c.setFillGray(0)
                else:
                    c.setFillGray(0.2)
                c.setFont("Montserrat-SemiBold", 7)
                c.drawRightString(
                    layout["grid_left"] - 7,
                    y + 2,
                    "All",
                )
                c.drawRightString(
                    layout["grid_left"] - 5,
                    y - 6,
                    "Day",
                )

        else:
            if draw_text:
                if settings.MONOCHROME:
                    c.setFillGray(0)
                else:
                    c.setFillGray(0.2)
                c.setFont("Montserrat-SemiBold", 7)
                label = (
                    f"{hour:02}:00"
                    if settings.USE_24H
                    else datetime.combine(date_label, time(hour=hour)).strftime("%-I %p")
                )
                c.drawRightString(
                    layout["grid_left"] - 5,
                    y - 2,
                    label,
                )

def render_cover(
     c: canvas.Canvas,
     cover_src: str,
     page_w_pt: float,
     page_h_pt: float,
 ):
     """
     Rasterize svg_path → PNG, draw it full-width (or COVER_WIDTH_PT)
     on a single-page PDF, centered, then append to merger.
     """
     dpi = settings.PDF_DPI
     # 1) Desired image width in points (defaults to full page width)
     target_w_frac = settings.COVER_WIDTH_FRAC
     # 2) Vertical nudge
     v_frac      = settings.COVER_VERT_FRAC
 
     target_w_pt = page_w_pt *target_w_frac
     target_w_px = int(target_w_pt * (dpi/ 72.0))
 
     # 4) Rasterize SVG → PNG bytes
     png_bytes = cairosvg.svg2png(
         url=cover_src,
         output_width=target_w_px
     )
 
     # 5) Wrap in ImageReader
     buf = BytesIO(png_bytes)
     img = ImageReader(buf)
     px_w, px_h = img.getSize()
 
     # 6) Compute height in points to preserve aspect ratio
     img_w_pt = target_w_pt
     img_h_pt = px_h * (72.0 / dpi)
 
     # 7) Position centrally
     x = (page_w_pt - img_w_pt) / 2.0
     y = (page_h_pt - img_h_pt) * (1 - v_frac)

     tf = NamedTemporaryFile(suffix=".pdf", delete=False)
     cover_path = tf.name
     tf.close()
 
     # 8) Draw directly to the canvas
     c.drawImage(
         img, x, y,
         width=img_w_pt,
         height=img_h_pt,
         mask="auto",
         preserveAspectRatio=True
     )

def render_schedule_pdf(
    timed_events: list,
    output_path: str,
    date_label: datetime.date,
    all_day_events: list | None = None,
    tz_local: tzinfo          = settings.TZ_LOCAL,
    start_hour: int     = settings.START_HOUR,
    end_hour:   int     = settings.END_HOUR,
    grid_color: str     = settings.GRIDLINE_COLOR,
    event_fill: str     = settings.EVENT_FILL,
    event_stroke: str   = settings.EVENT_STROKE,
    footer_color: str   = settings.FOOTER_COLOR,
    all_day_in_grid: bool = False,
    valid_dates: list[datetime.date] = None,
    canvas_obj: canvas.Canvas = None,
    *,
    draw_text: bool = True,
    draw_shapes: bool = True,
):
    """
    Draw a full-day schedule:
      • title and line under it
      • optional all-day band (use all_day_events)
      • mini-calendars (in get_layout_config)
      • time grid (start_hour→end_hour)
      • each timed_event, stacked/ellipsized
      • footer
    """
    # Determine effective start hour (shift back one if in-grid)
    eff_start = start_hour - 1 if all_day_in_grid else start_hour 
    
    width, height = get_page_size()
    # if they passed in a canvas, draw onto that; otherwise make our own
    c = canvas_obj
    layout    = get_layout_config(width, height, eff_start, end_hour)
    text_padding = layout["text_padding"]
    DRAW_ALL_DAY_BAND = settings.DRAW_ALL_DAY_BAND
    DRAW_MINICALS = settings.DRAW_MINICALS
    MINICAL_ALIGN = settings.MINICAL_ALIGN
    page_top = layout["page_top"]
    page_left = layout["page_left"]
    page_right = layout["page_right"]
    heading_ascent = layout["heading_ascent"]
    heading_size = layout["heading_size"]
    element_pad = layout["element_pad"]
    mini_block_gap = layout["mini_block_gap"]
    grid_left = layout["grid_left"]
    mini_text_pad = layout["mini_text_pad"]
    hour_height = layout["hour_height"]
    MINICAL_ONLY_CURRENT = (settings.minical_mode == "current")
    MINICAL_HEIGHT = settings.MINICAL_HEIGHT
    MINICAL_OFFSET = settings.MINICAL_OFFSET
    ALLDAY_FROM = settings.ALLDAY_FROM

    # Link prep
    if valid_dates is not None:
            c._valid_destinations = {
                d.strftime("%Y-%m-%d")
                for d in valid_dates
            }
    else:
        c._valid_destinations = set()
    page_dest = date_label.strftime("%Y-%m-%d")
    c.bookmarkPage(page_dest)

    logger.log("VISUAL","Page size:")
    logger.log("VISUAL","   pixels: {}", settings.PDF_PAGE_SIZE)
    logger.log("VISUAL", "Page size: {w:.2f}×{h:.2f}", w=width, h=height)
    logger.log("VISUAL","DPI: {}", settings.PDF_DPI)
    logger.log("VISUAL","Page Margins:")
    logger.log("VISUAL","      Top: {}", settings.PDF_MARGIN_TOP)
    logger.log("VISUAL","   Bottom: {}", settings.PDF_MARGIN_BOTTOM)
    logger.log("VISUAL","    Right: {}", settings.PDF_MARGIN_RIGHT)
    logger.log("VISUAL","     Left: {}", settings.PDF_MARGIN_LEFT)


    # Force right alignment of mini-cals if we're drawing the all-day band
    if DRAW_ALL_DAY_BAND:
        MINICAL_ALIGN = "right"

    # Header/title
    title_y = page_top - heading_ascent  # Pin ascenders to page_top
    if draw_text:
        c.setFillGray(0)
        c.setFont("Montserrat-Bold", heading_size)
        c.drawCentredString(width/2, title_y, date_label.strftime('%A, %B %d, %Y'))

    # Line under title
    sep_y = title_y - element_pad
    if draw_shapes:
        if settings.MONOCHROME:
            c.setStrokeGray(0)
        else:
            c.setStrokeGray(0.4)
        c.setLineWidth(1)
        c.line(page_left, sep_y, page_right, sep_y)

    # Mini Calendar Definitions
    mini_w       = 80
    mini_h       = MINICAL_HEIGHT
    gap          = mini_block_gap
    total_w = mini_w + (0 if MINICAL_ONLY_CURRENT else mini_w + gap)

    if MINICAL_ALIGN == "left":
        x_start = page_left
    elif MINICAL_ALIGN == "grid":
        x_start = grid_left
    elif MINICAL_ALIGN == "center":
        x_start = page_left + ((page_right - page_left) - total_w) / 2
    else:  # right
        left_offset = MINICAL_OFFSET
        x_start     = page_right - total_w - left_offset
    y_cal = sep_y - element_pad - mini_h - (2 * mini_text_pad)

    # All Day Events
    band_left = page_left if ALLDAY_FROM == "margin" else grid_left
    if DRAW_MINICALS:
        band_right  = x_start - mini_block_gap
    else:
        band_right = page_right
    band_width  = band_right - band_left
    band_bottom = y_cal + element_pad
    band_top    = y_cal + mini_h + 2*mini_text_pad
    band_height = band_top - band_bottom

    # Label
    label_lines = ["All-Day", "Events"]
    all_day_label_font_size = (band_height * 0.33) / (len(label_lines) * 1.2)
    x_label = band_left + text_padding

    if DRAW_MINICALS:
        today = date_label
        first_of_month = today.replace(day=1)
        if first_of_month.month == 12:
            next_month = first_of_month.replace(year=first_of_month.year+1, month=1)
        else:
            next_month = first_of_month.replace(month=first_of_month.month+1)

        cal = calendar.Calendar(firstweekday=6)
        weeks1 = cal.monthdayscalendar(first_of_month.year, first_of_month.month)
        weeks2 = cal.monthdayscalendar(next_month.year, next_month.month)

        draw_mini_cal(
            c,
            first_of_month.year,
            first_of_month.month,
            weeks1,
            x_start,
            y_cal,
            mini_w,
            mini_h,
            highlight_day=today.day,
            draw_text=draw_text,
            draw_shapes=draw_shapes,
        )
        if not MINICAL_ONLY_CURRENT:
            draw_mini_cal(
                c,
                next_month.year,
                next_month.month,
                weeks2,
                x_start + mini_w + gap,
                y_cal,
                mini_w,
                mini_h,
                draw_text=draw_text,
                draw_shapes=draw_shapes,
            )

    # Main Grid
    if all_day_in_grid:
        render_time_grid(
            c,
            date_label,
            layout,
            override_label_hour=eff_start,
            override_label_text=["All Day", "Events"],
            draw_text=draw_text,
            draw_shapes=draw_shapes,
        )
    else:
        render_time_grid(
            c,
            date_label,
            layout,
            draw_text=draw_text,
            draw_shapes=draw_shapes,
        )

    # Events
    get_title_font_and_offset, get_time_font_and_offset = init_text_helpers(hour_height)
    events = assign_stacks(timed_events)
    if events:
        logger.log("VISUAL", "----------------------------------------------------------------------")
    events = sorted(events,
                    key=lambda e: (e["layer_index"], e["start"]))
    total_width = layout["grid_right"] - layout["grid_left"]
    logger.log("VISUAL","Total width available: {w:.2f} points", w=total_width)

    for event in events:
        start = event["start"]
        end = event["end"]
        title = event["title"]
        meta = event["meta"]
        width_frac = event["width_frac"]

        grid_start_dt = datetime.combine(date_label, time(settings.START_HOUR, 0)).replace(tzinfo=tz_local)
        grid_end_dt   = datetime.combine(date_label, time(settings.END_HOUR,   0)).replace(tzinfo=tz_local)

        # Handle off-grid starts
        draw_start = max(start, grid_start_dt)
        draw_end   = min(end,   grid_end_dt)

        if draw_start >= draw_end:
            continue

        start_eff = draw_start
        end_eff   = draw_end

        y_start = time_to_y(start_eff, layout)
        y_end   = time_to_y(end_eff,   layout)
        y_start_raw = time_to_y(start, layout)
        y_end_raw   = time_to_y(end,   layout)

        box_height = y_start - y_end

        box_width = total_width * width_frac

        box_x = layout["grid_right"] - box_width  # right-align

        # breached_top    = (y_start_raw > layout["grid_top"])
        # breached_bottom = (y_end_raw   < layout["grid_bottom"])
        breached_top    = (event["start"] < grid_start_dt)
        breached_bottom = (event["end"]   > grid_end_dt)


        # clamp to grid bounds
        clamped_y_start = min(y_start, layout["grid_top"])
        clamped_y_end   = max(y_end,   layout["grid_bottom"])
        clamped_h       = clamped_y_start - clamped_y_end

        
        hex_color = meta.get("calendar_color", "#FFFFFF")
        radius = 3 if box_height < 6 else 4
        color_bar_width = 2

        if draw_shapes:
            c.setStrokeColor(css_color_to_hex(event_stroke))
            c.setLineWidth(.33)
            c.setFillColor(HexColor(hex_color))
            draw_rect_with_optional_round(
                c,
                box_x,
                clamped_y_end,
                box_width,
                clamped_h,
                radius,
                round_top=not breached_top,
                round_bottom=not breached_bottom,
                stroke=0,
                fill=1,
            )

            c.setFillColor(css_color_to_hex(event_fill))
            draw_rect_with_optional_round(
                c,
                box_x + color_bar_width,
                clamped_y_end,
                box_width - color_bar_width,
                clamped_h,
                radius,
                round_top=not breached_top,
                round_bottom=not breached_bottom,
                stroke=1,
                fill=1,
            )

        duration_minutes = (end_eff - start_eff).total_seconds() / 60

        logger.log("VISUAL","Event: '{}' ({} min)", title, int(duration_minutes))
        logger.log("VISUAL","        Size: box_x: {x:.2f} | box_width: {w:.2f} | box_height: {h:.2f}", title, x=box_x, w=box_width, h=box_height)

        # Calculate font sizes and labels needed for layout calculations
        font_size, y_offset = get_title_font_and_offset(duration_minutes)
        time_label = f"{fmt_time(start)} - {fmt_time(end)}"
        title_font_size, title_y_offset = get_title_font_and_offset((end_eff - start_eff).total_seconds()/60)
        time_font_size,  time_y_offset  = get_time_font_and_offset((end_eff - start_eff).total_seconds()/60)

        # Decide hide/move flags for time before ellipsizing
        has_direct_above = False
        above_event = None
        min_layer_diff = float("inf")
        min_delta = None
        for other in events:
            if other["layer_index"] <= event["layer_index"]:
                continue
            if not (start_eff < other["end"] and other["start"] < end_eff):
                continue
            delta = abs((other["start"] - start_eff).total_seconds())
            if delta <= 30 * 60:
                layer_diff = other["layer_index"] - event["layer_index"]
                if layer_diff < min_layer_diff or (
                    layer_diff == min_layer_diff and (min_delta is None or delta < min_delta)
                ):
                    has_direct_above = True
                    above_event = other
                    min_layer_diff = layer_diff
                    min_delta = delta
        if draw_text:
            raw_title_w = c.stringWidth(title, "Montserrat-Regular", title_font_size)
            inline_space = (
                box_width
                - 4
                - 2 * text_padding
                - c.stringWidth(time_label, "Montserrat-Regular", time_font_size)
            )

            should_move_for_title = duration_minutes >= 60 and raw_title_w > inline_space
            hide_time = has_direct_above and duration_minutes < 60
            move_time = (has_direct_above and duration_minutes >= 60) or should_move_for_title

            # Ellipsize title:
            #   reserve space for the time if inline; but always avoid occlusion by a
            #   next-layer box whose start is within 30 min
            title_x_start = box_x + 4 + text_padding
            time_reserve  = 0 if (hide_time or move_time) else \
                            c.stringWidth(time_label, "Montserrat-Regular", time_font_size)
            max_w_time    = box_width - 4 - 2 * text_padding - time_reserve

            # compute occlusion constraint regardless of hide/move
            max_w_occ = max_w_time
            for other in events:
                if other["layer_index"] <= event["layer_index"]:
                    continue
                if not (start_eff < other["end"] and other["start"] < end_eff):
                    continue
                delta = (other["start"] - start_eff).total_seconds()
                if delta < 30 * 60:
                    other_w = total_width * other["width_frac"]
                    other_x = layout["grid_right"] - other_w
                    avail = other_x - title_x_start - 2
                    max_w_occ = min(max_w_occ, avail)

            final_max_w = max(0, min(max_w_time, max_w_occ))
            display_title = title
            if c.stringWidth(display_title, "Montserrat-Regular", title_font_size) > final_max_w:
                # truncate
                while (
                    display_title
                    and c.stringWidth(display_title + "...", "Montserrat-Regular", title_font_size)
                    > final_max_w
                ):
                    display_title = display_title[:-1]
                display_title = display_title.rstrip() + "..."

            # Draw title
            c.setFont("Montserrat-Regular", font_size)
            y_text = y_start - title_y_offset
            c.drawString(box_x + 2 + text_padding, y_text, display_title)
            
            c.setFont("Montserrat-Regular", time_font_size)

                # Shift time horizontally if we have an overlapping event, but space to move it to
                horizontal_shift = False
                if duration_minutes < 60 and has_direct_above:
                    # find X of the overlapping box’s left edge
                    other_w = total_width * above_event["width_frac"]
                    other_x = layout["grid_right"] - other_w
                    # how many points from our left padding to that edge?
                    visible_space = (other_x - (box_x + 2 + text_padding))
                    # how much width do we need?
                    title_w = c.stringWidth(display_title, "Montserrat-Regular", title_font_size)
                    time_w  = c.stringWidth(time_label,    "Montserrat-Regular", time_font_size)
                    needed = title_w + time_w + text_padding
                    if needed <= visible_space:
                        horizontal_shift = True

                # Handle edge case where moving the time would force it off the grid
                if move_time:
                    # compute the would-be y_time for the moved label
                    y_title = y_start - title_y_offset
                    y_time  = y_title - (text_padding / 2) - time_y_offset
                    # if that y_time falls below grid_bottom, don’t move it
                    if y_time < layout["grid_bottom"]:
                        move_time = False
                        hide_time = True
                if horizontal_shift:
                    logger.opt(colors=True).log(
                        "VISUAL",
                        "        <cyan>Moving time horizontally because overlapping event {} @ {}.</cyan>",
                        above_event["title"],
                        above_event["start"].strftime("%H:%M"),
                    )
                    other_w = total_width * above_event["width_frac"]
                    other_x = layout["grid_right"] - other_w
                    x_time = other_x - text_padding
                    y_time = y_start - y_offset
                    c.drawRightString(x_time, y_time, time_label)
                elif hide_time:
                    logger.opt(colors=True).log(
                        "VISUAL",
                        "        <yellow>Hiding time because overlapping event {} @ {}.</yellow>",
                        above_event["title"],
                        above_event["start"].strftime("%H:%M"),
                    )
                elif move_time:
                    if should_move_for_title:
                        logger.opt(colors=True).log(
                            "VISUAL",
                            "        <cyan>Moving time because the title is too long.</cyan>",
                        )
                    else:
                        logger.opt(colors=True).log(
                            "VISUAL",
                            "        <cyan>Moving time because overlapping event {} @ {}.</cyan>",
                            above_event["title"],
                            above_event["start"].strftime("%H:%M"),
                        )
                    y_title = y_start - title_y_offset
                    y_time = y_title - (text_padding / 2) - time_y_offset
                    x_time = box_x + 2 + text_padding
                    c.drawString(x_time, y_time, time_label)
                else:
                    logger.log(
                        "VISUAL",
                        "        Drawing inline time; no overlapping event detected.",
                        title,
                        int(duration_minutes),
                    )
                    y_time = y_start - y_offset
                    c.drawRightString(box_x + box_width - text_padding, y_time, time_label)

    bar_w          = 2
    
    if DRAW_ALL_DAY_BAND:
        # Draw label string
        if draw_text:
            if settings.MONOCHROME:
                c.setFillGray(0)
            else:
                c.setFillGray(0)  # Black text for the label
        draw_centered_multiline(
            c,
            label_lines,
            "Montserrat-SemiBold",
            all_day_label_font_size,
            x_label,
            band_bottom,
            band_height,
            line_spacing=1.2,
            draw_text=draw_text,
        )

        # Compute label‐column width
        c.setFont("Montserrat-SemiBold", all_day_label_font_size)
        label_w = max(
            c.stringWidth(line, "Montserrat-SemiBold", all_day_label_font_size)
            for line in label_lines
        )
        label_area = label_w + 2 * text_padding

        n              = len(all_day_events)
        slots_per_col  = 4
        slot_h         = band_height / slots_per_col
        cols           = 1 if n <= slots_per_col else 2
        capacity       = slots_per_col * cols
        to_draw        = all_day_events[:capacity]
        events_left    = band_left + label_area
        events_width   = band_right - events_left
        slot_w         = events_width / cols
        pad            = 2

        get_title_font_and_offset, _ = init_text_helpers(hour_height)

        if draw_shapes:
            # Draw vertical separator
            sep_x = events_left
            c.setStrokeColor(black)
            c.setLineWidth(0.5)
            c.line(sep_x, band_bottom, sep_x, band_top)

        if draw_shapes:
            # Draw box
            c.setStrokeColor(black)
            c.setLineWidth(0.5)
            c.roundRect(band_left, band_bottom, band_width, band_height, 4, stroke=1, fill=0)

        # Draw the actual all day events, if they exist
        if all_day_events:

            for idx, (st, en, title, meta) in enumerate(to_draw):
                logger.log("EVENTS","All-day event slot: {} → {} | {} | all_day? {}", st, en, title, meta.get("all_day"))
                col = idx // slots_per_col
                row = idx %  slots_per_col

                x = events_left + col * slot_w + (2* pad)
                y = band_top  - (row+1)*slot_h    + pad
                w = slot_w   - pad*3
                h = slot_h   - pad*2

                if draw_shapes:
                    c.setFillColor(HexColor(meta.get("calendar_color", "#FFFFFF")))
                    c.roundRect(x, y, w, h, 4, stroke=0, fill=1)
                    c.setFillColor(css_color_to_hex(event_fill))
                    c.setStrokeColor(css_color_to_hex(event_stroke))
                    c.setLineWidth(0.33)
                    c.roundRect(x + bar_w, y, w - bar_w, h, 4, stroke=1, fill=1)

                # size the font as a fixed fraction of the box height
                # e.g. use 40% of the box height
                title_fraction = 0.6
                time_fraction = 0.4

                title_fs = h * title_fraction
                time_fs = h * time_fraction
                # enforce reasonable min/max so text never disappears or overflows
                title_fs = max(6, min(title_fs, h * 0.8))
                time_fs = max(4, min(time_fs, h * 0.8))
                # now compute vertical centering baseline
                title_face    = pdfmetrics.getFont("Montserrat-Regular").face
                title_ascent  = title_face.ascent  / 1000 * title_fs
                title_descent = title_face.descent / 1000 * title_fs
                title_baseline = (h + title_ascent + title_descent) / 2.0
                c.setFont("Montserrat-Regular", title_fs)

                time_face    = pdfmetrics.getFont("Montserrat-Regular").face
                time_ascent  = time_face.ascent  / 1000 * time_fs
                time_descent = time_face.descent / 1000 * time_fs
                time_baseline = (h + time_ascent + time_descent) / 2.0



                inner_w = (w - bar_w) - 4
                txt     = title

                if not (st.time() == time.min and en.time() == time.min):
                    time_label = meta.get('time_label', f"{fmt_time(st)}–{fmt_time(en)}")
                    while c.stringWidth(txt + "...", "Montserrat-Regular", title_fs) + c.stringWidth(time_label, "Montserrat-Regular", time_fs) + text_padding > inner_w:
                        txt = txt[:-1]
                    if txt != title:
                        txt = txt.rstrip() + "..."

                    if draw_text:
                        text_y = y + h - title_baseline
                        time_y = y + h - time_baseline
                        c.setFillGray(0)
                        c.drawString(x + bar_w + 2, text_y, txt)

                        c.setFont("Montserrat-Regular", time_fs)
                        c.drawRightString(x + w - text_padding, time_y, time_label)
                else:
                    while c.stringWidth(txt + "...", "Montserrat-Regular", title_fs) > inner_w:
                        txt = txt[:-1]
                    if txt != title:
                        txt = txt.rstrip() + "..."

                    if draw_text:
                        text_y = y + h - title_baseline
                        c.setFillGray(0)
                        c.drawString(x + bar_w + 2, text_y, txt)

    if all_day_in_grid and all_day_events:
        # slot_h = layout["hour_height"] * 0.25
        # ─── split into columns ───────────────────────────
        n               = len(all_day_events)
        slots_per_col   = 4
        if   n <= slots_per_col:
            cols = 1
        else:
            cols = 2
        capacity        = slots_per_col * cols
        events_to_draw  = all_day_events[:capacity]

        # height and width per slot
        slot_h = layout["hour_height"] * 0.25
        total_w = layout["grid_right"] - layout["grid_left"]
        col_w   = total_w / cols
        for idx, (st, en, title, meta) in enumerate(all_day_events):
            col = idx // slots_per_col
            row = idx %  slots_per_col

            # position in multi-col grid
            x = layout["grid_left"] + col * col_w
            y = layout["grid_top"]  - row * slot_h
            w = col_w
            h = slot_h

            if draw_shapes:
                c.setFillColor(HexColor(meta.get("calendar_color", "#FFFFFF")))
                c.roundRect(x, y - h, w, h, 4, stroke=0, fill=1)
                c.setFillColor(css_color_to_hex(event_fill))
                c.setStrokeColor(css_color_to_hex(event_stroke))
                c.setLineWidth(0.33)
                c.roundRect(x + bar_w, y - h, w - bar_w, h, 4, stroke=1, fill=1)

            fs_title, title_offset = get_title_font_and_offset(15)
            fs_time,  time_offset  = get_time_font_and_offset(15)

            # only show a time-label if not true 00:00–00:00
            show_time = not (st.time() == time.min and en.time() == time.min)
            label = title
            if show_time:
                tl = f"{fmt_time(st)}–{fmt_time(en)}"
                # truncate title to fit
                while c.stringWidth(label + '…', "Montserrat-Regular", h*0.5) + c.stringWidth(tl, "Montserrat-Regular", h*0.3) + 4 > w:
                    label = label[:-1]
                if label != title:
                    label = label.rstrip() + '…'

            if draw_text:
                y_top = y  # this is the top of our 15-min block
                c.setFillColor(black)
                # title line
                text_y = y_top - title_offset
                c.setFont("Montserrat-Regular", fs_title)
                c.drawString(x + 4, text_y, label)
                # optional time line
                if show_time:
                    time_y = y_top - time_offset
                    c.setFont("Montserrat-Regular", fs_time)
                    c.drawRightString(x + w - 4, time_y, tl)

    now = datetime.now(tz_local)
    footer = settings.FOOTER
    page_bottom = settings.PDF_MARGIN_BOTTOM
    if footer == "updatedat":
        if settings.USE_24H:
            footer_text = now.strftime("Updated: %Y-%m-%d %H:%M %Z")
        else:
            footer_text = now.strftime("Updated: %Y-%m-%d %I:%M %p %Z")
    else:
        footer_text = footer
    if footer != "disabled" and draw_text:
        c.setFont("Montserrat-Light", 6)
        c.setFillColor(css_color_to_hex(settings.FOOTER_COLOR))
        c.drawCentredString(width/2, page_bottom, footer_text)

    # # RENDER MARGINS FOR TESTING
    # c.setStrokeGray(0.4)
    # c.setLineWidth(0.5)
    # c.line(page_right, page_top, page_right, page_bottom)
    # c.line(page_left, page_top, page_left, page_bottom)
    # c.line(page_right, page_top, page_left, page_top)
    # c.line(page_right, page_bottom, page_left, page_bottom)

    c.showPage()
    
def export_pdf_to_png(pdf_path: str,
                      date_list: list,
                      cover: bool,
                      output_dir: str = None,
                      dpi: int = 150,
                      transparent: bool = False):
    """
    Calls Poppler's pdftocairo to rasterize each page of `pdf_path` to PNG.
    Output files:
      - cover.png       (if cover=True)
      - schedule_YYYY-MM-DD.png
    """
    # prepare output directory
    base = Path(pdf_path).with_suffix('')
    out_dir = Path(output_dir or f"{base}_png")
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Rendering PNGs...")

    # prefix for pdftocairo (it will append -1.png, -2.png, etc)
    prefix = str(out_dir / "page")

    args = [
        "pdftocairo",
        "-png",
        "-r", str(dpi),
    ]
    if transparent:
        args.append("-transp")
    if settings.MONOCHROME:
        logger.debug("Drawing in monochrome.")
        args.append("-mono")
        args.append("-antialias")
        args.append("none")
    elif not settings.ANTIALIAS:
        logger.debug("Drawing with anti-aliasing disabled.")
        args.append("-antialias")
        args.append("none")
    args.extend([
        str(pdf_path),
        prefix
    ])

    subprocess.run(args, check=True)

    # rename page-N.png → cover.png / ephemeris_YYYY-MM-DD.png
    for file in sorted(out_dir.glob("page-*.png")):
        idx = int(file.stem.split('-')[1])  # 1-based page number
        if cover and idx == 1:
            new_name = out_dir / "cover.png"
        else:
            date = date_list[idx - (1 if cover else 0) - 1]
            new_name = out_dir / f"ephemeris_{date.isoformat()}.png"
        file.rename(new_name)

    return str(out_dir)
