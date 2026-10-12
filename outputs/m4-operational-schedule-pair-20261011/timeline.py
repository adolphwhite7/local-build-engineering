"""Generic same-day clock arithmetic on explicitly supplied ordered unit records."""
import re

def calculate(facts):
    if facts.get('scope') != 'same_evening_no_unprovided_delays':
        raise ValueError('Unsupported time scope; keep unresolved')
    start = facts['start']
    if not isinstance(start, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', start):
        raise ValueError('Invalid clock time')
    hour, minute = map(int, start.split(':'))
    current = hour * 60 + minute
    rows = []
    steps = facts['steps']
    if not isinstance(steps, list) or not 1 <= len(steps) <= 64:
        raise ValueError('Invalid ordered steps')
    for step in steps:
        duration = step['duration']
        if type(duration) is not int or duration < 0 or step['unit'] != 'minutes':
            raise ValueError('Explicit nonnegative minute units required')
        previous = current
        current += duration
        if current >= 24 * 60:
            raise ValueError('Next-day timing outside this same-day calculator')
        rows.append({'label':step['label'], 'duration_minutes':duration,
                     'starts':f'{previous//60:02d}:{previous%60:02d}',
                     'ends':f'{current//60:02d}:{current%60:02d}',
                     'checkpoint':step.get('checkpoint')})
    return {'start':start,'steps':rows,'total_minutes':current-(hour*60+minute),
            'contribution':'SOFTWARE_ARITHMETIC_FROM_OWNER_CONFIRMED_STRUCTURED_INPUT',
            'scope':facts['scope'],'model_reasoning_credit':False}
