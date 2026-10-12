"""Isolated arithmetic syntax check. Never determines source meaning or repairs text."""
import re

WORDS = dict(zip(
    'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty'.split(),
    range(21),
))
NUM = r'(?:[0-9]{1,9}|' + '|'.join(WORDS) + r')'
TOKEN = re.compile(r'\b' + NUM + r'\b', re.I)
SYMBOLIC = re.compile(r'(' + NUM + r'(?:\s*\+\s*' + NUM + r')+)\s*=\s*(' + NUM + r')', re.I)
ITEM = re.compile(r'(' + NUM + r')\s+([a-z]+(?:\s+[a-z]+)*)', re.I)
TOTAL = re.compile(r'(' + NUM + r')(?:\s+[a-z]+)*', re.I)
UNSUPPORTED_NUMBER_WORDS = {'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety', 'hundred', 'thousand', 'million', 'billion', 'dozen', 'half', 'quarter', 'minus', 'negative', 'point'}
CONNECTORS = {'and', 'or', 'plus'}


def number(token):
    return int(token) if token.isascii() and token.isdecimal() else WORDS[token.lower()]


def check_claim(clause):
    """Two disclosed grammars only: A + B = C, or A label, B label, and C label, which totals D label."""
    symbolic = SYMBOLIC.fullmatch(clause)
    if symbolic:
        terms = [number(t.strip()) for t in symbolic[1].split('+')]
        claimed = number(symbolic[2])
        grammar = 'unsigned_integer_addition_equality'
    elif clause.count(', which totals ') == 1:
        left, right = clause.split(', which totals ')
        # Prefix is unconstrained prose, but may contain no number token or
        # punctuation that could hide a different mathematical construction.
        first = TOKEN.search(left)
        if not first or re.search(r'[^a-z\s]', left[:first.start()], re.I):
            return None
        if set(left[:first.start()].lower().split()) & (UNSUPPORTED_NUMBER_WORDS | CONNECTORS):
            return None
        items = left[first.start():].split(', ')
        if len(items) < 2 or not items[-1].startswith('and '):
            return None
        items[-1] = items[-1][4:]
        terms = []
        for item in items:
            parsed = ITEM.fullmatch(item)
            if not parsed or TOKEN.search(parsed[2]) or set(parsed[2].lower().split()) & (UNSUPPORTED_NUMBER_WORDS | CONNECTORS):
                return None
            terms.append(number(parsed[1]))
        total = TOTAL.fullmatch(right)
        if not total:
            return None
        tail = right[len(total[1]):]
        if TOKEN.search(tail) or set(tail.lower().split()) & (UNSUPPORTED_NUMBER_WORDS | CONNECTORS):
            return None
        claimed = number(total[1])
        grammar = 'enumerated_terms_which_totals'
    else:
        return None
    if len(terms) > 16:
        return None
    computed = sum(terms)
    return {'grammar': grammar, 'claim_text': clause, 'terms': terms,
            'claimed_total': claimed, 'computed_total': computed,
            'status': 'NUMERICALLY_CONSISTENT' if claimed == computed else 'NUMERIC_CLAIM_INCONSISTENT'}


def check_answer(text):
    """Unsupported clauses remain unresolved; no eval, imports, tools or semantic decisions."""
    if not isinstance(text, str) or len(text) > 8192:
        return {'status': 'UNRESOLVED', 'claims': [], 'unresolved_clauses': [], 'reason': 'unsupported input type or length'}
    claims, unresolved = [], []
    for clause in re.split(r'(?<!\d)\.(?!\d)|[!?;\n]', text):
        clause = clause.strip()
        if not clause:
            continue
        result = check_claim(clause)
        if result is None:
            unresolved.append(clause)
        else:
            claims.append(result)
    status = ('NUMERIC_CLAIM_INCONSISTENT' if any(c['status'] == 'NUMERIC_CLAIM_INCONSISTENT' for c in claims)
              else 'RECOGNIZED_CLAIMS_CONSISTENT' if claims else 'UNRESOLVED')
    return {'status': status, 'claims': claims, 'unresolved_clauses': unresolved,
            'unresolved_dimensions': ['operand role relevance', 'units', 'scope', 'currentness', 'intent', 'task implications'],
            'original_answer': text, 'answer_repaired': False,
            'coverage': 'Recognized addition claims only; no correctness judgment about the whole answer.'}
