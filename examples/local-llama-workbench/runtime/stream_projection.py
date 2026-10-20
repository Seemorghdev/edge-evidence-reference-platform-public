"""Strict, bounded projection of a streamed JSON explanation; NOT final approval.

Only the `explanation` string is eligible. No tool arguments, SDK events, or
partially formatted response are exposed. A complete final answer is separately
checked by the unchanged presentation policy. This cannot retract seen drafts.
"""
from __future__ import annotations
import json
import re
from explanation_policy import check_explanation

MAX_WIRE = 8192
MAX_DRAFT = 1200
_PREFIX = re.compile(r'^\s*\{\s*"explanation"\s*:\s*"')

class DraftProjector:
    def __init__(self, classification: str):
        self.classification = classification
        self.raw = ''
        self.visible = ''
        self.blocked = False

    def feed(self, fragment: str, *, inspected: bool) -> str:
        if not inspected or self.blocked or not isinstance(fragment,str):
            return ''
        self.raw += fragment
        if len(self.raw) > MAX_WIRE:
            self.blocked=True
            return ''
        match = _PREFIX.match(self.raw)
        if not match:
            # Prefix could still be incomplete; never guess a JSON field.
            if len(self.raw)>96: self.blocked=True
            return ''
        text = self.raw[match.end():]
        escaped=False; end=len(text)
        for i,c in enumerate(text):
            if escaped: escaped=False
            elif c == "\\": escaped=True
            elif c=='"': end=i; break
        # A truncated escape or Unicode escape remains unshown.
        fragment=text[:end]
        try: decoded=json.loads('"'+fragment+'"')
        except ValueError: return ''
        if any(0xD800 <= ord(c) <= 0xDFFF for c in decoded): return ''
        if len(decoded)>MAX_DRAFT or (decoded.strip() and not check_explanation(
                json.dumps({'explanation':decoded}),self.classification)['accepted_for_display']):
            self.blocked=True; return ''
        # Hold a suffix so split forbidden words and intermediate escaping are not rendered.
        candidate=decoded[:max(0,len(decoded)-32)]
        boundary=candidate.rfind(' ')
        if boundary<0: return ''
        candidate=candidate[:boundary+1]
        if not candidate.startswith(self.visible):
            self.blocked=True;return ''
        if candidate and not check_explanation(json.dumps({'explanation':candidate}),self.classification)['accepted_for_display']:
            self.blocked=True;return ''
        delta=candidate[len(self.visible):]
        self.visible=candidate
        return delta
