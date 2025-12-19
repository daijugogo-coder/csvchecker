#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit版 CSVファイルチェッカー（cp932対応・LF改行）

主チェック:
  - 25列目 == "Z00014" かつ 38列目 が "3000/5000" 以外 → NG

日付チェック（業務仕様）:
  - 9列目（必須）: yyyy/mm/dd hh:mm:ss が無い/不正 → エラー
  - 16列目: 無視
  - 17列目:
      - 空/NULL → 警告（要確認）
      - 日付形式でない → 警告（要確認）
      - 日付形式なら 9列目と yyyy/mm/dd が一致するか確認
          - 不一致 → 警告（要確認）
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, date
from io import StringIO
from typing import List, Optional, Tuple

import streamlit as st

# ----------------------------
# Constants / rules
# ----------------------------
TARGET_COL_25 = 24
TARGET_COL_38 = 37

DATE_COL_9 = 8     # 9列目（必須）
DATE_COL_16 = 15   # 16列目（無視）
DATE_COL_17 = 16   # 17列目（確認対象）

DATE_TIME_RE = re.compile(r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}$")
MAX_PHYSICAL_LINES = 50_000  # UIには出さない（内部上限）

# （豆知識は任意機能）
SOLAR_TERMS_2025 = [
    (date(2025, 1, 5), "小寒"), (date(2025, 1, 20), "大寒"),
    (date(2025, 2, 3), "立春"), (date(2025, 2, 18), "雨水"),
    (date(2025, 3, 5), "啓蟄"), (date(2025, 3, 20), "春分"),
    (date(2025, 4, 4), "清明"), (date(2025, 4, 20), "穀雨"),
    (date(2025, 5, 5), "立夏"), (date(2025, 5, 21), "小満"),
    (date(2025, 6, 5), "芒種"), (date(2025, 6, 21), "夏至"),
    (date(2025, 7, 7), "小暑"), (date(2025, 7, 22), "大暑"),
    (date(2025, 8, 7), "立秋"), (date(2025, 8, 23), "処暑"),
    (date(2025, 9, 7), "白露"), (date(2025, 9, 23), "秋分"),
    (date(2025, 10, 8), "寒露"), (date(2025, 10, 23), "霜降"),
    (date(2025, 11, 7), "立冬"), (date(2025, 11, 22), "小雪"),
    (date(2025, 12, 7), "大雪"), (date(2025, 12, 22), "冬至"),
]
ANNIVERSARIES = {
    (1, 1): ["元日"], (2, 14): ["バレンタインデー"], (3, 3): ["ひな祭り"],
    (4, 29): ["昭和の日"], (5, 5): ["こどもの日"], (7, 7): ["七夕"],
    (11, 3): ["文化の日"], (12, 17): ["飛行機の日（ライト兄弟が初飛行）"],
}


# ----------------------------
# Data models
# ----------------------------
@dataclass
class ErrorDetail:
    row: int  # 物理行（開始行）
    store_name: str
    slip_number: str
    col_38: str


@dataclass
class DateIssue:
    record_no: int
    start_physical_line: int
    severity: str   # "ERROR" or "WARN"
    issue_type: str
    col9: str
    col17: str
    note: str


@dataclass
class DateSummary:
    total_checked_cells: int
    count_col9_ok: int
    count_col17_ok: int
    count_warn: int
    count_error: int
    issues: List[DateIssue]


# ----------------------------
# Helper functions
# ----------------------------
def approximate_rokuyo(g_date: date) -> str:
    idx = (g_date.month + g_date.day) % 6
    mapping = ["先勝", "友引", "先負", "仏滅", "大安", "赤口"]
    return mapping[idx]


def current_solar_term_2025(g_date: date) -> str:
    last = SOLAR_TERMS_2025[0][1]
    for start, name in SOLAR_TERMS_2025:
        if g_date >= start:
            last = name
        else:
            break
    return last


def friendly_today_info() -> str:
    today = datetime.now()
    g_date = today.date()
    dow = ["月", "火", "水", "木", "金", "土", "日"][g_date.weekday()]
    rokuyo = approximate_rokuyo(g_date)
    term = current_solar_term_2025(g_date)
    anns = ANNIVERSARIES.get((g_date.month, g_date.day), [])
    anns_str = ("・" + "・".join(anns)) if anns else "（記念日の情報は参考辞書に未登録）"
    return (
        f"今日は {g_date.strftime('%Y/%m/%d')}（{dow}）です。\n"
        f"六曜（参考値）: {rokuyo}\n"
        f"二十四節気（近似）: {term}\n"
        f"記念日: {anns_str}\n"
    )


