"""截关前连续部分补正的合并与裁量。

同一票舱单在截关前会收到多份补正：前一份修正件重，后一份只改箱号。
若每份都按整行替代，后一份会丢掉前一份的修正；若把互不相干的补正
零散拼在一起，又会得到从未申报过的组合。这里的裁决标准是
“能否还原唯一申报依据”：

* 补正只声明本次真正改动的字段，其余字段继承当前已采用的完整版本。
* 每条补正必须紧接当前版本（revision = 当前 + 1）。跳版、回退、在同一
  版本上分叉都整包退回，所以合并结果始终对应唯一一条版本链，
  等价于确实存在过的某一完整申报版本。
* 一个补正包要么整包采用，要么整包退回；退回时保留上一完整版本，
  旧版结果继续作为当前结果，页面不会被半成品覆盖。
* 完全相同的补正包重试复用已生成批次，不重复生成结果。
* 申报汇总随补正一起提交；仅含申报汇总的补正不会改动明细。
* 原始采信行单独留档在 intake_evidence 中，任何时候都能完整追回；
  证据包每次导出都包含它。
"""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import csv
import io
import json

from app.coerce import number
from app.errors import BusinessError

FIELDS = ['id', 'parent', 'packages', 'package_unit', 'net', 'gross',
          'weight_unit', 'hazard', 'un_code', 'container', 'revision']
PATCHABLE = [field for field in FIELDS if field not in ('id', 'revision')]
DECLARATION_FIELDS = ('pieces', 'net_kg', 'gross_kg')


def _text(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def parse_revision(value):
    try:
        revision = number(value)
    except BusinessError:
        raise BusinessError('BAD_REVISION', '补正版本须为正整数')
    if revision < 1 or revision % 1:
        raise BusinessError('BAD_REVISION', '补正版本须为正整数')
    return int(revision)


def _rows_from_csv(text):
    text = '' if text is None else str(text)
    if not text.strip():
        raise BusinessError('EMPTY_CORRECTION', '补正内容为空')
    stream = csv.reader(io.StringIO(text, newline=''), strict=True)
    try:
        header = [cell.strip() for cell in next(stream)]
    except StopIteration:
        raise BusinessError('EMPTY_CORRECTION', '补正内容为空')
    except csv.Error:
        raise BusinessError('BROKEN_CSV', '补正 CSV 无法解析')
    for field in header:
        if field not in FIELDS:
            raise BusinessError('UNKNOWN_FIELD', f'补正字段不存在：{field}')
    rows = []
    try:
        for cells in stream:
            if not cells or not any(cell.strip() for cell in cells):
                continue
            if len(cells) != len(header):
                raise BusinessError('COLUMN_COUNT', '补正行列数不一致')
            row = {}
            for field, cell in zip(header, cells):
                value = cell.strip()
                if field == 'id':
                    if not value:
                        raise BusinessError('MISSING_ID', '补正行缺少编号')
                    row[field] = value
                elif field == 'revision':
                    if not value:
                        raise BusinessError('MISSING_REVISION', '补正行缺少版本号')
                    row[field] = value
                elif value:
                    # CSV 里的空单元格表示本次不改动该字段，不是清空。
                    row[field] = value
            rows.append(row)
    except csv.Error:
        raise BusinessError('BROKEN_CSV', '补正 CSV 无法解析')
    return rows


def canonical_package(package):
    if not isinstance(package, dict):
        raise BusinessError('BAD_PACKAGE', '补正包须为对象')
    package_id = package.get('package_id')
    if package_id is None or not _text(package_id).strip():
        raise BusinessError('BAD_PACKAGE', '补正包缺少编号')
    rows = package.get('rows')
    if rows is None and 'csv_text' in package:
        rows = _rows_from_csv(package.get('csv_text'))
    declaration = package.get('declaration')
    if declaration is not None:
        if not isinstance(declaration, dict):
            raise BusinessError('BAD_DECLARATION', '申报汇总须为对象')
        declaration = {field: _text(declaration.get(field)) for field in DECLARATION_FIELDS}
        if any(not value for value in declaration.values()):
            raise BusinessError('BAD_DECLARATION', '申报汇总缺少件数或净毛重')
        try:
            for field in DECLARATION_FIELDS:
                number(declaration[field])
        except BusinessError:
            raise BusinessError('BAD_DECLARATION', '申报汇总须为数值')
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise BusinessError('BAD_PACKAGE', '补正行须为列表')
    if not rows and declaration is None:
        raise BusinessError('EMPTY_CORRECTION', '补正包没有行')
    clean_rows = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise BusinessError('BAD_PACKAGE', '补正行须为对象')
        row_id = row.get('id')
        if row_id is None or not _text(row_id).strip():
            raise BusinessError('MISSING_ID', '补正行缺少编号')
        row_id = _text(row_id).strip()
        if row_id in seen:
            raise BusinessError('DUPLICATE_CONFLICT', f'同一补正包重复编号：{row_id}')
        seen.add(row_id)
        clean = {'id': row_id}
        for field, value in row.items():
            if field == 'id':
                continue
            if field not in FIELDS:
                raise BusinessError('UNKNOWN_FIELD', f'补正字段不存在：{field}')
            clean[field] = _text(value)
        if not clean.get('revision'):
            raise BusinessError('MISSING_REVISION', f'补正行缺少版本号：{row_id}')
        parse_revision(clean['revision'])
        clean_rows.append(clean)
    clean_rows.sort(key=lambda item: item['id'])
    return {'package_id': _text(package_id).strip(), 'rows': clean_rows,
            'note': _text(package.get('note')), 'declaration': declaration}


def _looks_like_package(value):
    return isinstance(value, dict) and any(
        key in value for key in ('package_id', 'csv_text', 'rows'))


def canonical_packages(packages):
    if packages is None:
        return []
    if isinstance(packages, dict):
        if 'packages' in packages:
            packages = packages.get('packages')
        elif _looks_like_package(packages):
            packages = [packages]
        else:
            raise BusinessError('BAD_PACKAGE', '缺少补正包')
    if not isinstance(packages, list):
        raise BusinessError('BAD_PACKAGE', '补正包须为列表')
    return [canonical_package(package) for package in packages]


def packages_from_payload(payload):
    if not isinstance(payload, dict):
        raise BusinessError('BAD_PACKAGE', '补正内容须为对象')
    if 'packages' in payload:
        return payload.get('packages')
    if _looks_like_package(payload):
        return [payload]
    raise BusinessError('BAD_PACKAGE', '缺少补正包')


def package_digest(package):
    payload = {'package_id': package['package_id'], 'rows': package['rows'],
               'declaration': package.get('declaration')}
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode()).hexdigest()


