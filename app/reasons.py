REASONS = {
    'COLUMN_COUNT':'列数错误', 'MISSING_ID':'编号缺失', 'DUPLICATE_CONFLICT':'重复编号冲突',
    'MISSING_VALUE':'数值缺失', 'BAD_NUMBER':'数值格式错误', 'BAD_TIME':'时间格式错误',
    'BAD_UNIT':'单位不受支持', 'UNKNOWN_REFERENCE':'引用对象不存在', 'INVALID_RANGE':'范围错误',
    'VERSION_CONFLICT':'版本冲突', 'EMPTY_FILE':'空文件', 'BLANK_FILE':'全空行',
    'HEADER_ONLY':'仅有表头', 'STALE_VERSION':'复核版本已更新', 'NOT_FOUND':'批次不存在',
    'BAD_PACKAGE':'补正包无效', 'EMPTY_CORRECTION':'补正包为空', 'BAD_REVISION':'补正版本无效',
    'MISSING_REVISION':'补正缺少版本', 'STALE_REVISION':'补正版本已落后',
    'REVISION_GAP':'补正版本跳跃', 'NO_CHANGE':'补正没有改动', 'PACKAGE_CONFLICT':'补正包编号冲突',
    'INVALID_CORRECTION':'补正后数值不可用', 'UNKNOWN_FIELD':'补正字段不存在',
    'PACKAGE_REJECTED':'补正包被退回', 'NOT_SEALED':'当前主单尚不一致，不能形成封存件',
    'INPUT_SNAPSHOT_MISSING':'批次缺少源快照',
}
def reject(state, record, code, detail):
    state['quarantine'].append({'line':record.get('_line',0),'id':record.get('id',''),
       'code':code,'detail':detail,'raw':{k:v for k,v in record.items() if not k.startswith('_')}})