def csv_reader_from_text(csv_text: str) -> csv.reader:
    # セル内LFを含むCSVでも列ズレしない前提（重要）
    return csv.reader(StringIO(csv_text, newline=""))


def parse_dt_str(s: str) -> Optional[datetime]:
    t = s.strip()
    if not DATE_TIME_RE.match(t):
        return None
    try:
        return datetime.strptime(t, "%Y/%m/%d %H:%M:%S")
    except Exception:
        return None


def build_error_csv_bytes(details: List[ErrorDetail]) -> bytes:
    buf = StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["行番号(物理行)", "店舗名", "伝票番号", "金額(38列目)"])
    for d in details:
        w.writerow([d.row, d.store_name, d.slip_number, d.col_38])
    return buf.getvalue().encode("utf-8")


def build_date_issue_csv_bytes(issues: List[DateIssue]) -> bytes:
    buf = StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["レコード番号", "開始物理行(参考)", "重要度", "種別", "9列目", "17列目", "補足"])
    for it in issues:
        w.writerow([it.record_no, it.start_physical_line, it.severity, it.issue_type, it.col9, it.col17, it.note])
    return buf.getvalue().encode("utf-8")


# ----------------------------
# Core logic (1 pass)
# ----------------------------
def check_and_analyze(csv_text: str) -> Tuple[bool, List[ErrorDetail], int, int, DateSummary]:
    error_details: List[ErrorDetail] = []
    total_data_records = 0
    total_physical_lines = 0

    total_checked_cells = 0
    count_col9_ok = 0
    count_col17_ok = 0
    count_warn = 0
    count_error = 0
    issues: List[DateIssue] = []

    reader = csv_reader_from_text(csv_text)
    prev_end_line = 0

    for record_no, row in enumerate(reader, start=1):
        # 物理行の管理（ヘッダーでも必ず更新する）
        start_physical_line = prev_end_line + 1
        end_physical_line = reader.line_num
        prev_end_line = end_physical_line
        total_physical_lines = end_physical_line

        if total_physical_lines > MAX_PHYSICAL_LINES:
            raise ValueError("ファイルが大きすぎるため処理できませんでした。（上限超過）")

        # ★ 1行目はヘッダーなので完全に無視
        if record_no == 1:
            continue

        # ここから下はデータ行のみ
        total_data_records += 1
        data_record_no = total_data_records  # ヘッダー除外の連番で表示したいならこれ

        # ----------------------------
        # NGチェック（25/38列）
        # ----------------------------
        if len(row) >= (TARGET_COL_38 + 1):
            col_3 = row[2].strip() if len(row) > 2 else ""
            col_11 = row[10].strip() if len(row) > 10 else ""
            col_25 = row[TARGET_COL_25].strip()
            col_38 = row[TARGET_COL_38].strip()

            if col_25 == "Z00014" and col_38 not in {"3000", "5000"}:
                error_details.append(
                    ErrorDetail(
                        row=start_physical_line,
                        store_name=col_3,
                        slip_number=col_11,
                        col_38=col_38,
                    )
                )

        # ----------------------------
        # 日付チェック（9列目必須、17列目は警告基準）
        # ----------------------------
        col9 = row[DATE_COL_9].strip() if len(row) > DATE_COL_9 else ""
        col17 = row[DATE_COL_17].strip() if len(row) > DATE_COL_17 else ""

        dt9 = parse_dt_str(col9)
        if dt9 is None:
            count_error += 1
            issues.append(
                DateIssue(
                    record_no=data_record_no,
                    start_physical_line=start_physical_line,
                    severity="ERROR",
                    issue_type="COL9_MISSING_OR_INVALID",
                    col9=col9,
                    col17=col17,
                    note="9列目に yyyy/mm/dd hh:mm:ss が必要です（業務上あり得ないデータ）。",
                )
            )
        else:
            count_col9_ok += 1
            total_checked_cells += 1

        dt17 = parse_dt_str(col17)
        if not col17.strip():
            count_warn += 1
            issues.append(
                DateIssue(
                    record_no=data_record_no,
                    start_physical_line=start_physical_line,
                    severity="WARN",
                    issue_type="COL17_EMPTY",
                    col9=col9,
                    col17=col17,
                    note="17列目が空です（要確認）。NULLの場合もあり得るため人間確認が必要です。",
                )
            )
        elif dt17 is None:
            count_warn += 1
            issues.append(
                DateIssue(
                    record_no=data_record_no,
                    start_physical_line=start_physical_line,
                    severity="WARN",
                    issue_type="COL17_INVALID",
                    col9=col9,
                    col17=col17,
                    note="17列目が日付形式ではありません（要確認）。",
                )
            )
        else:
            count_col17_ok += 1
            total_checked_cells += 1
            if dt9 is not None:
                d9 = dt9.strftime("%Y/%m/%d")
                d17 = dt17.strftime("%Y/%m/%d")
                if d9 != d17:
                    count_warn += 1
                    issues.append(
                        DateIssue(
                            record_no=data_record_no,
                            start_physical_line=start_physical_line,
                            severity="WARN",
                            issue_type="DATE_MISMATCH",
                            col9=col9,
                            col17=col17,
                            note=f"9列目({d9}) と 17列目({d17}) の日付が一致しません（要確認）。",
                        )
                    )

    date_summary = DateSummary(
        total_checked_cells=total_checked_cells,
        count_col9_ok=count_col9_ok,
        count_col17_ok=count_col17_ok,
        count_warn=count_warn,
        count_error=count_error,
        issues=issues,
    )

    # total_records は「データ行数（ヘッダー除外）」で返す
    return (len(error_details) > 0), error_details, total_data_records, total_physical_lines, date_summary


