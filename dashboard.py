import pandas as pd
import streamlit as st
import plotly.express as px
from supabase import create_client

# =========================
# 页面基础配置
# =========================
st.set_page_config(
    page_title="MoreTickets 价格趋势看板",
    page_icon="📈",
    layout="wide"
)

st.title("MoreTickets 价格趋势看板")

# =========================
# Supabase 配置
# =========================
TABLE_NAME = "ticket_data"

SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("没有读取到 Supabase 配置。请在 .streamlit/secrets.toml 或 Streamlit Cloud Secrets 里填写 SUPABASE_URL 和 SUPABASE_KEY。")
    st.stop()


# =========================
# 数据读取
# =========================
@st.cache_data(ttl=60)
def load_supabase_data():
    """从 Supabase 云数据库读取 ticket_data 表，分批读取避免超过 1000 行显示不全。"""
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    all_rows = []
    start = 0
    batch_size = 1000

    while True:
        response = (
            supabase
            .table(TABLE_NAME)
            .select("*")
            .order("collect_time", desc=False)
            .range(start, start + batch_size - 1)
            .execute()
        )

        rows = response.data or []
        if not rows:
            break

        all_rows.extend(rows)

        if len(rows) < batch_size:
            break

        start += batch_size

    return pd.DataFrame(all_rows)


def to_number(series):
    return pd.to_numeric(series, errors="coerce")


def normalize_columns(df):
    """
    统一列名，并生成“采集批次”。
    重点：数据库里存的是历史记录，不能把所有历史记录直接当作当前票数。
    """
    if df.empty:
        return df

    df = df.copy()

    mapping = {
        "show_name": "演出名称",
        "area_name": "大区名称",
        "original_price": "原价数值",
        "current_price": "当前价数值",
        "collect_time": "采集时间",
        "platform": "平台",
        "stock": "库存数值",
        "inventory": "库存数值",
        "inventory_count": "库存数值",
        "section_name": "小区名称",
        "seat_info": "座位信息",
        "currency": "币种",
    }

    for src, dst in mapping.items():
        if src in df.columns and dst not in df.columns:
            df[dst] = df[src]

    if "采集时间" in df.columns:
        df["采集时间"] = pd.to_datetime(df["采集时间"], errors="coerce")
    else:
        df["采集时间"] = pd.Timestamp.now()

    # 如果上传脚本每行时间略有差异，用分钟归并成一次采集批次。
    # 后续建议在 upload_to_supabase.py 里让同一批数据使用同一个 collect_time。
    df["采集批次"] = df["采集时间"].dt.floor("min")
    df["采集日期"] = df["采集批次"].dt.normalize()

    text_defaults = {
        "演出名称": "未命名演出",
        "大区名称": "未命名大区",
        "小区名称": "",
        "座位备注": "",
        "座位信息": "",
        "币种": "",
        "平台": "MoreTickets"
    }

    for col, default_value in text_defaults.items():
        if col not in df.columns:
            df[col] = default_value
        df[col] = df[col].fillna(default_value).astype(str)

    # 数值字段
    for col in ["库存数值", "原价数值", "当前价数值", "最低销售价数值"]:
        if col in df.columns:
            df[col] = to_number(df[col])

    if "当前价数值" not in df.columns:
        st.error("数据库里没有 current_price 或 当前价数值 字段，无法画价格图。")
        st.stop()

    if "原价数值" not in df.columns:
        df["原价数值"] = pd.NA

    if "最低销售价数值" not in df.columns:
        df["最低销售价数值"] = df["当前价数值"]

    # 如果没有库存字段，不要把历史记录累加成库存；用每行=1表示一条票源。
    if "库存数值" not in df.columns:
        df["库存数值"] = 1
        df["是否真实库存字段"] = False
    else:
        df["是否真实库存字段"] = True
        df["库存数值"] = df["库存数值"].fillna(0)

    # 如果有真实票源 ID，就用它去重；没有则用行数作为票源数。
    id_candidates = ["inventoryId", "inventory_id", "ticket_id", "票源ID", "库存ID"]
    ticket_id_col = None
    for col in id_candidates:
        if col in df.columns:
            ticket_id_col = col
            break

    if ticket_id_col:
        df["票源唯一标识"] = df[ticket_id_col].astype(str)
        df["是否有真实票源ID"] = True
    else:
        # 注意：不要使用 Supabase 自增 id 去跨批次去重，它每次上传都会变，不能代表同一张票。
        df["票源唯一标识"] = df.index.astype(str)
        df["是否有真实票源ID"] = False

    # 展示字段
    if "原价" not in df.columns:
        df["原价"] = df["原价数值"]
    if "当前价" not in df.columns:
        df["当前价"] = df["当前价数值"]
    if "最低销售价" not in df.columns:
        df["最低销售价"] = df["最低销售价数值"]
    if "库存" not in df.columns:
        df["库存"] = df["库存数值"]

    df = df.dropna(subset=["当前价数值", "采集批次"])
    return df


