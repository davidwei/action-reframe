"""Resolve proposals without treating shared ancestry as independent confirmation."""
from tracking_selection import overlap


def reliable(row,threshold):
    from verification_policy import accepted_row
    return accepted_row(row,threshold)


def resolve(previous,candidate,threshold=.5,agreement_iou=.35):
    if previous and previous.get('manual'):return previous,False
    if not reliable(candidate,threshold):return previous or candidate,False
    if not reliable(previous,threshold):return candidate,False
    if (overlap(previous['bbox'],candidate['bbox']) or 0)<agreement_iou:
        return dict(frame=candidate['frame'],time=candidate['time'],bbox=None,confidence=0,
                    visibility='uncertain',selection_flags=['tracking_branch_conflict'],
                    selection_reason='Conflicting branches require independent localization',
                    conflict=True),True
    # Agreement never increases confidence. Prefer an actual localization over a search region.
    quality=lambda r:(bool(r.get('localized')),r.get('confidence',0))
    return (candidate if quality(candidate)>quality(previous) else previous),False
