# -*- coding: utf-8 -*-
"""ykkb.validation：由臺南 tests/test_knowledge_validation.py 移植（狀態報表相關的不在本 repo），
另加 schema 3.1 的 office／schema_version 檢查。"""
import copy

import pytest

from ykkb import metadata
from ykkb import validation


def test_schema_loads_and_version_documented():
    schema = validation.load_schema()
    assert str(schema["schema_version"]) == "3.1"
    for kind in ("case_note", "legal_note"):
        assert "office" in schema[kind]["optional"]
        assert "schema_version" in schema[kind]["optional"]
        assert "office" not in schema[kind]["required"]


def test_missing_not_automatically_inferred():
    raw = {'type': 'case', 'depth': '文件萃取', 'updated': '2026-09-17'}
    before = copy.deepcopy(raw)
    report = validation.validate_metadata(raw, 'case_note')
    assert raw == before
    assert 'source_depth' in report['raw_missing']
    assert 'source_depth' not in report['compatible_missing']
    assert 'as_of' in report['compatible_missing']
    assert 'lifecycle' in report['compatible_missing']
    assert report['errors'] == []


def test_explicit_null_does_not_fall_back_to_legacy():
    raw = {'type': 'law-digest', 'source_depth': None, 'depth': '文件萃取',
           'verified_at': None, 'verified': '2026-01-01', 'official_url': None,
           'source': 'https://law.moj.gov.tw/'}
    normalized = metadata.normalize_metadata(raw)
    for field in ('source_depth', 'verified_at', 'official_url'):
        assert normalized[field] is None


def test_legacy_law_is_not_verified_again():
    report = validation.validate_metadata({'type': 'law-digest',
        'verified': '2026-01-01（部分條文）', 'source': 'https://law.moj.gov.tw/'}, 'legal_note')
    assert 'legal_status' in report['unresolved']
    assert 'verified_at' in report['raw_missing']
    assert 'verified_at' not in report['compatible_missing']
    assert 'verified_at' in report['compatibility_fields']


def test_all_required_and_conditional_fields_checked():
    report = validation.validate_metadata({'lifecycle': 'active'}, 'case_note')
    for field in ('case_id', 'source', 'updated', 'blocker', 'next_action', 'source_last_modified'):
        assert field in report['raw_missing']
    future = validation.validate_metadata({'type': 'law-digest', 'legal_status': 'future_system'}, 'legal_note')
    assert 'system_scope' in future['raw_missing']
    assert 'applicability_condition' in future['raw_missing']


def test_law_enum_and_type_errors_are_reported():
    report = validation.validate_metadata({'type': 'law-digest', 'legal_status': '已生效',
        'jurisdiction': ['national'], 'verified_at': False}, 'legal_note')
    errors = {(v['field'], v['code']) for v in report['errors']}
    assert ('legal_status', 'invalid_enum') in errors
    assert ('jurisdiction', 'invalid_type') in errors
    assert ('verified_at', 'invalid_date') in errors


@pytest.mark.parametrize("value", ['2026-02-30', '2026-01-01（部分條文）', '20260101', False, ['2026-01-01']])
def test_date_validation_is_strict(value):
    assert validation.strict_date(value) is None


def test_leap_day_ok():
    assert validation.strict_date('2024-02-29') is not None


def test_timestamp_requires_time_and_zone():
    for value in ('2026-01-01', '2026-01-01T01:00:00', '2026-02-30T01:00:00+08:00', 123):
        assert not validation.valid_timestamp(value)
    assert validation.valid_timestamp('2026-01-01T01:00:00+08:00')
    assert validation.valid_timestamp('2026-01-01T01:00:00Z')


def test_official_hostname_not_lookalike_or_userinfo():
    for value in ('https://law.moj.gov.tw.evil.test/', 'https://law.moj.gov.tw@evil.test/',
                  'https://someone@law.moj.gov.tw/', 'not a url', ['url']):
        assert not metadata.valid_official_url(value)
    assert metadata.valid_official_url('https://LAW.MOJ.GOV.TW/LawClass/LawAll.aspx?pcode=X')


def test_bad_legacy_depth_does_not_crash():
    assert 'source_depth' not in metadata.normalize_metadata({'depth': ['文件萃取']})


def test_legacy_url_annotations_not_part_of_url():
    source = 'https://law.moea.gov.tw/LawContent.aspx?id=EXAMPLE（官方來源，舊替代：https://example.gov.tw/）'
    result = metadata.normalize_metadata({'type': 'law-digest', 'source': source})
    assert result['official_url'] == 'https://law.moea.gov.tw/LawContent.aspx?id=EXAMPLE'
    assert result['source'] == source
    assert result['legal_status'] == 'unknown'
    assert 'verified_at' not in result
    assert metadata.legacy_official_url('https://law.gov.tw.evil.test/') is None