def filter_dataframe(df):
    st.sidebar.title("筛选条件")

    event_options = sorted([x for x in df["演出名称"].dropna().unique() if str(x).strip() != ""])
    selected_events = st.sidebar.multiselect("演出名称", event_options, default=event_options)
    if selected_events:
        df = df[df["演出名称"].isin(selected_events)]

    area_options = sorted([x for x in df["大区名称"].dropna().unique() if str(x).strip() != ""])
    selected_areas = st.sidebar.multiselect("大区名称", area_options, default=area_options)
    if selected_areas:
        df = df[df["大区名称"].isin(selected_areas)]

    section_options = sorted([x for x in df["小区名称"].dropna().unique() if str(x).strip() != ""])
    selected_sections = st.sidebar.multiselect("小区名称", section_options, default=[])
    if selected_sections:
        df = df[df["小区名称"].isin(selected_sections)]

    if not df.empty and "当前价数值" in df.columns:
        price_min = int(df["当前价数值"].min()) if pd.notna(df["当前价数值"].min()) else 0
        price_max = int(df["当前价数值"].max()) if pd.notna(df["当前价数值"].max()) else 10000
        if price_max > price_min:
            selected_price_range = st.sidebar.slider(
                "当前价范围",
                min_value=price_min,
                max_value=price_max,
                value=(price_min, price_max)
            )
            df = df[(df["当前价数值"] >= selected_price_range[0]) & (df["当前价数值"] <= selected_price_range[1])]

    return df


def add_snapshot_selector(df):
    """允许查看最新批次，也允许回看历史批次。"""
    batches = sorted(df["采集批次"].dropna().unique(), reverse=True)
    if not batches:
        return df, None

    batch_labels = [pd.Timestamp(x).strftime("%Y-%m-%d %H:%M") for x in batches]
    selected_label = st.sidebar.selectbox("查看采集批次", batch_labels, index=0)
    selected_batch = batches[batch_labels.index(selected_label)]
    snapshot_df = df[df["采集批次"] == selected_batch].copy()
    return snapshot_df, selected_batch


def count_tickets(df):
    """当前批次票源数量：有真实票源ID就去重，没有就按行数统计。"""
    if df.empty:
        return 0
    if "是否有真实票源ID" in df.columns and bool(df["是否有真实票源ID"].any()):
        return df["票源唯一标识"].nunique()
    return len(df)


def build_snapshot_summary(df):
    """按采集批次、演出、大区汇总趋势数据。"""
    if df.empty:
        return pd.DataFrame()

    use_unique_id = "是否有真实票源ID" in df.columns and bool(df["是否有真实票源ID"].any())

    grouped = df.groupby(["采集批次", "演出名称", "大区名称"], dropna=False)

    summary = grouped.agg(
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
    ).reset_index()

    if use_unique_id:
        ticket_counts = grouped["票源唯一标识"].nunique().reset_index(name="票源数量")
        summary = summary.merge(ticket_counts, on=["采集批次", "演出名称", "大区名称"], how="left")
    else:
        summary["票源数量"] = summary["记录数量"]

    for col in ["平均原价", "平均当前价", "平均最低销售价"]:
        if col in summary.columns:
            summary[col] = summary[col].round(2)

    return summary


# =========================
# 页面主体
# =========================
raw_df = load_supabase_data()

if raw_df.empty:
    st.warning("Supabase 的 ticket_data 表没有读取到数据。请确认本地采集程序已经上传成功，且 Streamlit Secrets 填写正确。")
    st.stop()

df = normalize_columns(raw_df)

if df.empty:
    st.warning("读取到了数据，但没有可用于展示的当前价数据。")
    st.stop()

st.caption(f"当前数据来源：Supabase 云数据库 / 表：{TABLE_NAME}")
st.caption(f"数据库历史记录数：{len(df)} 条；采集批次数：{df['采集批次'].nunique()} 次；最新采集批次：{df['采集批次'].max().strftime('%Y-%m-%d %H:%M')}")

filtered_all_df = filter_dataframe(df)

if filtered_all_df.empty:
    st.warning("筛选后没有数据，请调整左侧筛选条件。")
    st.stop()

snapshot_df, selected_batch = add_snapshot_selector(filtered_all_df)

if snapshot_df.empty:
    st.warning("当前采集批次没有数据，请调整左侧筛选条件。")
    st.stop()

summary_df = build_snapshot_summary(filtered_all_df)

# =========================
# 顶部指标：全部使用当前采集批次，不再累计历史批次
# =========================
st.subheader("当前采集批次概览")

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("当前批次", pd.Timestamp(selected_batch).strftime("%m-%d %H:%M"))

with col2:
    st.metric("演出数量", snapshot_df["演出名称"].nunique())

