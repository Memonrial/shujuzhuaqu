import os
import glob
from datetime import datetime

import pandas as pd
import streamlit as st
import plotly.express as px


# =========================
# 基础配置
# =========================

OUTPUT_DIR = "output"
HISTORY_FILE = os.path.join(OUTPUT_DIR, "history_prices.csv")


st.set_page_config(
    page_title="MoreTickets 价格趋势看板",
    page_icon="📈",
    layout="wide"
)


# =========================
# 工具函数
# =========================

def to_number(series):
    return pd.to_numeric(series, errors="coerce")


def load_history_data():
    """
    优先读取 output/history_prices.csv。
    如果没有 history_prices.csv，则尝试读取 output 里最新的 Excel 文件。
    """

    if os.path.exists(HISTORY_FILE):
        df = pd.read_csv(HISTORY_FILE, encoding="utf-8-sig")
        return df, HISTORY_FILE

    excel_files = glob.glob(os.path.join(OUTPUT_DIR, "moretickets_prices_*.xlsx"))

    if not excel_files:
        return pd.DataFrame(), None

    latest_file = max(excel_files, key=os.path.getmtime)

    all_sheets = pd.read_excel(latest_file, sheet_name=None)

    frames = []

    for sheet_name, sheet_df in all_sheets.items():
        if sheet_name in ["演出汇总", "全部明细", "明细数据"]:
            continue

        if sheet_df.empty:
            continue

        frames.append(sheet_df)

    if not frames:
        return pd.DataFrame(), latest_file

    df = pd.concat(frames, ignore_index=True)

    return df, latest_file


def clean_data(df):
    if df.empty:
        return df

    df = df.copy()

    # 日期处理
    if "采集日期" in df.columns:
        df["采集日期"] = pd.to_datetime(df["采集日期"], errors="coerce")
    else:
        df["采集日期"] = pd.to_datetime(datetime.now().date())

    # 常用数值字段处理
    numeric_columns = [
        "库存数值",
        "原价数值",
        "当前价数值",
        "最低销售价数值",
        "库存",
        "原价",
        "当前价",
        "最低销售价"
    ]

    for col in numeric_columns:
        if col in df.columns:
            df[col] = to_number(df[col])

    # 如果没有数值列，就从文本价格列转换
    if "原价数值" not in df.columns and "原价" in df.columns:
        df["原价数值"] = to_number(
            df["原价"].astype(str)
            .str.replace("HK$", "", regex=False)
            .str.replace(",", "", regex=False)
        )

    if "当前价数值" not in df.columns and "当前价" in df.columns:
        df["当前价数值"] = to_number(
            df["当前价"].astype(str)
            .str.replace("HK$", "", regex=False)
            .str.replace(",", "", regex=False)
        )

    if "最低销售价数值" not in df.columns and "最低销售价" in df.columns:
        df["最低销售价数值"] = to_number(
            df["最低销售价"].astype(str)
            .str.replace("HK$", "", regex=False)
            .str.replace(",", "", regex=False)
        )

    # 防止缺少字段时报错
    default_text_columns = [
        "演出名称",
        "大区名称",
        "小区名称",
        "座位备注",
        "座位信息",
        "币种"
    ]

    for col in default_text_columns:
        if col not in df.columns:
            df[col] = ""

    return df


def filter_dataframe(df):
    """
    左侧筛选器
    """

    st.sidebar.title("筛选条件")

    event_options = sorted([x for x in df["演出名称"].dropna().unique()])
    selected_events = st.sidebar.multiselect(
        "演出名称",
        event_options,
        default=event_options
    )

    if selected_events:
        df = df[df["演出名称"].isin(selected_events)]

    area_options = sorted([x for x in df["大区名称"].dropna().unique() if str(x).strip() != ""])
    selected_areas = st.sidebar.multiselect(
        "大区名称",
        area_options,
        default=area_options
    )

    if selected_areas:
        df = df[df["大区名称"].isin(selected_areas)]

    section_options = sorted([x for x in df["小区名称"].dropna().unique() if str(x).strip() != ""])
    selected_sections = st.sidebar.multiselect(
        "小区名称",
        section_options,
        default=[]
    )

    if selected_sections:
        df = df[df["小区名称"].isin(selected_sections)]

    price_min = int(df["当前价数值"].min()) if "当前价数值" in df.columns and pd.notna(df["当前价数值"].min()) else 0
    price_max = int(df["当前价数值"].max()) if "当前价数值" in df.columns and pd.notna(df["当前价数值"].max()) else 10000

    if price_max > price_min:
        selected_price_range = st.sidebar.slider(
            "当前价范围",
            min_value=price_min,
            max_value=price_max,
            value=(price_min, price_max)
        )

        df = df[
            (df["当前价数值"] >= selected_price_range[0]) &
            (df["当前价数值"] <= selected_price_range[1])
        ]

    return df


def build_daily_summary(df):
    """
    按日期、演出、大区汇总趋势数据
    """

    if df.empty:
        return pd.DataFrame()

    group_cols = ["采集日期", "演出名称", "大区名称"]

    summary = (
        df.groupby(group_cols, dropna=False)
        .agg(
            票源数量=("inventoryId", "nunique"),
            记录数量=("演出名称", "count"),
            总库存=("库存数值", "sum"),
            最低原价=("原价数值", "min"),
            平均原价=("原价数值", "mean"),
            最高原价=("原价数值", "max"),
            最低当前价=("当前价数值", "min"),
            平均当前价=("当前价数值", "mean"),
            最高当前价=("当前价数值", "max"),
            最低销售价=("最低销售价数值", "min"),
            平均最低销售价=("最低销售价数值", "mean"),
        )
        .reset_index()
    )

    for col in ["平均原价", "平均当前价", "平均最低销售价"]:
        if col in summary.columns:
            summary[col] = summary[col].round(2)

    return summary