# ----------------------------
# UI helpers (modal-like overlay)
# ----------------------------
def inject_base_css() -> None:
    st.markdown(
        """
<style>
#processing-overlay {
  position: fixed;
  z-index: 99999;
  inset: 0;
  background: rgba(0,0,0,0.45);
  display: flex;
  align-items: center;
  justify-content: center;
}
.processing-card {
  background: white;
  padding: 18px 22px;
  border-radius: 14px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.25);
  display: flex;
  gap: 12px;
  align-items: center;
  min-width: 260px;
}
.spinner {
  width: 22px;
  height: 22px;
  border: 3px solid #ddd;
  border-top: 3px solid #555;
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.processing-text { font-size: 16px; font-weight: 600; }
.small-note { font-size: 12px; color: #666; margin-top: 2px; }
</style>
        """,
        unsafe_allow_html=True,
    )


def show_processing_overlay(placeholder: st.delta_generator.DeltaGenerator) -> None:
    placeholder.markdown(
        """
<div id="processing-overlay">
  <div class="processing-card">
    <div class="spinner"></div>
    <div>
      <div class="processing-text">確認中</div>
      <div class="small-note">しばらくお待ちください…</div>
    </div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def hide_processing_overlay(placeholder: st.delta_generator.DeltaGenerator) -> None:
    placeholder.empty()


# ----------------------------
# Streamlit App
# ----------------------------
def main() -> None:
    st.set_page_config(page_title="CSVチェッカー", page_icon="✅", layout="centered")
    inject_base_css()

    st.title("CSVチェッカー")

    st.markdown(
        """
- CSVファイルをドラッグ&ドロップで置いてください（置いたら自動でチェックします）
- 通信は暗号化されます（HTTPS）
- アップロードされたファイルはサーバに保存せず、メモリ上で処理します
- ファイルが大きすぎる場合は処理できません
        """.strip()
    )

    uploaded = st.file_uploader(
        "CSVファイルを選択（ドラッグ&ドロップ可）",
        type=["csv"],
        accept_multiple_files=False,
    )

    overlay_ph = st.empty()

    if uploaded is None:
        st.info("CSVを置くと自動でチェックを開始します。")
        return

    raw = uploaded.getvalue()
    if not raw:
        st.info("アップロード処理中です。完了後に自動で検査します…")
        return

    file_sig = (uploaded.name, len(raw), hashlib.sha256(raw).hexdigest())
    if st.session_state.get("last_file_sig") == file_sig:
        cached = st.session_state.get("last_result")
        if cached:
            render_result(**cached)
            return
    st.session_state["last_file_sig"] = file_sig

    try:
        show_processing_overlay(overlay_ph)

        try:
            text = raw.decode("cp932")
        except UnicodeDecodeError as e:
            raise ValueError("cp932としてデコードできませんでした。文字コードが違います。") from e

        error_found, error_details, total_records, total_physical_lines, date_summary = check_and_analyze(text)

        st.session_state["last_result"] = dict(
            error_found=error_found,
            error_details=error_details,
            total_records=total_records,
            total_physical_lines=total_physical_lines,  # 表示しない（内部用）
            date_summary=date_summary,
            uploaded_name=uploaded.name,
        )

    except Exception as e:
        hide_processing_overlay(overlay_ph)
        st.error("エラー：期待している形式のCSVとして処理できませんでした。")
        st.exception(e)
        return
    finally:
        hide_processing_overlay(overlay_ph)

    render_result(**st.session_state["last_result"])


def render_result(
    *,
    error_found: bool,
    error_details: List[ErrorDetail],
    total_records: int,
    total_physical_lines: int,  # 表示しない
    date_summary: DateSummary,
    uploaded_name: str,
) -> None:
    st.subheader("判定結果")
    st.caption(f"読み込みレコード数(ヘッダー除く): {total_records} 件")

    # --- NGチェック結果 ---
    if not error_found:
        st.success("問題ありません（NG条件に該当する行は見つかりませんでした）")
    else:
        st.error("NGデータがあります。処理を進めずに店舗へ確認を。")
        st.write(f"エラー件数: **{len(error_details)} 件**")

        st.markdown("#### エラー詳細（最大10件）")
        preview = error_details[:10]
        st.table(
            [
                {"行番号(物理行)": d.row, "店舗名": d.store_name, "伝票番号": d.slip_number, "金額(38列目)": d.col_38}
                for d in preview
            ]
        )
        if len(error_details) > 10:
            st.caption(f"…他 {len(error_details) - 10} 件")

        error_csv_bytes = build_error_csv_bytes(error_details)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_stem = uploaded_name.rsplit(".", 1)[0]
        out_name = f"{safe_stem}_error_{ts}.csv"
        st.download_button(
            label="エラー詳細CSVをダウンロード（UTF-8）",
            data=error_csv_bytes,
            file_name=out_name,
            mime="text/csv",
        )

    # --- 日付チェック結果 ---
    st.subheader("日付チェック（9列目・17列目）")

    ds = date_summary
    st.caption(f"検出件数（箇所）: {ds.total_checked_cells} 件（9列目・17列目のうち日付として成立したもの）")
    st.markdown(
        f"""
- 9列目（日付）OK: **{ds.count_col9_ok} 件**
- 17列目（日付）OK: **{ds.count_col17_ok} 件**
- 日付チェック: エラー **{ds.count_error} 件** / 警告 **{ds.count_warn} 件**
        """.strip()
    )

    if ds.issues:
        hard_errors = [x for x in ds.issues if x.severity == "ERROR"]
        warns = [x for x in ds.issues if x.severity == "WARN"]

        if hard_errors:
            st.error("日付チェックでエラーがあります（9列目が不正）。業務上あり得ないデータです。")

        if warns:
            st.warning("日付チェックで警告があります。人間による確認が必要です。")

        st.markdown("#### 日付チェックの指摘（最大20件）")
        preview = ds.issues[:20]
        st.table(
            [
                {
                    "レコード番号": it.record_no,
                    "開始物理行(参考)": it.start_physical_line,
                    "重要度": it.severity,
                    "種別": it.issue_type,
                    "9列目": it.col9,
                    "17列目": it.col17,
                    "補足": it.note,
                }
                for it in preview
            ]
        )
        if len(ds.issues) > 20:
            st.caption(f"…他 {len(ds.issues) - 20} 件")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_stem = uploaded_name.rsplit(".", 1)[0]
        out_name = f"{safe_stem}_date_issues_{ts}.csv"
        csv_bytes = build_date_issue_csv_bytes(ds.issues)
        st.download_button(
            label="日付チェック指摘一覧CSVをダウンロード（UTF-8）",
            data=csv_bytes,
            file_name=out_name,
            mime="text/csv",
        )
    else:
        st.success("日付チェック上の指摘はありません。")

    with st.expander("今日の豆知識（任意）"):
        st.text(friendly_today_info())


if __name__ == "__main__":
    main()
