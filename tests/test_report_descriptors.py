"""PR-4 T-4 — descriptor content + loader (design book v1.1 §5 / §8.3).

验收对照:

  T-4 完整性: config/report_descriptors.json 恰 144 条，且必须覆盖
      dimension(4) × level(4) × band(3) × lang(3) 全交叉，无缺无重
  T-4 值域: dimension / band / lang 全部落在冻结闭集内，level 为 int 0-3
  T-4 Level 0 格式: 36 条 L0 全部以 "Not yet — " / "尚未——" 开头
  T-4 等级名不入 JSON: 等级名（Exemplary / Achieved / Developing / Not Yet
      与中文对）只作代码常量存在，JSON 正文零命中
  T-4 禁用词: IB / ATL / Inquirer / Learner Profile / Proficient / Excellent /
      「未達標」「不及格」在 144 条里零命中（CI 可复跑）
  T-4 载入器硬断言: 缺一条、多一条、域值漂移、L0 前缀漂移、禁用词混入
      → raise DescriptorError（报告生成拒绝启动），绝不返回残缺表
  T-4 查询: descriptor(dim, level, band, lang) 对 144 个 cell 逐一等于 JSON 原文
  T-4 未评分: score_0_3 IS NULL → 不出 descriptor（不得当 Not Yet）；0 是
      真分数 → 出 L0 句

本档只读 config/report_descriptors.json；不改任何文件。
"""

from __future__ import annotations

import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

from auth import report_descriptors as rd  # noqa: E402

CONFIG_PATH = os.path.join(REPO_ROOT, "config", "report_descriptors.json")

ALL_KEYS = [
    (dim, level, band, lang)
    for dim in rd.DIMENSIONS
    for level in rd.LEVELS
    for band in rd.BANDS
    for lang in rd.LANGS
]


def _raw_rows() -> list[dict]:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _raw_text() -> str:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return fh.read()


def _write(tmp_path, rows) -> str:
    path = tmp_path / "report_descriptors.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# T-4.1 completeness + domains
# ---------------------------------------------------------------------------


def test_t4_source_json_is_144_objects_with_exactly_five_keys():
    rows = _raw_rows()
    assert isinstance(rows, list)
    assert len(rows) == 144
    for row in rows:
        assert set(row) == {"dimension", "level", "band", "lang", "text"}
        assert isinstance(row["text"], str) and row["text"].strip() == row["text"]
        assert row["text"] != ""


def test_t4_table_covers_the_full_cross_product_no_gap_no_dupe():
    table = rd.load_descriptors(CONFIG_PATH)
    assert len(table) == 144
    assert set(table) == set(ALL_KEYS)
    for key, text in table.items():
        assert isinstance(text, str) and text

    # the four axes are frozen closed sets (value drift is a hard error)
    assert rd.DIMENSIONS == ("DREAM", "DISCOVER", "DESIGN", "DELIVER")
    assert rd.LEVELS == (0, 1, 2, 3)
    assert rd.BANDS == ("P1-P3", "P4-P6", "S1-S3")
    assert rd.LANGS == ("en", "zh-hk", "zh-cn")
    assert rd.EXPECTED_ROWS == 144

    rows = _raw_rows()
    assert {r["dimension"] for r in rows} == set(rd.DIMENSIONS)
    assert {r["level"] for r in rows} == set(rd.LEVELS)
    assert {r["band"] for r in rows} == set(rd.BANDS)
    assert {r["lang"] for r in rows} == set(rd.LANGS)
    for row in rows:
        assert isinstance(row["level"], int) and not isinstance(row["level"], bool)
        assert row["dimension"] in rd.DIMENSIONS
        assert row["band"] in rd.BANDS
        assert row["lang"] in rd.LANGS
        assert row["level"] in rd.LEVELS


# ---------------------------------------------------------------------------
# T-4.2 level 0 prefix + frozen level names stay out of the JSON
# ---------------------------------------------------------------------------