def _order_key(package):
    """补正按声明的版本推进，版本相同则保持到达顺序。

    同一组补正包原样重试（含顺序相同）会得到同一条版本链；若两份补正
    在同一版本上分叉，先到者采用、后到者整包退回，不会被静默拼合。
    只带申报汇总的补正代表最终口径，排在全部明细补正之后应用。
    """
    bucket = 1 if (not package['rows'] and package.get('declaration')) else 0
    revisions = [parse_revision(row['revision']) for row in package['rows']]
    return (bucket, min(revisions) if revisions else 0)


def dedupe_packages(packages):
    """按包内容去重并稳定排序；同编号不同内容保留，交给合并阶段退回。"""
    result = []
    seen = set()
    for package in packages:
        identity = (package['package_id'], package_digest(package))
        if identity in seen:
            continue
        seen.add(identity)
        result.append(package)
    return sorted(result, key=_order_key)


def _normalize(row, context):
    from app.modules.packaging.rules import normalize
    return normalize(row, context)


def _metrics(normalized):
    return {'pieces': normalized['pieces'], 'net_kg': normalized['net_kg'],
            'gross_kg': normalized['gross_kg']}


def _subtree(root, children):
    seen = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(children.get(node, []))
    return seen


def _fallback_graph(records):
    """部分模块（尚未执行拆并编组）只按上级单号还原主单与子树。"""
    children = {}
    roots = []
    ids = {record['id'] for record in records}
    for record in records:
        parent = _text(record.get('parent')).strip()
        if parent and parent in ids:
            children.setdefault(parent, []).append(record['id'])
        elif not parent:
            roots.append(record['id'])
    return {'roots': sorted(roots), 'children': children, 'errors': [],
            'node_count': len(records)}


