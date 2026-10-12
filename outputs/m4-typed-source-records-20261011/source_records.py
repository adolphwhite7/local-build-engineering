"""Offline authoring prototype. Source attribution is not semantic confirmation."""
import copy
import hashlib
import re

WORDS = dict(zip(('one two three four five six seven eight nine ten eleven twelve'
                  ' thirty').split(), list(range(1, 13)) + [30]))
SCALAR = re.compile(r'\b\d{4}-\d{2}-\d{2}\b|\b\d{2}:\d{2}\b|'
                    r'\$[\d,]+(?:\.\d+)?|\b\d+(?:\.\d+)?\b|\b(?:'
                    + '|'.join(WORDS) + r')\b', re.I)


def source_ref(path, text, start, end):
    """Offsets are UTF8 bytes, never character offsets or generated quotations."""
    return {'path': path, 'sha256': hashlib.sha256(text.encode()).hexdigest(),
            'start': len(text[:start].encode()), 'end': len(text[:end].encode()),
            'quote': text[start:end]}


def locate(path, text, quote):
    if text.count(quote) != 1:
        raise ValueError('source quotation missing or ambiguous')
    start = text.index(quote)
    return source_ref(path, text, start, start + len(quote))


def verify(ref, sources):
    raw = sources[ref['path']].encode()
    if hashlib.sha256(raw).hexdigest() != ref['sha256']:
        raise ValueError('source changed')
    if not 0 <= ref['start'] < ref['end'] <= len(raw):
        raise ValueError('invalid source span')
    if raw[ref['start']:ref['end']].decode() != ref['quote']:
        raise ValueError('source span mismatch')
    return ref['quote']


def nominate(path, text):
    """Nominate scalar lexemes with surrounding text, no roles or currentness."""
    result = []
    for match in SCALAR.finditer(text):
        start = text.rfind('\n\n', 0, match.start()) + 2
        if start == 1:
            start = 0
        end = text.find('\n\n', match.end())
        if end == -1:
            end = len(text)
        result.append({'value': source_ref(path, text, *match.span()),
                       'context': source_ref(path, text, start, end),
                       'role': None, 'unit': None, 'authority': None,
                       'state': 'NOMINATION_ONLY'})
    return result


def confirmed_value(record, sources):
    """Validate supplied source-level mapping, never invent its semantic owner."""
    if not record.get('confirmed_by') or not record.get('unit_basis'):
        raise ValueError('field role/unit not confirmed')
    for ref in record.get('qualifiers', []):
        verify(ref, sources)
    token = verify(record['value'], sources)
    if record['unit'] == 'clock_hhmm':
        if not re.fullmatch(r'\d{2}:\d{2}', token):
            raise ValueError('clock grammar')
        hour, minute = map(int, token.split(':'))
        if hour > 23 or minute > 59:
            raise ValueError('clock range')
        return hour * 60 + minute
    if record['unit'] != 'minutes':
        raise ValueError('unsupported arithmetic unit')
    if token.lower() in WORDS:
        return WORDS[token.lower()]
    if not re.fullmatch(r'\d+', token):
        raise ValueError('duration grammar')
    return int(token)


def schedule(records, sources, early, proposal, departure, durations):
    """Same-day arithmetic only; caller supplies roles and scope confirmation."""
    names = [early, proposal, departure, *durations]
    if len(names) != len(set(names)):
        raise ValueError('duplicate operands')
    values = {name: confirmed_value(records[name], sources) for name in names}
    for name in (early, proposal, departure):
        if records[name]['unit'] != 'clock_hhmm':
            raise ValueError('clock unit required')
    if any(records[name]['unit'] != 'minutes' for name in durations):
        raise ValueError('duration unit required')
    if any(records[name].get('day_scope') != 'confirmed_same_day'
           for name in (early, proposal, departure)):
        raise ValueError('same-day scope not confirmed')
    if values[proposal] < values[early] or values[departure] < values[early]:
        raise ValueError('overnight scope requires explicit dates')
    required = sum(values[name] for name in durations)
    return {'required_minutes': required,
            'proposal_gap_minutes': values[proposal] - values[early],
            'departure_gap_minutes': values[departure] - values[early],
            'proposal_shortfall_minutes': max(0, required - values[proposal] + values[early]),
            'qualification': 'CONDITIONAL_ON_DECLARED_SOURCE_ROLE_UNIT_AND_DAY_CONFIRMATION'}


def present(saved, known, unknown, sources):
    """Keep saved useful output and model judgment; append exact bounded findings."""
    result = copy.deepcopy(saved)
    for item in [*known, *unknown]:
        verify(item['source'], sources)
    result['known_from_supplied_records'] = copy.deepcopy(known)
    result['unknown_in_supplied_records'] = copy.deepcopy(unknown)
    result['answer'] = list(saved.get('answer', []))
    result['answer'] += [f"Known — {item['label']}: {item['source']['quote']}"
                         for item in known]
    result['answer'] += [f"Unknown in supplied records — {item['label']}: {item['source']['quote']}"
                         for item in unknown]
    result['qualification'] = 'OFFLINE_PRESENTATION_OF_SAVED_RESULT_NO_NEW_MODEL_JUDGMENT'
    return result