def test_t4_level0_is_36_cells_all_with_the_frozen_prefix():
    table = rd.load_descriptors(CONFIG_PATH)
    level0 = {k: v for k, v in table.items() if k[1] == 0}
    assert len(level0) == 36
    for (dim, level, band, lang), text in level0.items():
        assert text.startswith(rd.LEVEL0_PREFIX[lang]), f"{dim}/{band}/{lang}: {text!r}"
    assert rd.LEVEL0_PREFIX == {
        "en": "Not yet — ",
        "zh-hk": "尚未——",
        "zh-cn": "尚未——",
    }

    # every Level 0 cell for one dimension, per band/lang
    for lang, prefix in rd.LEVEL0_PREFIX.items():
        for band in rd.BANDS:
            for dim in rd.DIMENSIONS:
                assert table[(dim, 0, band, lang)].startswith(prefix)


def test_t4_level_names_are_code_constants_not_json_content():
    raw = _raw_text()
    assert "LEVEL_NAMES" not in raw
    for names in rd.LEVEL_NAMES.values():
        for name in names:
            assert name not in raw, f"level name {name!r} leaked into the JSON"
    assert rd.LEVEL_NAMES["en"] == ("Not Yet", "Developing", "Achieved", "Exemplary")
    assert rd.LEVEL_NAMES["zh-hk"] == ("尚未開始", "進展中", "達標", "出色")
    assert rd.LEVEL_NAMES["zh-cn"] == ("尚未开始", "进展中", "达标", "出色")


# ---------------------------------------------------------------------------
# T-4.3 forbidden vocabulary (runs in CI exactly as this test)
# ---------------------------------------------------------------------------


def test_t4_forbidden_terms_zero_hits_across_all_144_cells():
    assert rd.FORBIDDEN_TERMS == (
        "IB",
        "ATL",
        "Inquirer",
        "Learner Profile",
        "Proficient",
        "Excellent",
        "未達標",
        "不及格",
    )
    hits = [
        (term, key)
        for key, text in rd.load_descriptors(CONFIG_PATH).items()
        for term in rd.FORBIDDEN_TERMS
        if term in text
    ]
    assert hits == []


def test_t4_languages_are_really_switched_english_never_reused():
    table = rd.load_descriptors(CONFIG_PATH)
    for dim, level, band, _lang in ALL_KEYS:
        en = table[(dim, level, band, "en")]
        hk = table[(dim, level, band, "zh-hk")]
        cn = table[(dim, level, band, "zh-cn")]
        assert en != hk and en != cn
    # zh-HK / zh-CN are verbatim design-book cells; exactly two pairs coincide
    same = [
        (dim, level, band)
        for dim in rd.DIMENSIONS
        for level in rd.LEVELS
        for band in rd.BANDS
        if table[(dim, level, band, "zh-hk")] == table[(dim, level, band, "zh-cn")]
    ]
    assert sorted(same) == [("DELIVER", 2, "P1-P3"), ("DESIGN", 0, "P4-P6")]


# ---------------------------------------------------------------------------
# T-4.4 the loader refuses a partial / drifted table (generation must not start)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate, reason",
    [
        pytest.param(
            lambda rows: rows[:-1], "144", id="missing-one-cell",
        ),
        pytest.param(
            lambda rows: rows + [dict(rows[0])], "144", id="duplicate-cell",
        ),
        pytest.param(
            lambda rows: [{**rows[0], "dimension": "DREAMY"}] + rows[1:],
            "dimension", id="unknown-dimension",
        ),
        pytest.param(
            lambda rows: [{**rows[0], "band": "P7-P9"}] + rows[1:],
            "band", id="unknown-band",
        ),
        pytest.param(
            lambda rows: [{**rows[0], "lang": "fr"}] + rows[1:],
            "lang", id="unknown-lang",
        ),
        pytest.param(
            lambda rows: [{**rows[0], "level": 4}] + rows[1:],
            "level", id="level-out-of-range",
        ),
        pytest.param(
            lambda rows: [{**rows[0], "level": "0"}] + rows[1:],
            "level", id="level-not-an-int",
        ),
        pytest.param(
            lambda rows: [{**rows[0], "text": ""}] + rows[1:],
            "text", id="empty-text",
        ),
        pytest.param(
            lambda rows: [{**rows[0], "text": " " + rows[0]["text"]}] + rows[1:],
            "text", id="untrimmed-text",
        ),
        pytest.param(
            lambda rows: [{**rows[0], "extra": 1}] + rows[1:],
            "keys", id="extra-key",
        ),
    ],
)
def test_t4_loader_raises_on_gap_or_domain_drift(tmp_path, mutate, reason):
    rows = _raw_rows()
    path = _write(tmp_path, mutate(rows))
    with pytest.raises(rd.DescriptorError) as excinfo:
        rd.load_descriptors(path)
    assert reason in str(excinfo.value)