def test_validation_reads_schema_not_hardcoded_enums():
    schema = validation.load_schema()
    schema['case_note']['enums']['lifecycle'].append('test_only')
    report = validation.validate_metadata({'lifecycle': 'test_only'}, 'case_note', schema)
    assert report['errors'] == []


# --- 無公開官方來源理由 -------------------------------------------------------------

BASE = {'type': 'guidance-digest', 'jurisdiction': 'national',
        'verified_at': '2026-11-13', 'updated': '2026-11-13'}


def test_reason_satisfies_missing_url_for_unknown_status():
    raw = dict(BASE, legal_status='unknown', official_url_unavailable_reason='2026-11-13 查官網無公開版')
    report = validation.validate_metadata(raw, 'legal_note')
    assert 'official_url' not in report['raw_missing']
    assert 'official_url' not in report['compatible_missing']
    assert report['errors'] == []


def test_without_reason_url_still_missing():
    report = validation.validate_metadata(dict(BASE, legal_status='unknown'), 'legal_note')
    assert 'official_url' in report['raw_missing']


def test_reason_not_allowed_for_known_status():
    raw = dict(BASE, legal_status='effective', official_url_unavailable_reason='x')
    report = validation.validate_metadata(raw, 'legal_note')
    assert {'field': 'official_url_unavailable_reason', 'code': 'alternative_requires_unknown_status'} in report['errors']


def test_reason_not_allowed_alongside_url():
    raw = dict(BASE, legal_status='unknown', official_url_unavailable_reason='x',
               official_url='https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=D0060013')
    report = validation.validate_metadata(raw, 'legal_note')
    assert {'field': 'official_url_unavailable_reason', 'code': 'alternative_with_value'} in report['errors']


# --- 3.1：office／schema_version（選填，有填才檢查） ---------------------------------

def test_office_and_version_missing_is_not_error_or_missing():
    report = validation.validate_metadata({'type': 'case'}, 'case_note', office_codes={'TN', 'HC'})
    assert report['errors'] == []
    assert 'office' not in report['raw_missing'] and 'schema_version' not in report['raw_missing']


@pytest.mark.parametrize("value", [3, 3.1, "3.1", "3"])
def test_valid_schema_version(value):
    report = validation.validate_metadata({'schema_version': value}, 'case_note')
    assert report['errors'] == []


@pytest.mark.parametrize("value", ["v3", "三", True, [3], "3.1.2"])
def test_invalid_schema_version(value):
    report = validation.validate_metadata({'schema_version': value}, 'legal_note')
    assert {'field': 'schema_version', 'code': 'invalid_version'} in report['errors']


def test_office_checked_against_codes_only_when_given():
    raw = {'office': 'KH'}
    assert validation.validate_metadata(raw, 'case_note')['errors'] == []
    report = validation.validate_metadata(raw, 'case_note', office_codes={'TN', 'HC', 'TP'})
    assert {'field': 'office', 'code': 'invalid_office'} in report['errors']
    assert validation.validate_metadata({'office': 'HC'}, 'case_note', office_codes={'HC'})['errors'] == []
    wrong_type = validation.validate_metadata({'office': ['HC']}, 'legal_note', office_codes={'HC'})
    assert {'field': 'office', 'code': 'invalid_type'} in wrong_type['errors']


def test_new_jurisdictions_accepted():
    for value in ('taipei', 'new_taipei', 'hsinchu_city', 'hsinchu_county', 'tainan'):
        report = validation.validate_metadata({'type': 'law-digest', 'jurisdiction': value}, 'legal_note')
        assert report['errors'] == []


# --- require_office_field（office.yaml 開啟時才強制） ---------------------------------

def test_required_office_off_by_default():
    report = validation.validate_metadata({'type': 'case', 'case_id': 'X-1'}, 'case_note')
    assert report['errors'] == []


@pytest.mark.parametrize("raw, expected", [
    ({'case_id': 'HC-2026-001'}, ('office', 'office_required')),
    ({'office': 'TP', 'case_id': 'HC-2026-001'}, ('office', 'office_mismatch')),
    ({'office': 'HC', 'case_id': '2026-001'}, ('case_id', 'id_prefix_mismatch')),
    ({'office': 'HC'}, ('case_id', 'id_prefix_mismatch')),
    ({'office': 'HC', 'case_id': 'HCX-1'}, ('case_id', 'id_prefix_mismatch')),
])
def test_required_office_errors(raw, expected):
    report = validation.validate_metadata(dict(raw, type='case'), 'case_note', required_office='HC')
    assert {'field': expected[0], 'code': expected[1]} in report['errors']


def test_required_office_satisfied():
    raw = {'type': 'case', 'office': 'HC', 'case_id': 'HC-2026-001'}
    assert validation.validate_metadata(raw, 'case_note', office_codes={'HC'}, required_office='HC')['errors'] == []


def test_required_office_not_applied_to_legal_notes():
    report = validation.validate_metadata({'type': 'law-digest'}, 'legal_note', required_office='HC')
    assert report['errors'] == []