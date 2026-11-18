from copy import deepcopy

import pytest

from app.engine import evaluate
from app.errors import BusinessError


def package(pid, rows=None, declaration=None):
    value = {'package_id': pid, 'rows': rows or []}
    if declaration is not None:
        value['declaration'] = declaration
    return value


def row(node, revision, **fields):
    return {'id': node, 'revision': str(revision), **fields}


def clean_with(packages):
    return evaluate({'dataset': 'clean', 'corrections': packages})


def root(state, node='M001'):
    return next(item for item in state['corrections']['roots'] if item['id'] == node)


def weight_fix(revision):
    """把 M001-P1-1 毛重从 110 改到 120，并逐级补齐上级与申报汇总。"""
    return package(
        'W1',
        [row('M001-P1-1', revision, gross='0.12'),
         row('M001-P1', revision, gross='230'),
         row('M001', revision, gross='450')],
        {'pieces': 240, 'net_kg': '2400', 'gross_kg': '2650'})


def test_sequential_partial_corrections_merge_not_replace():
    """前一份修件重、后一份只改箱号：两项改动都要保留。"""
    state = clean_with([
        weight_fix(2),
        package('B1', [row('M001-P1-1', 3, container='C777'),
                       row('M001-P1', 3, container='C777'),
                       row('M001', 3, container='C777')]),
    ])
    node = state['corrections']['nodes']['M001-P1-1']
    assert node['current']['gross'] == '0.12'
    assert node['current']['container'] == 'C777'
    assert node['current']['revision'] == '3'
    assert [item['revision'] for item in node['revisions']] == [2, 3]
    assert root(state)['source'] == 'W1、B1'
    assert state['archive']['status'] == '可封存'


def test_merge_keeps_prior_weight_when_later_package_only_changes_container():
    state = clean_with([
        weight_fix(2),
        package('B1', [row('M001', 3, container='C123')]),
    ])
    node = state['corrections']['nodes']['M001']
    assert node['current']['gross'] == '450'
    assert node['current']['container'] == 'C123'
    assert root(state)['gross_kg']['current'] == '450'
    assert root(state)['gross_kg']['delta'] == '10'


def test_weight_change_without_declaration_blocks_manifest():
    state = clean_with([
        package('W1', [row('M001-P1-1', 2, gross='0.12'),
                       row('M001-P1', 2, gross='230'),
                       row('M001', 2, gross='450')]),
    ])
    assert state['archive']['status'] == '待处理'
    assert root(state)['consistent'] is False
    codes = [item['code'] for item in root(state)['blockers']]
    assert 'DECLARATION_MISMATCH' in codes
    assert root(state, 'M002')['consistent'] is True
    assert state['corrections']['summary']['consistent_roots'] == 5


def test_declaration_package_keeps_batch_sealable():
    state = clean_with([weight_fix(2)])
    assert state['archive']['status'] == '可封存'
    assert state['balance']['gross_kg'] == '2650'
    assert state['balance']['declaration_differences'] == []


def test_revision_gap_rejected_and_previous_version_kept():
    state = clean_with([weight_fix(5)])
    assert state['corrections']['rejected'][0]['code'] == 'REVISION_GAP'
    assert 'M001' not in state['corrections']['nodes']
    kept = next(record for record in state['records'] if record['id'] == 'M001')
    assert kept['gross'] == '440'


def test_branching_same_revision_rejected_as_second_package():
    """同一版本上分叉的两份补正不能拼成从未申报过的组合。"""
    state = clean_with([
        weight_fix(2),
        package('A2', [row('M001', 2, container='C999')]),
    ])
    assert [item['code'] for item in state['corrections']['rejected']] == ['STALE_REVISION']
    node = state['corrections']['nodes']['M001']
    assert node['current']['gross'] == '450'
    assert node['current']['container'] == 'C001'


def test_rejected_package_restores_previous_full_version():
    state = clean_with([
        weight_fix(2),
        package('A2', [row('M001', 2, gross='460')]),
    ])
    record = next(item for item in state['records'] if item['id'] == 'M001')
    assert record['gross'] == '450'
    assert record['revision'] == 2
    assert root(state)['decision'] == 'keep'
    # 被退回的补正说明申报依据仍有争议，旧版结果保留但不能封存。
    assert state['archive']['status'] == '待处理'
    codes = [item['code'] for item in root(state)['blockers']]
    assert 'CORRECTION_STALE_REVISION' in codes
    assert root(state, 'M002')['consistent'] is True


def test_duplicate_retry_of_same_package_is_idempotent():
    body = weight_fix(2)
    first = clean_with([body])
    second = clean_with([deepcopy(body), deepcopy(body)])
    assert first['manifest']['run_id'] == second['manifest']['run_id']
    assert len(second['corrections']['accepted']) == 1
    assert second['corrections']['summary']['changed_nodes'] == 3