def test_t4_loader_raises_on_level0_prefix_drift(tmp_path):
    rows = _raw_rows()
    level0 = next(r for r in rows if r["level"] == 0)
    idx = rows.index(level0)
    rows[idx] = {**level0, "text": "Not there — no sharing yet."}
    with pytest.raises(rd.DescriptorError) as excinfo:
        rd.load_descriptors(_write(tmp_path, rows))
    assert "level 0" in str(excinfo.value)


def test_t4_loader_raises_when_forbidden_term_is_injected(tmp_path):
    rows = _raw_rows()
    rows[0] = {**rows[0], "text": rows[0]["text"] + " ATL"}
    with pytest.raises(rd.DescriptorError) as excinfo:
        rd.load_descriptors(_write(tmp_path, rows))
    assert "forbidden term" in str(excinfo.value)


def test_t4_loader_raises_on_missing_or_non_array_config(tmp_path):
    with pytest.raises(rd.DescriptorError) as excinfo:
        rd.load_descriptors(str(tmp_path / "nope.json"))
    assert "missing" in str(excinfo.value)

    bad = tmp_path / "bad.json"
    bad.write_text('{"dimension": "DREAM"}', encoding="utf-8")
    with pytest.raises(rd.DescriptorError) as excinfo:
        rd.load_descriptors(str(bad))
    assert "array" in str(excinfo.value)

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(rd.DescriptorError):
        rd.load_descriptors(str(broken))


def test_t4_config_path_defaults_to_the_repo_config_dir():
    assert rd.config_path() == CONFIG_PATH
    assert os.path.isfile(rd.config_path())
    assert rd.CONFIG_RELATIVE_PATH.replace("\\", "/") == "config/report_descriptors.json"


# ---------------------------------------------------------------------------
# T-4.5 lookup
# ---------------------------------------------------------------------------


def test_t4_descriptor_lookup_equals_the_json_cell_for_all_144():
    raw = {(r["dimension"], r["level"], r["band"], r["lang"]): r["text"] for r in _raw_rows()}
    assert len(raw) == 144
    for key in ALL_KEYS:
        assert rd.descriptor(*key) == raw[key]


def test_t4_descriptor_lookup_spot_checks_every_band_and_lang():
    # 4 levels of one dimension inside one (band, lang) family are 4 sentences
    for band in rd.BANDS:
        for lang in rd.LANGS:
            for dim in rd.DIMENSIONS:
                texts = [rd.descriptor(dim, lv, band, lang) for lv in rd.LEVELS]
                assert all(texts)
                assert len(set(texts)) == 4
    # the language axis really switches the sentence
    for band in rd.BANDS:
        for dim in rd.DIMENSIONS:
            for band_lang in (("en", "zh-hk"), ("en", "zh-cn"), ("zh-hk", "zh-cn")):
                if band_lang == ("zh-hk", "zh-cn"):
                    continue  # two verbatim-identical pairs, checked above
                left, right = band_lang
                assert rd.descriptor(dim, 2, band, left) != rd.descriptor(
                    dim, 2, band, right
                )


def test_t4_descriptor_lookup_hard_anchors_two_verbatim_cells():
    """逐字锚点 —— 两句直接来自设计书 v1.1 §5.1/§5.3 表，防表格解析错位。"""
    assert rd.descriptor("DREAM", 2, "P4-P6", "en") == (
        "Comes up with own ideas and, with AI help, picks the one that feels"
        " most original to finish."
    )
    assert rd.descriptor("DREAM", 2, "P4-P6", "zh-hk") == (
        "能提出自己的想法，借助 AI 挑選最具原創性的一個完成作品。"
    )
    assert rd.descriptor("DELIVER", 0, "P1-P3", "en") == "Not yet — no sharing yet."
    assert rd.descriptor("DELIVER", 0, "P1-P3", "zh-cn") == "尚未——未尝试分享。"
    assert rd.descriptor("DESIGN", 0, "P4-P6", "zh-hk") == "尚未——未完成任何作品。"