def _apply_one(package, current, context):
    """在副本上试算一个补正包，任何一行失败都整包退回。"""
    trial = deepcopy(current)
    changes = []
    for patch in package['rows']:
        row_id = patch['id']
        target = trial.get(row_id)
        if target is None:
            return None, {'id': row_id, 'code': 'UNKNOWN_REFERENCE',
                          'detail': f'补正目标不在已采信记录中：{row_id}'}
        current_revision = parse_revision(target.get('revision'))
        try:
            next_revision = parse_revision(patch['revision'])
        except BusinessError as error:
            return None, {'id': row_id, 'code': error.code, 'detail': error.message}
        if next_revision <= current_revision:
            return None, {'id': row_id, 'code': 'STALE_REVISION',
                          'detail': f'{row_id} 补正版本 {next_revision} 不晚于当前版本 {current_revision}'}
        if next_revision != current_revision + 1:
            return None, {'id': row_id, 'code': 'REVISION_GAP',
                          'detail': f'{row_id} 补正版本须为 {current_revision + 1}，实际 {next_revision}'}
        changed = {}
        for field in PATCHABLE:
            if field not in patch:
                continue
            value = patch[field]
            if value != _text(target.get(field)):
                changed[field] = {'before': _text(target.get(field)), 'after': value}
        if not changed:
            # 没有实际改动的详细行说明补正与当前版本不一致，不能据此推进版本。
            return None, {'id': row_id, 'code': 'NO_CHANGE',
                          'detail': f'{row_id} 补正包没有实际改动'}
        merged = deepcopy(target)
        for field, values in changed.items():
            merged[field] = values['after']
        merged['revision'] = str(next_revision)
        try:
            before = _metrics(_normalize(target, context))
            after = _metrics(_normalize(merged, context))
        except BusinessError as error:
            return None, {'id': row_id, 'code': 'INVALID_CORRECTION',
                          'detail': f'{row_id} 补正后不可用：{error.message}'}
        trial[row_id] = merged
        changes.append({'id': row_id, 'revision': next_revision,
                        'changed': changed, 'before': before, 'after': after,
                        'base': deepcopy(target)})
    if not changes and not package.get('declaration'):
        return None, {'id': '', 'code': 'NO_CHANGE',
                      'detail': f'{package["package_id"]} 补正包没有实际改动'}
    return trial, changes


def apply_packages(state, packages):
    """把补正包逐包合并进采信后的记录；失败包整包退回并保留旧版本。"""
    packages = dedupe_packages(canonical_packages(packages))
    order = [record['id'] for record in state['records']]
    current = {record['id']: deepcopy(record) for record in state['records']}
    ledger = {'accepted': [], 'rejected': [], 'nodes': {},
              'declaration_base': deepcopy(state['context'].get('declaration')),
              'declaration': deepcopy(state['context'].get('declaration')),
              'declaration_package': None,
              'declaration_changes': []}
    accepted = {}
    for package in packages:
        digest = package_digest(package)
        if package['package_id'] in accepted:
            ledger['rejected'].append({
                'package_id': package['package_id'], 'digest': digest, 'id': '',
                'code': 'PACKAGE_CONFLICT',
                'detail': f'补正包编号已用于不同内容：{package["package_id"]}'})
            continue
        trial, changes = _apply_one(package, current, state['context'])
        if trial is None:
            ledger['rejected'].append({**changes, 'package_id': package['package_id'],
                                       'digest': digest})
            continue
        current = trial
        accepted[package['package_id']] = digest
        ledger['accepted'].append({'package_id': package['package_id'], 'digest': digest,
                                   'note': package['note'], 'row_count': len(package['rows']),
                                   'declaration': deepcopy(package.get('declaration'))})
        if package.get('declaration'):
            # 申报汇总随补正一起更新；后续补正不携带汇总时沿用这一版。
            previous = ledger['declaration'] or {}
            ledger['declaration_changes'].append({
                'package_id': package['package_id'],
                'targets': [row['id'] for row in package['rows']],
                'before': deepcopy(previous),
                'after': deepcopy(package['declaration']),
            })
            ledger['declaration'] = deepcopy(package['declaration'])
            ledger['declaration_package'] = package['package_id']
            state['context']['declaration'] = deepcopy(package['declaration'])
        for change in changes:
            node = ledger['nodes'].setdefault(change['id'], {
                'id': change['id'], 'base': change['base'],
                'current': None, 'revisions': []})
            node['revisions'].append({
                'revision': change['revision'],
                'package_id': package['package_id'],
                'changed': change['changed'],
                'before': change['before'],
                'after': change['after'],
            })
            node['current'] = deepcopy(current[change['id']])
    state['records'] = [current[row_id] for row_id in order]
    state['correction_ledger'] = ledger
    state['correction_packages'] = packages


