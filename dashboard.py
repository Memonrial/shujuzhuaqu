import streamlit as st
import pandas as pd
import plotly.express as px
import re
from supabase import create_client


# =========================
# 页面配置
# =========================
st.set_page_config(
    page_title="MoreTickets 价格看板",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    h1 {
        font-size: 1.6rem !important;
        line-height: 1.3;
    }
    h2, h3 {
        font-size: 1.15rem !important;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.25rem;
    }
    @media (max-width: 768px) {
        .block-container {
            padding-left: 0.55rem;
            padding-right: 0.55rem;
        }
        h1 {
            font-size: 1.3rem !important;
        }
        div[data-testid="stMetricValue"] {
            font-size: 1.05rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True
)


# =========================
# Supabase 连接
# =========================
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# =========================
# 读取数据
# =========================
@st.cache_data(ttl=180)
def load_data():
    """
    从 Supabase 分页读取 ticket_data 表。
    """
    all_rows = []
    start = 0
    batch_size = 1000

    while True:
        res = (
            supabase
            .table("ticket_data")
            .select("*")
            .order("collect_time", desc=False)
            .range(start, start + batch_size - 1)
            .execute()
        )

        rows = res.data or []

        if not rows:
            break

        all_rows.extend(rows)

        if len(rows) < batch_size:
            break

        start += batch_size

    return pd.DataFrame(all_rows)


def append_unique(parts, value):
    text = "" if pd.isna(value) else str(value).strip()

    if not text or text.lower() in {"nan", "none", "null", "nat"}:
        return

    for existing in parts:
        if text == existing or text in existing:
            return

    parts.append(text)


def normalize_big_area(value):
    """
    大区只保留一级票档/大类。数字段位、A1/B2、Floor2 这类分区不放进大区。
    """
    text = "" if pd.isna(value) else str(value).strip()

    if not text or text.lower() in {"nan", "none", "null", "nat"}:
        return ""

    if re.match(r"^\d+", text):
        return ""

    if re.match(r"^[A-Z]{1,2}\d+(?:\b|\s|$)", text, flags=re.IGNORECASE):
        return ""

    if re.match(r"^floor(?:zone|\d+)?(?:\b|\s|$)", text, flags=re.IGNORECASE):
        return ""

    cat_match = re.match(r"^(CAT\s*\d+[A-Z]?)\b", text, flags=re.IGNORECASE)
    if cat_match:
        return cat_match.group(1).replace(" ", "").upper()

    return text


def compose_ticket_detail(row):
    parts = []
    area_name = "" if pd.isna(row.get("大区名称", "")) else str(row.get("大区名称", "")).strip()

    for col in ["小区名称", "座位备注", "区域排号", "座位信息"]:
        value = row.get(col, "")
        text = "" if pd.isna(value) else str(value).strip()

        if text and text != area_name:
            append_unique(parts, text)

    return " | ".join(parts)


def normalize_columns(df):
    """
    兼容英文字段和中文字段。
    """
    if df.empty:
        return df

    df = df.copy()

    rename_map = {}

    if "show_name" in df.columns:
        rename_map["show_name"] = "演出名称"
    if "area_name" in df.columns:
        rename_map["area_name"] = "大区名称"
    if "original_price" in df.columns:
        rename_map["original_price"] = "原价数值"
    if "current_price" in df.columns:
        rename_map["current_price"] = "当前价数值"
    if "collect_time" in df.columns:
        rename_map["collect_time"] = "采集时间"
    if "section_name" in df.columns:
        rename_map["section_name"] = "小区名称"
    if "row_name" in df.columns:
        rename_map["row_name"] = "区域排号"
    if "seat_remark" in df.columns:
        rename_map["seat_remark"] = "座位备注"
    if "seat_info" in df.columns:
        rename_map["seat_info"] = "座位信息"
    if "ticket_detail" in df.columns:
        rename_map["ticket_detail"] = "票面详情"

    df = df.rename(columns=rename_map)

    for col in ["演出名称", "大区名称", "采集时间", "原价数值", "当前价数值"]:
        if col not in df.columns:
            df[col] = None

    for col in ["小区名称", "区域排号", "座位备注", "座位信息", "票面详情"]:
        if col not in df.columns:
            df[col] = ""

    df["采集时间"] = pd.to_datetime(df["采集时间"], errors="coerce")
    df["采集批次"] = df["采集时间"].dt.floor("min")
    df["采集日期"] = df["采集时间"].dt.date

    df["原价数值"] = pd.to_numeric(df["原价数值"], errors="coerce")
    df["当前价数值"] = pd.to_numeric(df["当前价数值"], errors="coerce")

    df["演出名称"] = df["演出名称"].fillna("").astype(str).str.strip()
    df["大区名称"] = df["大区名称"].fillna("").astype(str).str.strip()

    # 兼容之前上传过的“大区 | 小区/座位”旧数据：
    # 左侧大区筛选只使用第 1 段，其余内容放到票面详情里。
    combined_area = df["大区名称"].str.contains("|", regex=False, na=False)
    split_area = df.loc[combined_area, "大区名称"].str.split("|", n=1, regex=False)
    df.loc[combined_area, "大区名称"] = split_area.str[0].str.strip()

    old_detail = split_area.str[1].fillna("").str.strip()
    missing_detail = df.loc[combined_area, "票面详情"].fillna("").astype(str).str.strip() == ""
    detail_target_index = df.loc[combined_area].index[missing_detail.to_numpy()]
    df.loc[detail_target_index, "票面详情"] = old_detail[missing_detail].to_numpy()

    raw_area = df["大区名称"].copy()
    normalized_area = raw_area.apply(normalize_big_area)
    numeric_area = raw_area.ne("") & normalized_area.eq("")

    if numeric_area.any():
        for idx, value in raw_area[numeric_area].items():
            parts = []
            append_unique(parts, value)
            append_unique(parts, df.at[idx, "票面详情"])
            df.at[idx, "票面详情"] = " | ".join(parts)

    df["大区名称"] = normalized_area

    for col in ["小区名称", "区域排号", "座位备注", "座位信息", "票面详情"]:
        df[col] = df[col].fillna("").astype(str).str.strip()

    missing_detail = df["票面详情"] == ""
    if missing_detail.any():
        df.loc[missing_detail, "票面详情"] = df.loc[missing_detail].apply(compose_ticket_detail, axis=1)

    df = df[df["演出名称"] != ""]
    df = df.dropna(subset=["采集批次", "当前价数值"])

    return df


def get_latest_rows_each_show(df):
    """
    每个演出只取最新一次采集批次，避免把历史批次累加。
    """
    frames = []

    for show_name, group in df.groupby("演出名称"):
        latest_batch = group["采集批次"].max()
        frames.append(group[group["采集批次"] == latest_batch])

    if not frames:
        return pd.DataFrame(columns=df.columns)

    return pd.concat(frames, ignore_index=True)


def build_show_trend(df):
    """
    多演出趋势对比：
    默认按演出汇总，不把大区展开成太多线。
    """
    if df.empty:
        return pd.DataFrame()

    trend = (
        df
        .groupby(["采集批次", "演出名称"], dropna=False)
        .agg(
            当前票源数=("当前价数值", "count"),
            最低当前价=("当前价数值", "min"),
            最高当前价=("当前价数值", "max"),
        )
        .reset_index()
    )

    for col in ["最低当前价", "最高当前价"]:
        trend[col] = trend[col].round(2)

    return trend


def build_area_trend(df):
    """
    演出 + 大区趋势。
    数据量多时会比较密集，所以放在可选项里。
    """
    if df.empty:
        return pd.DataFrame()

    trend = (
        df
        .groupby(["采集批次", "演出名称", "大区名称"], dropna=False)
        .agg(
            当前票源数=("当前价数值", "count"),
            最低当前价=("当前价数值", "min"),
            最高当前价=("当前价数值", "max"),
        )
        .reset_index()
    )

    trend["对比名称"] = trend["演出名称"] + "｜" + trend["大区名称"].replace("", "未分区")

    for col in ["最低当前价", "最高当前价"]:
        trend[col] = trend[col].round(2)

    return trend


# =========================
# 页面主体
# =========================
st.title("MoreTickets 价格看板")

df = normalize_columns(load_data())

if df.empty:
    st.warning("暂无数据。请先运行采集程序并上传到 Supabase。")
    st.stop()

show_options = sorted(df["演出名称"].dropna().unique())

st.info("请先选择一个或多个演出，页面不会默认展示全部演出。")

selected_shows = st.multiselect(
    "选择演出，可多选对比",
    options=show_options,
    default=[],
    placeholder="请选择演出"
)

if not selected_shows:
    st.stop()

selected_df = df[df["演出名称"].isin(selected_shows)].copy()

# 侧边栏：补充筛选
st.sidebar.header("补充筛选")

area_options = sorted([x for x in selected_df["大区名称"].dropna().unique() if str(x).strip() != ""])

selected_areas = st.sidebar.multiselect(
    "选择大区",
    options=area_options,
    default=area_options,
    placeholder="默认全部大区"
)

if selected_areas:
    selected_df = selected_df[selected_df["大区名称"].isin(selected_areas)]

detail_options = sorted([x for x in selected_df["票面详情"].dropna().unique() if str(x).strip() != ""])

selected_details = st.sidebar.multiselect(
    "选择二级/座位",
    options=detail_options,
    default=[],
    placeholder="默认全部二级/座位"
)

if selected_details:
    selected_df = selected_df[selected_df["票面详情"].isin(selected_details)]

if selected_df.empty:
    st.warning("筛选后没有数据，请重新选择演出、大区或二级/座位。")
    st.stop()

latest_df = get_latest_rows_each_show(selected_df)

selected_show_text = "、".join(selected_shows[:3])
if len(selected_shows) > 3:
    selected_show_text += f" 等 {len(selected_shows)} 个演出"

st.caption(f"当前选择：{selected_show_text}")


# =========================
# 当前概览，只看每个演出的最新批次
# =========================
st.subheader("当前概览")

col1, col2 = st.columns(2)
with col1:
    st.metric("已选演出数量", len(selected_shows))
with col2:
    st.metric("当前票源数", len(latest_df))

col3, col4 = st.columns(2)
with col3:
    st.metric("最低当前价", f"{latest_df['当前价数值'].min():.0f}" if not latest_df.empty else "-")
with col4:
    st.metric("最高当前价", f"{latest_df['当前价数值'].max():.0f}" if not latest_df.empty else "-")


tab1, tab2, tab3 = st.tabs(["价格趋势", "当前演出对比", "明细数据"])


# =========================
# 价格趋势：默认最低当前价
# =========================
with tab1:
    st.subheader("价格趋势")

    metric_map = {
        "最低当前价": "最低当前价",
        "最高当前价": "最高当前价",
        "当前票源数": "当前票源数",
    }

    metric_name = st.selectbox(
        "选择趋势指标",
        list(metric_map.keys()),
        index=0
    )

    compare_mode = st.radio(
        "对比方式",
        ["按演出对比", "按演出 + 大区对比"],
        horizontal=True
    )

    metric_col = metric_map[metric_name]

    if compare_mode == "按演出对比":
        trend_df = build_show_trend(selected_df)
        color_col = "演出名称"
        title = f"{metric_name}趋势：多演出对比"
    else:
        trend_df = build_area_trend(selected_df)
        color_col = "对比名称"
        title = f"{metric_name}趋势：演出 + 大区对比"

    if trend_df.empty:
        st.info("暂无趋势数据。")
    else:
        fig = px.line(
            trend_df,
            x="采集批次",
            y=metric_col,
            color=color_col,
            markers=True,
            title=title
        )

        fig.update_layout(
            height=430,
            xaxis_title="采集批次",
            yaxis_title=metric_name,
            legend_title="对比对象",
            margin=dict(l=10, r=10, t=50, b=10)
        )

        st.plotly_chart(fig, use_container_width=True)


# =========================
# 当前演出对比：不做平均原价 vs 平均当前价
# =========================
with tab2:
    st.subheader("当前演出对比")

    if latest_df.empty:
        st.info("暂无当前批次数据。")
    else:
        show_summary = (
            latest_df
            .groupby("演出名称", dropna=False)
            .agg(
                当前票源数=("当前价数值", "count"),
                最低当前价=("当前价数值", "min"),
                最高当前价=("当前价数值", "max"),
                最新采集批次=("采集批次", "max"),
            )
            .reset_index()
        )

        show_summary["最低当前价"] = show_summary["最低当前价"].round(2)
        show_summary["最高当前价"] = show_summary["最高当前价"].round(2)
        show_summary["最新采集批次"] = show_summary["最新采集批次"].dt.strftime("%Y-%m-%d %H:%M")

        fig_bar = px.bar(
            show_summary,
            x="演出名称",
            y="最低当前价",
            text="最低当前价",
            title="当前各演出最低当前价对比"
        )

        fig_bar.update_layout(
            height=390,
            xaxis_title="演出名称",
            yaxis_title="最低当前价",
            margin=dict(l=10, r=10, t=50, b=10)
        )

        st.plotly_chart(fig_bar, use_container_width=True)

        st.dataframe(
            show_summary.sort_values("最低当前价", ascending=True),
            use_container_width=True,
            height=260
        )


# =========================
# 明细数据
# =========================
with tab3:
    st.subheader("当前最新批次明细")

    simple_columns = [
        "采集批次",
        "演出名称",
        "大区名称",
        "票面详情",
        "当前价数值",
        "原价数值",
    ]

    # 如果表里还有这些字段，也一起展示
    extra_columns = [
        "platform",
        "票类型",
        "小区名称",
        "区域排号",
        "座位信息",
        "座位备注",
        "页面链接",
        "inventoryId",
    ]

    display_columns = [c for c in simple_columns + extra_columns if c in latest_df.columns]

    display_df = latest_df[display_columns].copy()

    if "采集批次" in display_df.columns:
        display_df["采集批次"] = pd.to_datetime(display_df["采集批次"]).dt.strftime("%Y-%m-%d %H:%M")

    st.dataframe(
        display_df.sort_values(["演出名称", "当前价数值"], ascending=[True, True]),
        use_container_width=True,
        height=430
    )

    csv_data = display_df.to_csv(index=False, encoding="utf-8-sig")

    st.download_button(
        "下载当前最新批次数据 CSV",
        data=csv_data,
        file_name="moretickets_current_selected_data.csv",
        mime="text/csv",
        use_container_width=True
    )
