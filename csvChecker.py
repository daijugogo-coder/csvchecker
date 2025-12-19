#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit版 CSVファイルチェッカー（cp932対応・LF改行）＋ 日付項目の解析

- 既存ルール: 25列が "Z00014" かつ 38列が "3000/5000" 以外ならNG
- 拡張: yyyy/mm/dd hh:mi:ss 形式の列のみ抽出して、すべて同じ「日」か判定

Web要件:
  - CSVをドラッグ&ドロップで置いたら即検査（ボタン不要）
  - 処理中は「確認中」モーダル風表示＋回転アイコン
  - アップロードファイルはサーバ(ディスク)に残さない（メモリ上のみで処理）
  - NG時はエラー詳細CSVをダウンロード提供（ディスクに書かない）
  - 読み込めるファイルは最大 50,000 物理行まで（超えたらエラー）
  - エラー行番号は「物理行（テキスト上の行）」で返す（セル内改行があっても、エディタ行番号と一致）
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, date
from io import StringIO
from typing import Iterable, List, Optional, Set, Tuple

import streamlit as st

# ----------------------------
# Constants / rules
# ----------------------------
TARGET_COL_25 = 24
TARGET_COL_38 = 37
DATE_TIME_RE = re.compile(r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}$")

MAX_PHYSICAL_LINES = 50_000  # 物理行（エディタで見える行）の上限

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
class DateAnalysis:
    total_matches: int
    unique_days: Set[str]
    first_day_str: Optional[str]


# ----------------------------
# Helper functions (logic)
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


def parse_dates_from_row(row: Iterable[str]) -> List[datetime]:
    dt_list: List[datetime] = []
    for cell in row:
        s = cell.strip()
        if DATE_TIME_RE.match(s):
            try:
                dt_list.append(datetime.strptime(s, "%Y/%m/%d %H:%M:%S"))
            except Exception:
                # 形式に合っていても実際は不正、みたいなケースは無視
                pass
    return dt_list


def csv_reader_from_text(csv_text: str) -> csv.reader:
    # csv module 推奨: newline="" で改行の扱いをcsv側に任せる（セル内改行を含むCSVでも安定）
    return csv.reader(StringIO(csv_text, newline=""))


def analyze_dates_from_text(csv_text: str) -> DateAnalysis:
    """
    csv_text: すでに文字列（cp932デコード済み）
    """
    day_set: Set[str] = set()
    total_matches = 0

    reader = csv_reader_from_text(csv_text)
    for row in reader:
        dts = parse_dates_from_row(row)
        for dt in dts:
            total_matches += 1
            day_set.add(dt.strftime("%Y/%m/%d"))

        # 物理行数の上限（セル内改行ありでも、reader.line_num が物理行）
        if reader.line_num > MAX_PHYSICAL_LINES:
            raise ValueError(f"読み込み行数が上限を超えました（最大 {MAX_PHYSICAL_LINES} 行）。")

    first_day_str = next(iter(day_set)) if day_set else None
    return DateAnalysis(total_matches=total_matches, unique_days=day_set, first_day_str=first_day_str)


def check_csv_from_text(csv_text: str) -> Tuple[bool, List[ErrorDetail], int, int]:
    """
    Returns:
      error_found, error_details, total_records, total_physical_lines
    """
    error_details: List[ErrorDetail] = []
    total_records = 0
    total_physical_lines = 0

    reader = csv_reader_from_text(csv_text)

    # 物理行番号（テキストの行番号）をレコード単位で算出する
    prev_end_line = 0  # 直前レコードが終了した物理行（1-based）

    for record_num, row in enumerate(reader, start=1):
        total_records = record_num

        # このレコードの開始/終了の物理行番号
        start_physical_line = prev_end_line + 1
        end_physical_line = reader.line_num  # ここまで読んだ物理行数（1-based）
        prev_end_line = end_physical_line
        total_physical_lines = end_physical_line

        # 物理行上限チェック
        if total_physical_lines > MAX_PHYSICAL_LINES:
            raise ValueError(f"読み込み行数が上限を超えました（最大 {MAX_PHYSICAL_LINES} 行）。")

        # 38列目に届かない行はスキップ（元コード踏襲）
        if len(row) < (TARGET_COL_38 + 1):
            continue

        col_3 = row[2].strip() if len(row) > 2 else ""
        col_11 = row[10].strip() if len(row) > 10 else ""
        col_25 = row[TARGET_COL_25].strip()
        col_38 = row[TARGET_COL_38].strip()

        if col_25 == "Z00014" and col_38 not in {"3000", "5000"}:
            error_details.append(
                ErrorDetail(
                    row=start_physical_line,  # ★物理行（開始行）を返す
                    store_name=col_3,
                    slip_number=col_11,
                    col_38=col_38,
                )
            )

    return (len(error_details) > 0), error_details, total_records, total_physical_lines