def test_package_order_does_not_change_run_id():
    weight = weight_fix(2)
    box = package('B1', [row('M001', 3, container='C123')])
    forward = clean_with([weight, box])
    backward = clean_with([deepcopy(box), deepcopy(weight)])
    assert forward['manifest']['run_id'] == backward['manifest']['run_id']


def test_unknown_target_rejected_whole_package():
    state = clean_with([
        package('X1', [row('M001', 2, container='C2'), row('NOPE', 2, container='C3')]),
    ])
    assert state['corrections']['rejected'][0]['code'] == 'UNKNOWN_REFERENCE'
    record = next(item for item in state['records'] if item['id'] == 'M001')
    assert record['container'] == 'C001'


def test_invalid_correction_keeps_old_value():
    state = clean_with([package('W1', [row('M001', 2, gross='1')])])
    assert state['corrections']['rejected'][0]['code'] == 'INVALID_CORRECTION'
    record = next(item for item in state['records'] if item['id'] == 'M001')
    assert record['gross'] == '440'


def test_no_change_package_rejected():
    state = clean_with([package('N1', [row('M001', 2, gross='440')])])
    assert state['corrections']['rejected'][0]['code'] == 'NO_CHANGE'


def test_csv_patch_blank_cells_do_not_clear_fields():
    text = 'id,revision,container\nM001-P1-1,2,C777\n'
    state = clean_with([{'package_id': 'CSV1', 'csv_text': text}])
    node = state['corrections']['nodes']['M001-P1-1']
    assert node['current']['container'] == 'C777'
    assert node['current']['gross'] == '0.11'


def test_original_intake_evidence_preserved_after_correction():
    state = clean_with([package('B1', [row('M001', 2, container='C777')])])
    evidence = state['intake_evidence']
    original = next(item for item in evidence['records'] if item['id'] == 'M001')
    assert original['container'] == 'C001'
    assert len(evidence['records']) == 42
    assert evidence['counts']['input'] == 42


def test_root_rows_report_sources_and_changes():
    state = clean_with([weight_fix(2),
                        package('B1', [row('M001', 3, container='C777')])])
    item = root(state)
    assert item['id'] == 'M001'
    assert item['sources'] == ['W1', 'B1']
    assert item['revision'] == 3
    assert item['gross_kg']['delta'] == '10'
    assert item['change_count'] == 4
    assert [entry['package_id'] for entry in item['changes']] == ['W1', 'W1', 'W1', 'B1']
    untouched = root(state, 'M002')
    assert untouched['source'] == '原始采信'
    assert untouched['change_count'] == 0
    assert untouched['consistent'] is True


def test_declaration_only_package_does_not_touch_rows():
    state = clean_with([package('D1', declaration={'pieces': 240, 'net_kg': '2400',
                                                   'gross_kg': '2640'})])
    assert state['corrections']['summary']['changed_nodes'] == 0
    assert state['archive']['status'] == '可封存'
    assert state['balance']['declaration_differences'] == []


def test_declaration_only_package_blocks_when_inconsistent():
    state = clean_with([package('D1', declaration={'pieces': 241, 'net_kg': '2400',
                                                   'gross_kg': '2640'})])
    assert state['archive']['status'] == '待处理'
    assert state['balance']['declaration_differences'] == ['pieces']
    assert any(item['code'] == 'DECLARATION_MISMATCH'
               for item in root(state)['blockers'])


def test_unknown_field_in_package_raises():
    with pytest.raises(BusinessError) as error:
        clean_with([package('X1', [{'id': 'M001', 'revision': '2', 'colour': 'red'}])])
    assert error.value.code == 'UNKNOWN_FIELD'


def test_bad_revision_in_package_raises():
    with pytest.raises(BusinessError) as error:
        clean_with([package('X1', [{'id': 'M001', 'revision': 'x'}])])
    assert error.value.code == 'BAD_REVISION'


def test_empty_package_rejected():
    with pytest.raises(BusinessError) as error:
        clean_with([{'package_id': 'X1', 'rows': []}])
    assert error.value.code == 'EMPTY_CORRECTION'


def test_duplicate_id_inside_package_rejected():
    with pytest.raises(BusinessError) as error:
        clean_with([package('X1', [row('M001', 2, gross='440'),
                                   row('M001', 2, container='C9')])])
    assert error.value.code == 'DUPLICATE_CONFLICT'


def test_dirty_sample_with_correction_still_reports_original_blocks():
    state = evaluate({'dataset': 'dirty', 'corrections': [
        package('B1', [row('M001', 2, container='C777')])]})
    assert state['archive']['status'] == '待处理'
    assert state['corrections']['summary']['all_consistent'] is False
    codes = {item['code'] for item in root(state)['blockers']}
    assert 'WEIGHT_GROSS_KG' in codes


def test_no_corrections_keeps_original_behaviour(clean):
    assert clean['corrections']['summary']['basis'] == 'original'
    assert clean['corrections']['accepted'] == []
    assert clean['archive']['status'] == '可封存'
    assert all(item['source'] == '原始采信' for item in clean['corrections']['roots'])