def snapshot_intake(state):
    """在补正前留档，保证原始采信证据可完整追回。"""
    state['intake_evidence'] = {
        'records': deepcopy(state['records']),
        'quarantine': deepcopy(state['quarantine']),
        'counts': deepcopy(state['counts']),
        'encoding': state.get('encoding'),
    }


def _base_metrics(state):
    base = {}
    evidence = state.get('intake_evidence') or {}
    for row in evidence.get('records', []):
        try:
            base[row['id']] = _metrics(_normalize(row, state['context']))
        except BusinessError:
            continue
    return base


def _decimal(value):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(0)


def _delta(before, after):
    if isinstance(before, int) and isinstance(after, int):
        return after - before
    return str(_decimal(after) - _decimal(before))


def ensure(state):
    """为旧批次补算裁量结果，保证跨版本读取不报错。"""
    if 'corrections' not in state:
        state['corrections'] = adjudicate(state)
    return state['corrections']


def adjudicate(state):
    """逐张主单给出采用的补正来源、件重变化与阻断原因。"""
    ledger = state.get('correction_ledger') or {'accepted': [], 'rejected': [], 'nodes': {},
                                                'declaration': None}
    base = _base_metrics(state)
    current = {record['id']: record for record in state['records']}
    graph = state.get('graph') or _fallback_graph(state['records'])
    children = graph.get('children', {})
    roots = list(graph.get('roots', []))
    weight_by_id = {}
    for check in state.get('weight_checks', []):
        if check.get('code') != 'BALANCED':
            weight_by_id.setdefault(check.get('id'), []).append(check)

    declaration_issues = []
    for field in (state.get('balance') or {}).get('declaration_differences', []):
        declaration_issues.append({'code': 'DECLARATION_MISMATCH', 'id': '',
                                   'detail': f'主单合计与申报汇总 {field} 不一致'})
    if (state.get('balance') or {}).get('row_balanced') is False:
        declaration_issues.append({'code': 'ROW_UNBALANCED', 'id': '',
                                   'detail': '采信行未能守恒，存在未归属行'})

    root_sets = {root: _subtree(root, children) for root in roots}
    covered = set().union(*root_sets.values()) if root_sets else set()
    blockers_global_without_declaration = []
    for error in graph.get('errors', []):
        nodes = {error.get('id', '')} | set(error.get('path', []))
        if nodes & covered:
            continue
        # 缺父级、依赖环这类无法归属任一主单的问题属于全票阻断。
        blockers_global_without_declaration.append(
            {'code': 'UNATTACHED_' + error.get('code', 'GRAPH'), 'id': error.get('id', ''),
             'detail': '未归属任一主单：' + ' -> '.join(error.get('path', []))})
    unattached_rejections = []
    for rejection in ledger.get('rejected', []):
        target = rejection.get('id', '')
        if target and any(target in ids for ids in root_sets.values()):
            continue
        unattached_rejections.append(
            {'code': 'CORRECTION_' + rejection['code'], 'id': target,
             'detail': f'{rejection.get("package_id", "")}：{rejection.get("detail", "")}'})

    rows = []
    for root in roots:
        ids = root_sets[root]
        blockers = []
        corrected_here = any(node_id in ledger['nodes'] for node_id in ids)
        if corrected_here or not ledger['nodes']:
            # 申报汇总差异归到实际被补正的主单；没有补正时视为全票问题。
            blockers.extend(declaration_issues)
        blockers.extend(unattached_rejections)
        blockers.extend(blockers_global_without_declaration)
        for node_id in sorted(ids):
            for check in weight_by_id.get(node_id, []):
                blockers.append({'code': 'WEIGHT_' + check['field'].upper(), 'id': node_id,
                                 'detail': f'{check["field"]} 申报 {check["declared"]}，子单合计 {check["children_sum"]}'})
        for error in graph.get('errors', []):
            nodes = {error.get('id', '')} | set(error.get('path', []))
            if nodes & ids:
                blockers.append({'code': 'GRAPH_' + error['code'], 'id': error.get('id', ''),
                                 'detail': ' -> '.join(error.get('path', []))})
        for issue in state.get('hazard_issues', []):
            hit = issue.get('id') in ids
            if not hit and issue.get('code') == 'INCOMPATIBLE':
                hit = any(current.get(node_id, {}).get('container') == issue.get('id')
                          for node_id in ids)
            if hit:
                blockers.append({'code': 'HAZARD_' + issue['code'], 'id': issue.get('id', ''),
                                 'detail': issue.get('classes', '')})
        rejected_here = [item for item in ledger.get('rejected', []) if item.get('id') in ids]
        for rejection in rejected_here:
            blockers.append({'code': 'CORRECTION_' + rejection['code'], 'id': rejection.get('id', ''),
                             'detail': f'{rejection.get("package_id", "")}：{rejection.get("detail", "")}'})

        sources = []
        revisions = []
        for node_id in sorted(ids):
            node = ledger['nodes'].get(node_id)
            if not node:
                continue
            for revision in node['revisions']:
                if revision['package_id'] not in sources:
                    sources.append(revision['package_id'])
                revisions.append({'id': node_id, **deepcopy(revision)})
        revisions.sort(key=lambda item: (item['revision'], item['id']))
        declaration_updates = []
        for update in ledger.get('declaration_changes', []):
            targets = update.get('targets') or []
            if targets and not (set(targets) & ids):
                continue
            if update['package_id'] not in sources:
                sources.append(update['package_id'])
            declaration_updates.append(deepcopy(update))

        root_current = current.get(root)
        root_base = base.get(root)

        def current_value(field, fallback='0'):
            return root_current[field] if root_current else fallback

        def base_value(field, fallback='0'):
            return root_base[field] if root_base else fallback

        pieces = {'base': int(base_value('pieces', 0)),
                  'current': int(current_value('pieces', 0))}
        pieces['delta'] = pieces['current'] - pieces['base']
        net = {'base': str(base_value('net_kg', '0')),
               'current': str(current_value('net_kg', '0'))}
        gross = {'base': str(base_value('gross_kg', '0')),
                 'current': str(current_value('gross_kg', '0'))}
        net['delta'] = _delta(net['base'], net['current'])
        gross['delta'] = _delta(gross['base'], gross['current'])

        if rejected_here:
            decision = 'keep'
            basis = '补正越版或分叉，保留上一完整版本'
        elif revisions or declaration_updates:
            decision = 'merge'
            basis = '逐字段合并已确认改动'
        else:
            decision = 'original'
            basis = '原始采信'
        rows.append({
            'id': root,
            'source': '、'.join(sources) if sources else '原始采信',
            'sources': sources,
            'revision': int(root_current['revision']) if root_current else 0,
            'pieces': pieces, 'net_kg': net, 'gross_kg': gross,
            'changes': revisions, 'change_count': len(revisions),
            'declaration_changes': declaration_updates,
            'blockers': blockers, 'consistent': not blockers,
            'decision': decision, 'basis': basis,
        })

    rejected_total = len(ledger.get('rejected', []))
    summary = {
        'packages': len(ledger.get('accepted', [])),
        'rejected_packages': rejected_total,
        'changed_nodes': len(ledger.get('nodes', {})),
        'roots': len(rows),
        'consistent_roots': sum(1 for row in rows if row['consistent']),
        'all_consistent': bool(rows) and all(row['consistent'] for row in rows),
        'basis': ('merge' if any(row['changes'] or row['declaration_changes'] for row in rows)
                  else 'original'),
        'declaration_package': ledger.get('declaration_package'),
    }
    return {'accepted': deepcopy(ledger.get('accepted', [])),
            'rejected': deepcopy(ledger.get('rejected', [])),
            'nodes': deepcopy(ledger.get('nodes', {})),
            'declaration': deepcopy(ledger.get('declaration')),
            'declaration_base': deepcopy(ledger.get('declaration_base')),
            'declaration_changes': deepcopy(ledger.get('declaration_changes', [])),
            'roots': rows, 'summary': summary}