def build_error_csv_bytes(details: List[ErrorDetail]) -> bytes:
    """
    エラー詳細CSVをUTF-8でメモリ上に生成して返す（ディスクに書かない）
    """
    buf = StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["行番号(物理行)", "店舗名", "伝票番号", "金額(38列目)"])
    for d in details:
        w.writerow([d.row, d.store_name, d.slip_number, d.col_38])
    return buf.getvalue().encode("utf-8")


# ----------------------------
# UI helpers (modal-like overlay)
# ----------------------------
def inject_base_css() -> None:
    st.markdown(
        """
<style>
/* Simple full-screen overlay (modal-like) */
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

@keyframes spin {
  to { transform: rotate(360deg); }
}

.processing-text {
  font-size: 16px;
  font-weight: 600;
}
.small-note {
  font-size: 12px;
  color: #666;
  margin-top: 2px;
}
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

    # 要件：静的な箇条書き（＋ 5万行制限）
    st.markdown(
        f"""
- CSVファイルをドラッグドロップで置いてください
- 通信は暗号化しているので盗聴されません
- 処理ファイルはサーバに残さないので安全です
- 読み込めるファイルは最大 **{MAX_PHYSICAL_LINES:,}行（物理行）** までです
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

    # アップロード直後の再実行で 0byte を掴むことがあるので弾く
    raw = uploaded.getvalue()
    if not raw:
        st.info("アップロード処理中です。完了後に自動で検査します…")
        return

    # 同一ファイル連打での“再計算”を防止（再実行に強くする）
    file_sig = (uploaded.name, len(raw), hashlib.sha256(raw).hexdigest())
    if st.session_state.get("last_file_sig") == file_sig:
        cached = st.session_state.get("last_result")
        if cached:
            render_result(**cached)
            return
    st.session_state["last_file_sig"] = file_sig

    try:
        show_processing_overlay(overlay_ph)

        # cp932でデコード（失敗したら即エラー）
        try:
            text = raw.decode("cp932")
        except UnicodeDecodeError as e:
            raise ValueError("cp932としてデコードできませんでした。文字コードが違います。") from e

        # 本処理
        error_found, error_details, total_records, total_physical_lines = check_csv_from_text(text)
        date_info = analyze_dates_from_text(text)

        result_payload = dict(
            error_found=error_found,
            error_details=error_details,
            total_records=total_records,
            total_physical_lines=total_physical_lines,
            date_info=date_info,
            uploaded_name=uploaded.name,
        )
        st.session_state["last_result"] = result_payload

    except Exception as e:
        hide_processing_overlay(overlay_ph)
        st.error("エラー：期待している形式のCSVとして処理できませんでした。")
        # 原因追跡用（本番で邪魔なら str(e) に戻してOK）
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
    total_physical_lines: int,
    date_info: DateAnalysis,
    uploaded_name: str,
) -> None:
    st.subheader("判定結果")

    st.caption(f"読み込みレコード数: {total_records} 件")
    st.caption(f"読み込み物理行数: {total_physical_lines} 行（上限 {MAX_PHYSICAL_LINES:,} 行）")

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

        # エラー詳細CSVをダウンロード（ディスクに書かない）
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

    # 日付チェック
    st.subheader("日付チェック（yyyy/mm/dd hh:mi:ss だけ抽出）")
    if date_info.total_matches == 0:
        st.warning("対象形式の日付は見つかりませんでした。")
    else:
        if len(date_info.unique_days) == 1 and date_info.first_day_str:
            dt = datetime.strptime(date_info.first_day_str, "%Y/%m/%d")
            st.success(f"ファイル内の日付は **{dt.strftime('%m')}月{dt.strftime('%d')}日** でした（すべて同じ日）")
            st.caption(f"検出件数: {date_info.total_matches} 件")
        else:
            days_sorted = sorted(date_info.unique_days)
            example = ", ".join(days_sorted[:5]) + (" ..." if len(days_sorted) > 5 else "")
            st.error("ファイル内の日付は複数日です。")
            st.caption(f"例: {example}")
            st.caption(f"検出件数: {date_info.total_matches} 件 / {len(date_info.unique_days)} 日分")

    with st.expander("今日の豆知識（任意）"):
        st.text(friendly_today_info())


if __name__ == "__main__":
    main()