# =========================
# 页面主体
# =========================

st.title("MoreTickets 价格趋势看板")

df, source_file = load_history_data()

if df.empty:
    st.warning("没有读取到数据。请先运行 collect_moretickets.py 生成 output/history_prices.csv 或 Excel。")
    st.stop()

df = clean_data(df)

st.caption(f"当前数据来源：{source_file}")

filtered_df = filter_dataframe(df)

if filtered_df.empty:
    st.warning("筛选后没有数据，请调整左侧筛选条件。")
    st.stop()

summary_df = build_daily_summary(filtered_df)


# =========================
# 顶部指标
# =========================

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("演出数量", filtered_df["演出名称"].nunique())

with col2:
    st.metric("票源记录", len(filtered_df))

with col3:
    if "当前价数值" in filtered_df.columns:
        st.metric("最低当前价", f"{filtered_df['当前价数值'].min():.0f}")

with col4:
    if "当前价数值" in filtered_df.columns:
        st.metric("平均当前价", f"{filtered_df['当前价数值'].mean():.0f}")

with col5:
    if "库存数值" in filtered_df.columns:
        st.metric("总库存", f"{filtered_df['库存数值'].sum():.0f}")


# =========================
# 趋势图区域
# =========================

st.subheader("价格趋势图")

metric_options = {
    "最低当前价": "最低当前价",
    "平均当前价": "平均当前价",
    "最高当前价": "最高当前价",
    "最低原价": "最低原价",
    "平均原价": "平均原价",
    "最高原价": "最高原价",
    "总库存": "总库存",
    "票源数量": "票源数量",
}

selected_metric_name = st.selectbox(
    "选择趋势指标",
    list(metric_options.keys()),
    index=1
)

metric_col = metric_options[selected_metric_name]

if not summary_df.empty:
    fig = px.line(
        summary_df,
        x="采集日期",
        y=metric_col,
        color="演出名称",
        line_dash="大区名称",
        markers=True,
        title=f"{selected_metric_name} 趋势"
    )

    fig.update_layout(
        height=520,
        xaxis_title="采集日期",
        yaxis_title=selected_metric_name,
        legend_title="演出 / 大区"
    )

    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("暂无可用于趋势图的数据。")


# =========================
# 大区价格对比
# =========================

st.subheader("大区价格对比")

latest_date = filtered_df["采集日期"].max()
latest_df = filtered_df[filtered_df["采集日期"] == latest_date]

area_summary = (
    latest_df.groupby(["演出名称", "大区名称"], dropna=False)
    .agg(
        票源数量=("inventoryId", "nunique"),
        总库存=("库存数值", "sum"),
        最低当前价=("当前价数值", "min"),
        平均当前价=("当前价数值", "mean"),
        最高当前价=("当前价数值", "max"),
        平均原价=("原价数值", "mean"),
    )
    .reset_index()
)

area_summary["平均当前价"] = area_summary["平均当前价"].round(2)
area_summary["平均原价"] = area_summary["平均原价"].round(2)

fig_bar = px.bar(
    area_summary,
    x="大区名称",
    y="平均当前价",
    color="演出名称",
    barmode="group",
    text="平均当前价",
    title=f"最新采集日 {latest_date.date()} 各大区平均当前价"
)

fig_bar.update_layout(
    height=480,
    xaxis_title="大区名称",
    yaxis_title="平均当前价"
)

st.plotly_chart(fig_bar, use_container_width=True)


# =========================
# 原价 vs 当前价
# =========================

st.subheader("原价与当前价对比")

compare_df = latest_df.copy()

if "原价数值" in compare_df.columns and "当前价数值" in compare_df.columns:
    compare_summary = (
        compare_df.groupby(["演出名称", "大区名称"], dropna=False)
        .agg(
            平均原价=("原价数值", "mean"),
            平均当前价=("当前价数值", "mean"),
            票源数量=("inventoryId", "nunique")
        )
        .reset_index()
    )

    compare_summary["平均原价"] = compare_summary["平均原价"].round(2)
    compare_summary["平均当前价"] = compare_summary["平均当前价"].round(2)

    compare_long = compare_summary.melt(
        id_vars=["演出名称", "大区名称", "票源数量"],
        value_vars=["平均原价", "平均当前价"],
        var_name="价格类型",
        value_name="价格"
    )

    fig_compare = px.bar(
        compare_long,
        x="大区名称",
        y="价格",
        color="价格类型",
        facet_col="演出名称",
        barmode="group",
        title="各演出各大区：平均原价 vs 平均当前价"
    )

    fig_compare.update_layout(height=500)

    st.plotly_chart(fig_compare, use_container_width=True)


# =========================
# 数据表格
# =========================

st.subheader("筛选后的明细数据")

display_columns = [
    "采集日期",
    "采集时间",
    "演出名称",
    "大区名称",
    "小区名称",
    "座位备注",
    "座位信息",
    "库存",
    "票类型",
    "原价",
    "当前价",
    "最低销售价",
    "币种",
    "inventoryId",
    "页面链接"
]

display_columns = [col for col in display_columns if col in filtered_df.columns]

st.dataframe(
    filtered_df[display_columns],
    use_container_width=True,
    height=480
)


# =========================
# 下载按钮
# =========================

st.subheader("导出数据")

csv_data = filtered_df.to_csv(index=False, encoding="utf-8-sig")

st.download_button(
    label="下载当前筛选数据 CSV",
    data=csv_data,
    file_name="filtered_moretickets_data.csv",
    mime="text/csv"
)