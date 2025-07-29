import sys
import os
import subprocess
from datetime import datetime
from collections import Counter, defaultdict

from pypdf import PdfMerger
from loguru import logger
from reportlab.pdfgen import canvas


import ephemeris.settings as settings
from ephemeris.fonts import init_fonts
from ephemeris.config import load_config
from ephemeris.meta import load_meta, save_meta
from ephemeris.calendar_loader import load_raw_events
from ephemeris.event_processing import (
    expand_event_for_day,
    split_all_day_events,
    filter_events_for_day,
    compute_events_hash,
)
from ephemeris.layout import get_page_size
from ephemeris.utils import parse_date_range
from ephemeris.renderers import render_cover, render_schedule_pdf, export_pdf_to_png
from ephemeris.logger import configure_logging


def main():
    # 0) Set up logs
    configure_logging()
    # 1) Initialize fonts once
    init_fonts()

    # 2) Determine local timezone
    tz_local = settings.TZ_LOCAL
    logger.debug("Timezone: {}", settings.TIMEZONE)

    # 3) Build list of dates to render
    dr = settings.DATE_RANGE

    date_list = parse_date_range(dr, tz_local)

    # 4) Prepare canvas
    out_pdf = settings.OUTPUT_PDF
    os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
    c = canvas.Canvas(out_pdf, pagesize=get_page_size())
    if settings.SEPARATE_TEXT:
        bg_pdf = out_pdf.replace('.pdf', '_bg.pdf')
        text_pdf = out_pdf.replace('.pdf', '_text.pdf')
        c_bg = canvas.Canvas(bg_pdf, pagesize=get_page_size())
        c_text = canvas.Canvas(text_pdf, pagesize=get_page_size())
    else:
        c_bg = c_text = None

    # 5) Load config, metadata, and events
    config = load_config()
    meta   = load_meta()
    raw_events = load_raw_events(config["calendars"])

    # 6) Compute anchor & hash for change detection
    anchor    = f"{date_list[0].isoformat()}:{date_list[-1].isoformat()}"
    new_hash  = compute_events_hash(raw_events)
    last_anchor = meta.get("_last_anchor")
    prev_hash   = meta.get("events_hash")

    if not settings.FORCE_REFRESH and last_anchor == anchor and prev_hash == new_hash:
        logger.info("No changes for {}, skipping generation.", anchor)
        sys.exit(0)

    if settings.FORCE_REFRESH:
        logger.info("FORCE_REFRESH set, refreshing...")
    elif last_anchor != anchor:
        logger.info("Date-range changed: {} → {}, refreshing...", last_anchor, anchor)
    else:
        logger.info("Events changed, refreshing...")

    # 7) Build override map
    from ephemeris.event_processing import build_override_map
    override_map = build_override_map(raw_events)

    counts = Counter(cal_name for _, _, _, cal_name in raw_events)
    logger.debug("Event count by calender:")
    for cal_name, cnt in counts.items():
        logger.debug("   • {}: {} events", cal_name, cnt)

    # 8) Optionally render cover
    if settings.COVER_PAGE:
        logger.debug("Rendering cover page")
        w, h = get_page_size()
        cover_src = settings.DEFAULT_COVER
        render_cover(c, cover_src, w, h)
        c.showPage()

    # 9) Per-day expansion & rendering
    for d in date_list:
        logger.info("Processing {}",d)
        # expand & dedupe
        instances = []
        seen = set()
        for comp, color, tzf, name in raw_events:
            for st, en, title, meta_info in expand_event_for_day(comp, color, tzf, d, tz_local, override_map):
                uid = meta_info.get("uid")
                if uid in seen:
                    logger.opt(colors=True).debug("<yellow>Skipping duplicate: {}, {}. (UID: {}).</yellow>", title, st.isoformat(), uid)
                    continue
                seen.add(uid)
                instances.append((st, en, title, meta_info))

        # split and filter
        all_day, rest = split_all_day_events(instances, d, tz_local)
        all_day = filter_events_for_day(all_day, d)
        timed = filter_events_for_day(rest, d)

        # sort all-day into pre-grid, true all-day, post-grid
        from datetime import datetime, time, timedelta
        grid_start = datetime.combine(d, time(settings.START_HOUR, 0), tzinfo=tz_local)
        grid_end   = datetime.combine(d, time(settings.END_HOUR,   0), tzinfo=tz_local)
        sod        = datetime.combine(d, time.min).replace(tzinfo=tz_local)
        sod_next   = sod + timedelta(days=1)

        pre, true_all, post, other = [], [], [], []
        for st, en, title, meta in all_day:
            if en <= grid_start:
                pre.append((st,en,title,meta))
            elif st >= grid_end:
                post.append((st,en,title,meta))
            elif st == sod and en == sod_next:
                true_all.append((st,en,title,meta))
            else:
                other.append((st,en,title,meta))

        # within each bucket, sort by start time
        pre       .sort(key=lambda e: e[1])  # earliest-ending first
        true_all  .sort(key=lambda e: e[0])  # (all equal sod, so stable)
        other     .sort(key=lambda e: e[0])
        post      .sort(key=lambda e: e[0])

        all_day = pre + true_all + other + post

        # render schedule
        tmp = f"/tmp/schedule_{d.isoformat()}.pdf"
        render_schedule_pdf(
            timed,
            tmp,
            d,
            all_day_events=all_day,
            tz_local=settings.TZ_LOCAL,
            all_day_in_grid=settings.ALLDAY_IN_GRID,
            valid_dates=date_list,
            canvas_obj=c,
        )
        if settings.SEPARATE_TEXT:
            render_schedule_pdf(
                timed,
                tmp,
                d,
                all_day_events=all_day,
                tz_local=settings.TZ_LOCAL,
                all_day_in_grid=settings.ALLDAY_IN_GRID,
                valid_dates=date_list,
                canvas_obj=c_bg,
                draw_text=False,
                draw_shapes=True,
            )
            render_schedule_pdf(
                timed,
                tmp,
                d,
                all_day_events=all_day,
                tz_local=settings.TZ_LOCAL,
                all_day_in_grid=settings.ALLDAY_IN_GRID,
                valid_dates=date_list,
                canvas_obj=c_text,
                draw_text=True,
                draw_shapes=False,
            )
        logger.debug("Rendered {}",d)

    # 10) Write out PDF
    c.save()
    if settings.SEPARATE_TEXT:
        c_bg.save()
        c_text.save()
    logger.info("Wrote PDF to {}", out_pdf)
    
    if settings.FORMAT in ('png', 'both'):
        png_dir = export_pdf_to_png(
            pdf_path=out_pdf,
            date_list=date_list,
            cover=settings.COVER_PAGE,
            output_dir=settings.OUTPUT_PNG,
            dpi=settings.PDF_DPI,
        )
        logger.info("Exported PNGs to {}", png_dir)

        if settings.SEPARATE_TEXT:
            export_pdf_to_png(
                pdf_path=bg_pdf,
                date_list=date_list,
                cover=False,  # Separate PDFs don't include cover page
                output_dir=settings.OUTPUT_PNG_BG,
                dpi=settings.PDF_DPI,
            )
            export_pdf_to_png(
                pdf_path=text_pdf,
                date_list=date_list,
                cover=False,  # Separate PDFs don't include cover page
                output_dir=settings.OUTPUT_PNG_TEXT,
                dpi=settings.PDF_DPI,
                transparent=True,
            )
        
        # If the user only wants PNGs, remove the PDF:
        if settings.FORMAT == 'png':
            os.remove(out_pdf)
            logger.info("Removed merged PDF at {}", out_pdf)
            if settings.SEPARATE_TEXT:
                os.remove(bg_pdf)
                os.remove(text_pdf)

    # 11) Persist metadata
    save_meta({"_last_anchor": anchor, "events_hash": new_hash})
    logger.info("✅ Completed generation for {}", anchor)

    # 12) Run post-hook if configured
    if settings.POST_HOOK:
        logger.info("Running post-hook: {}", settings.POST_HOOK)
        try:
            result = subprocess.run(settings.POST_HOOK, shell=True, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                logger.info("Post-hook completed successfully")
                if result.stdout.strip():
                    logger.debug("Post-hook stdout: {}", result.stdout.strip())
            else:
                logger.error("Post-hook failed with exit code {}", result.returncode)
                if result.stderr.strip():
                    logger.error("Post-hook stderr: {}", result.stderr.strip())
        except subprocess.TimeoutExpired:
            logger.error("Post-hook timed out after 300 seconds")
        except Exception as e:
            logger.error("Failed to execute post-hook: {}", e)

if __name__ == '__main__':
    main()