with col3:
    st.metric("当前票源数", count_tickets(snapshot_df))

with col4:
    st.metric("最低当前价", f"{snapshot_df['当前价数值'].min():.0f}")

with col5:
    st.metric("平均当前价", f"{snapshot_df['当前价数值'].mean():.0f}")

with st.expander("说明：为什么这里不再显示 2000 张？"):
    st.write(
        "Supabase 里保存的是历史记录。比如 11:44 采集 1000 条，11:55 又采集 1000 条，数据库历史记录确实是 2000 条，"
        "但当前票源数应该只看某一次采集批次。这个页面顶部指标和大区对比都只使用左侧选择的采集批次，默认是最新批次。"
    )

# =========================
# 趋势图：按采集批次变化，不按日期把一天内多次采集合并
# =========================
st.subheader("价格 / 票源趋势图")

metric_options = {
    "最低当前价": "最低当前价",
    "平均当前价": "平均当前价",
    "最高当前价": "最高当前价",
    "最低原价": "最低原价",
    "平均原价": "平均原价",
    "最高原价": "最高原价",
    "票源数量": "票源数量",
    "总库存": "总库存",
}

selected_metric_name = st.selectbox("选择趋势指标", list(metric_options.keys()), index=1)
metric_col = metric_options[selected_metric_name]

if not summary_df.empty:
    fig = px.line(
        summary_df,
        x="采集批次",
        y=metric_col,
        color="演出名称",
        line_dash="大区名称",
        markers=True,
        title=f"{selected_metric_name} 趋势（按采集批次）"
    )
    fig.update_layout(
        height=520,
        xaxis_title="采集批次",
        yaxis_title=selected_metric_name,
        legend_title="演出 / 大区"
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("暂无可用于趋势图的数据。")

# =========================
# 大区价格对比：只看当前批次
# =========================
st.subheader("当前批次大区价格对比")

area_grouped = snapshot_df.groupby(["演出名称", "大区名称"], dropna=False)
area_summary = area_grouped.agg(
    记录数量=("演出名称", "count"),
    总库存=("库存数值", "sum"),
    最低当前价=("当前价数值", "min"),
    平均当前价=("当前价数值", "mean"),
    最高当前价=("当前价数值", "max"),
    平均原价=("原价数值", "mean"),
).reset_index()

if "是否有真实票源ID" in snapshot_df.columns and bool(snapshot_df["是否有真实票源ID"].any()):
    area_ticket_counts = area_grouped["票源唯一标识"].nunique().reset_index(name="票源数量")
    area_summary = area_summary.merge(area_ticket_counts, on=["演出名称", "大区名称"], how="left")
else:
    area_summary["票源数量"] = area_summary["记录数量"]

area_summary["平均当前价"] = area_summary["平均当前价"].round(2)
area_summary["平均原价"] = area_summary["平均原价"].round(2)

fig_bar = px.bar(
    area_summary,
    x="大区名称",
    y="平均当前价",
    color="演出名称",
    barmode="group",
    text="平均当前价",
    title=f"{pd.Timestamp(selected_batch).strftime('%Y-%m-%d %H:%M')} 各大区平均当前价"
)
fig_bar.update_layout(height=480, xaxis_title="大区名称", yaxis_title="平均当前价")
st.plotly_chart(fig_bar, use_container_width=True)

# =========================
# 当前批次原价 vs 当前价
# =========================
st.subheader("当前批次原价与当前价对比")

compare_summary = area_summary[["演出名称", "大区名称", "平均原价", "平均当前价", "票源数量"]].copy()
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
    title="当前批次各演出各大区：平均原价 vs 平均当前价"
)
fig_compare.update_layout(height=500)
st.plotly_chart(fig_compare, use_container_width=True)

# =========================
# 数据表格
# =========================
st.subheader("当前批次明细数据")

display_columns = [
    "采集批次",
    "采集时间",
    "演出名称",
    "大区名称",
    "小区名称",
    "座位备注",
    "座位信息",
    "库存",
    "原价",
    "当前价",
    "最低销售价",
    "币种",
    "平台",
    "票源唯一标识",
]

display_columns = [col for col in display_columns if col in snapshot_df.columns]

st.dataframe(
    snapshot_df[display_columns].sort_values("采集时间", ascending=False),
    use_container_width=True,
    height=480
)

# =========================
# 导出数据
# =========================
st.subheader("导出数据")

csv_data = snapshot_df.to_csv(index=False, encoding="utf-8-sig")
st.download_button(
    label="下载当前采集批次 CSV",
    data=csv_data,
    file_name="current_snapshot_moretickets_data.csv",
    mime="text/csv"
)

csv_all_data = filtered_all_df.to_csv(index=False, encoding="utf-8-sig")
st.download_button(
    label="下载全部历史筛选数据 CSV",
    data=csv_all_data,
    file_name="history_moretickets_data.csv",
    mime="text/csv"
)
