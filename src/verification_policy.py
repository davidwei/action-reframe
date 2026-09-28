"""Shared identity/localization policy; completeness is diagnostic for schema v7+."""
import math

VERSION = 2


def target_description(config):
    return config.get('approved_target_description') or config['target']


def verification_decision(result, threshold=.5):
    comparison = result.get('comparison', {})
    score = comparison.get('match_score', 0)
    valid_score = isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score)
    if result.get('error'):
        category, reason = 'request_error', result['error']
    elif not comparison.get('target_present') or not valid_score or not threshold <= score <= 1:
        category, reason = 'identity_rejected', 'Target absent or identity confidence below threshold'
    elif comparison.get('exclusion_check') == 'contradicted':
        category, reason = 'identity_rejected', comparison.get('exclusion_reason') or 'Explicit identity requirement contradicted'
    elif result.get('version', 0) >= 7 and comparison.get('localization_support') != 'supported' and not (
        result.get('verification_context')=='optical_motion' and result.get('motion_reliable') is True
        and comparison.get('localization_support')=='ambiguous'):
        category, reason = 'localization_rejected', comparison.get('localization_reason') or 'Crop does not isolate the intended subject'
    elif result.get('version', 0) < 7 and comparison.get('target_complete') is not True:
        category, reason = 'localization_rejected', 'Legacy verification lacks supported localization/completeness'
    else:
        category, reason = 'accepted', ('Identity supported; ambiguous localization accepted for reliable optical motion'
            if comparison.get('localization_support')=='ambiguous' else 'Identity and localization supported; partial visibility is allowed')
    return dict(accepted=category == 'accepted', category=category, reason=reason, threshold=threshold, policy_version=VERSION)


def accepted_row(row, threshold=.5):
    if not row or (not row.get('manual') and (row.get('error') or row.get('scene_cut') or row.get('conflict'))):
        return False
    box, score = row.get('bbox'), row.get('confidence', 0)
    valid = (isinstance(box, (list, tuple)) and len(box) == 4
             and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1000 for v in box)
             and box[0] < box[2] and box[1] < box[3]
             and isinstance(score, (int, float)) and math.isfinite(score) and threshold <= score <= 1
             and row.get('visibility') in ('visible', 'partial'))
    if not valid: return False
    if row.get('manual'): return True
    if row.get('identity_verified') is False or row.get('analysis_source')=='optical_unverified':return False
    verification = row.get('box_verification')
    # Preserve historical unverified rows for playback; new verified rows use the full policy.
    return not verification or verification.get('version',0)<7 or verification_decision(verification, threshold)['accepted']


def verification_anchor_eligible(result, threshold=.5, high=.85, localized=True):
    if not localized or not verification_decision(result,max(threshold,high))['accepted']:return False
    if result.get('version',0)>=7 and result.get('comparison',{}).get('localization_support')!='supported':return False
    return (result.get('comparison',{}).get('exclusion_check')=='pass' if result.get('version',0)>=7
            else result.get('comparison',{}).get('target_complete') is True)


def anchor_eligible(row, threshold=.5, high=.85):
    if not accepted_row(row, max(threshold, high)) or not row.get('localized'): return False
    if row.get('manual'): return True
    result = row.get('box_verification', {})
    if result.get('version',0)<7:return result.get('comparison',{}).get('target_complete') is True
    return verification_anchor_eligible(result,threshold,high)
