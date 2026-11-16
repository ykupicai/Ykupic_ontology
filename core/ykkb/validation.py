"""依 schema 驗證 metadata（唯讀），健檢與狀態報表共用同一實作。

證據缺漏是遷移債務，不代填事實、不構成新的查證。
診斷只含欄位名與代碼，不輸出可能敏感的原始值。
（移植自臺南維護者 repo 的 _knowledge_validation.py；另加 schema 3.1 的 office／schema_version 檢查。）
"""
from datetime import date, datetime
from pathlib import Path
import re

from ykkb.metadata import load_yaml, normalize_metadata, valid_official_url

SCHEMA_PATH = Path(__file__).resolve().parents[1] / 'knowledge_schema.yaml'
_VERSION_PATTERN = re.compile(r'\d+(?:\.\d+)?')


def load_schema(path=SCHEMA_PATH):
    schema = load_yaml(Path(path).read_text(encoding='utf-8-sig'))
    for kind in ('case_note', 'legal_note'):
        spec = schema.get(kind)
        if not isinstance(spec, dict) or not isinstance(spec.get('required'), list) or not isinstance(spec.get('enums'), dict):
            raise ValueError(f'Invalid metadata schema section: {kind}')
    return schema


def missing(value):
    return value is None or (isinstance(value, str) and not value.strip())


def strict_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def valid_timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', value):
        return False
    try:
        stamp = datetime.fromisoformat(value)
        return stamp.tzinfo is not None and stamp.utcoffset() is not None
    except ValueError:
        return False


def valid_schema_version(value):
    """schema_version 接受數字（3、3.1）或同形式字串（"3.1"）；布林值不算。"""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value > 0
    return isinstance(value, str) and bool(_VERSION_PATTERN.fullmatch(value.strip()))


def satisfied_by_alternative(field, source, spec):
    """必填欄缺漏時，若 schema 指定的替代欄有值即視為已滿足（如無公開來源之理由）。"""
    alt = spec.get('required_alternatives', {}).get(field)
    return bool(alt) and not missing(source.get(alt))


def validate_metadata(raw, kind, schema=None, path='', office_codes=None, required_office=None):
    """office_codes：辦公室代碼集合；有給時檢查 office 欄位值是否在表內，沒給只檢查型別。
    required_office：office.yaml 設 require_office_field: true 時傳入本辦公室代碼；
    依 schema 的 office_enforcement，缺 office、office 不符、案號未以「代碼-」開頭都算格式錯誤。"""
    schema = schema if schema is not None else load_schema()
    spec = schema[kind]
    meta = normalize_metadata(raw, path)
    required = list(spec['required'])
    state = raw.get('lifecycle' if kind == 'case_note' else 'legal_status')
    if isinstance(state, str):
        required += spec.get('conditional_required', {}).get(state, [])
    required = list(dict.fromkeys(required))
    errors = []

    def error(field, code):
        item = {'field': field, 'code': code}
        if item not in errors:
            errors.append(item)

    # 必填欄的 null 算缺漏；明確填了錯誤的純量／容器型別才算錯誤。
    for field in set(required + spec.get('string_fields', [])):
        value = meta.get(field)
        if not missing(value) and not isinstance(value, str):
            error(field, 'invalid_type')
    for field, allowed in spec['enums'].items():
        value = meta.get(field)
        if not missing(value) and (not isinstance(value, str) or value not in allowed):
            error(field, 'invalid_enum')
    for field in spec.get('date_fields', []):
        if not missing(meta.get(field)) and strict_date(meta[field]) is None:
            error(field, 'invalid_date')
    for field in spec.get('timestamp_fields', []):
        if not missing(meta.get(field)) and not valid_timestamp(meta[field]):
            error(field, 'invalid_timestamp')
    for field in spec.get('version_fields', []):
        if not missing(meta.get(field)) and not valid_schema_version(meta[field]):
            error(field, 'invalid_version')
    if office_codes is not None:
        for field in spec.get('office_fields', []):
            value = meta.get(field)
            if isinstance(value, str) and not missing(value) and value.strip() not in office_codes:
                error(field, 'invalid_office')
    enforcement = spec.get('office_enforcement')
    if required_office and isinstance(enforcement, dict):
        office_field = enforcement.get('office_field', 'office')
        office_value = raw.get(office_field)
        if missing(office_value):
            error(office_field, 'office_required')
        elif isinstance(office_value, str) and office_value.strip() != required_office:
            error(office_field, 'office_mismatch')
        id_field = enforcement.get('id_prefix_field')
        if id_field:
            case_id = raw.get(id_field)
            if not isinstance(case_id, str) or not case_id.strip().startswith(f'{required_office}-'):
                error(id_field, 'id_prefix_mismatch')
    if kind == 'legal_note' and not missing(meta.get('official_url')) and not valid_official_url(meta['official_url']):
        error('official_url', 'invalid_official_url')
    for field, alt in spec.get('required_alternatives', {}).items():
        if missing(raw.get(alt)):
            continue
        if not missing(meta.get(field)):
            error(alt, 'alternative_with_value')  # 有網址就不得再填無網址理由
        if kind == 'legal_note' and raw.get('legal_status') != 'unknown':
            error(alt, 'alternative_requires_unknown_status')
    return {
        'raw_missing': [field for field in required
                        if missing(raw.get(field)) and not satisfied_by_alternative(field, raw, spec)],
        'compatible_missing': [field for field in required
                               if missing(meta.get(field)) and not satisfied_by_alternative(field, meta, spec)],
        'compatibility_fields': sorted(field for field in meta if field not in raw),
        'unresolved': sorted(field for field in spec['enums'] if meta.get(field) == 'unknown'),
        'errors': sorted(errors, key=lambda item: (item['field'], item['code'])),
    }
