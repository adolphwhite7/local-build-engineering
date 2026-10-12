"""Isolated supplied-record adapter; no file lookup, inference or semantic rules."""
import copy
import re


def one(items, label):
    if len(items) != 1:
        raise ValueError(label + ' missing or ambiguous')
    return items[0]


def bind(blocks):
    """Bind the single supplied gift via declared F/H/G/GG/TY record grammar.

    This is not natural-language retrieval. Multiple gifts require a separately
    established subject; this adapter refuses rather than guessing that subject.
    No status, approval, negation, person name, amount or answer is inferred.
    """
    if len({b['id'] for b in blocks}) != len(blocks):
        raise ValueError('duplicate evidence IDs')
    gifts = [(b, fid) for b in blocks
             for fid in re.findall(r'^(F\d+):', b['text'], re.M)]
    gift, fid = one(gifts, 'supplied gift')
    hid = one(re.findall(r'Household (H\d+);', gift['text']), 'gift household')
    gid = one(re.findall(r'person (G\d+)\.', gift['text']), 'gift person')
    group = one(re.findall(r'Group (GG\d+)\.', gift['text']), 'gift group')
    household, recorded_hid = one([(b, h) for b in blocks for h in
        re.findall(r'^(H\d+):', b['text'], re.M)], 'household identity')
    if recorded_hid != hid:
        raise ValueError('household mismatch')
    one(re.findall(r'^' + re.escape(gid) + r':', household['text'], re.M),
        'person identity')
    # Count declared records before parsing; malformed extras must not disappear.
    one([(b, record) for b in blocks for record in re.findall(
        r'^TY\d+:', b['text'], re.M)], 'declared correspondence record')
    notes = [(b, match) for b in blocks for match in re.finditer(
        r'^(TY\d+): gift (F\d+), group (GG\d+),', b['text'], re.M)
        ]
    note, match = one(notes, 'matching correspondence')
    if match.group(2) != fid:
        raise ValueError('gift mismatch')
    if match.group(3) != group:
        raise ValueError('group mismatch')
    return {'gift_and_card_credit': gift['id'], 'matching_person': household['id'],
            'matching_correspondence': note['id']}


def render(planner, packet, model_bindings, judgments):
    """Reuse original guarded arithmetic and meaning; retain wrong model choices."""
    baseline = planner.render(packet, model_bindings, judgments)
    try:
        bound = bind(packet['blocks'])
    except (KeyError, ValueError) as error:
        result = copy.deepcopy(baseline)
        result['calculations'] = {}
        result['answer'] = ['No joined work item: ' + str(error) + '.']
        result['structural_binding_error'] = str(error)
    else:
        result = planner.render(packet, bound, judgments)
        result['software_record_bindings'] = bound
        result['model_role_assignments'] = copy.deepcopy(model_bindings)
        for support in result['copied_support']:
            support['binding_owner'] = 'software structural record grammar'
    result['baseline_answer'] = baseline['answer']
    result['baseline_calculation_error'] = baseline.get('calculation_error')
    result['baseline_model_role_assignments'] = copy.deepcopy(model_bindings)
    result['qualification'] = 'OFFLINE_EXPOSED_OUTPUT_REASSEMBLY_NOT_NEW_MODEL_RUN'
    return result