def test_t4_descriptor_lookup_raises_on_unknown_key_and_caches_the_table():
    with pytest.raises(rd.DescriptorError) as excinfo:
        rd.descriptor("DREAM", 0, "P9-P9", "en")
    assert "P9-P9" in str(excinfo.value)
    with pytest.raises(rd.DescriptorError):
        rd.descriptor("DREAM", 7, "P1-P3", "en")

    table = rd.descriptors()
    assert rd.descriptors() is table
    assert len(table) == 144
    rd.reset_cache()
    assert rd.descriptors() is not table


# ---------------------------------------------------------------------------
# T-4.6 scores -> descriptors (NULL is not a "Not Yet")
# ---------------------------------------------------------------------------


def test_t4_null_score_yields_no_descriptor_at_all():
    scores = {"DREAM": None, "DISCOVER": None, "DESIGN": None, "DELIVER": None}
    assert rd.descriptors_for_scores(scores, "P4-P6", "zh-hk") == {}


def test_t4_zero_is_a_real_score_and_gets_the_level0_sentence():
    scores = {"DREAM": 0, "DISCOVER": None, "DESIGN": 2, "DELIVER": 3}
    picked = rd.descriptors_for_scores(scores, "P1-P3", "en")
    assert set(picked) == {"DREAM", "DESIGN", "DELIVER"}
    assert "DISCOVER" not in picked
    assert picked["DREAM"] == rd.descriptor("DREAM", 0, "P1-P3", "en")
    assert picked["DREAM"].startswith("Not yet — ")
    assert picked["DESIGN"] == rd.descriptor("DESIGN", 2, "P1-P3", "en")
    assert picked["DELIVER"] == rd.descriptor("DELIVER", 3, "P1-P3", "en")


def test_t4_scores_reject_bad_band_lang_and_out_of_range_score():
    with pytest.raises(rd.DescriptorError) as excinfo:
        rd.descriptors_for_scores({"DREAM": 1}, "P7-P9", "en")
    assert "band" in str(excinfo.value)
    with pytest.raises(rd.DescriptorError) as excinfo:
        rd.descriptors_for_scores({"DREAM": 1}, "P1-P3", "zh-tw")
    assert "lang" in str(excinfo.value)
    with pytest.raises(rd.DescriptorError) as excinfo:
        rd.descriptors_for_scores({"DREAM": 4}, "P1-P3", "en")
    assert "score" in str(excinfo.value)
    with pytest.raises(rd.DescriptorError):
        rd.descriptors_for_scores({"DREAM": True}, "P1-P3", "en")


def test_t4_attach_writes_payload_and_uses_the_passed_band_and_lang():
    envelope = {"report": {"student_id": "eeee1111eeee2222"}}
    picked = rd.attach_dimension_descriptors(
        envelope,
        scores={"DREAM": 3, "DISCOVER": None, "DESIGN": 1, "DELIVER": 0},
        age_band="S1-S3",
        lang_code="zh-cn",
    )
    assert envelope["report"]["dimension_descriptors"] == picked
    assert sorted(picked) == ["DELIVER", "DESIGN", "DREAM"]
    assert picked["DELIVER"] == rd.descriptor("DELIVER", 0, "S1-S3", "zh-cn")
    assert picked["DELIVER"].startswith("尚未——")
    assert "DISCOVER" not in picked

    # a later attach replaces, never merges stale sentences from another band
    rd.attach_dimension_descriptors(
        envelope,
        scores={"DREAM": 1, "DISCOVER": None, "DESIGN": None, "DELIVER": None},
        age_band="P1-P3",
        lang_code="zh-hk",
    )
    assert sorted(envelope["report"]["dimension_descriptors"]) == ["DREAM"]
    assert envelope["report"]["dimension_descriptors"]["DREAM"] == rd.descriptor(
        "DREAM", 1, "P1-P3", "zh-hk"
    )


def test_t4_attach_refuses_an_envelope_without_a_report_object():
    with pytest.raises(rd.DescriptorError) as excinfo:
        rd.attach_dimension_descriptors(
            {}, scores={"DREAM": 1}, age_band="P1-P3", lang_code="en"
        )
    assert "report" in str(excinfo.value)
