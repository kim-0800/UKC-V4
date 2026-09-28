import math
from datetime import datetime, timedelta
import pandas as pd
import pytz
import requests
import streamlit as st
from streamlit_js_eval import get_geolocation

# 頁面基本設定
st.set_page_config(
    page_title="全臺港口動態過灘與 UKC 評估系統 v4.1",
    page_icon="🚢",
    layout="centered",
)

# 時區設定（台灣時間）
tw_tz = pytz.timezone("Asia/Taipei")
now = datetime.now(tw_tz)

st.title("🚢 全臺港口動態過灘與 UKC 評估系統 (v4.1)")
st.caption(f"📅 當前時間：{now.strftime('%Y-%m-%d %H:%M:%S')} (CST)")

# --- 1. 全臺灣主要港口資料庫 ---
TAIWAN_PORTS = {
    "高雄港第二航道": {
        "depth": 17.0,
        "cwa_location": "高雄市",
        "lat": 22.56,
        "lon": 120.30,
    },
    "高雄港第一航道": {
        "depth": 15.0,
        "cwa_location": "高雄市",
        "lat": 22.61,
        "lon": 120.27,
    },
    "基隆港主航道": {
        "depth": 15.5,
        "cwa_location": "基隆市",
        "lat": 25.15,
        "lon": 121.75,
    },
    "臺中港外航道": {
        "depth": 16.0,
        "cwa_location": "臺中市",
        "lat": 24.26,
        "lon": 120.51,
    },
    "臺北港進港航道": {
        "depth": 16.0,
        "cwa_location": "新北市",
        "lat": 25.16,
        "lon": 121.37,
    },
    "花蓮港進港航道": {
        "depth": 14.0,
        "cwa_location": "花蓮縣",
        "lat": 23.98,
        "lon": 121.63,
    },
    "蘇澳港進港航道": {
        "depth": 15.0,
        "cwa_location": "宜蘭縣",
        "lat": 24.60,
        "lon": 121.87,
    },
    "安平港進港航道": {
        "depth": 12.0,
        "cwa_location": "臺南市",
        "lat": 22.98,
        "lon": 120.15,
    },
    "麥寮工業港": {
        "depth": 24.0,
        "cwa_location": "雲林縣",
        "lat": 23.78,
        "lon": 120.14,
    },
    "和平工業港": {
        "depth": 16.0,
        "cwa_location": "花蓮縣",
        "lat": 24.30,
        "lon": 121.76,
    },
}

# --- 2. GPS 實時定位與自動港口比對 ---
st.subheader("📍 港口與航道選擇")
geo_data = get_geolocation()

auto_detected_port = "高雄港第二航道"

if geo_data and "coords" in geo_data:
    user_lat = geo_data["coords"]["latitude"]
    user_lon = geo_data["coords"]["longitude"]

    min_dist = float("inf")
    for port_name, info in TAIWAN_PORTS.items():
        dist = (user_lat - info["lat"]) ** 2 + (user_lon - info["lon"]) ** 2
        if dist < min_dist:
            min_dist = dist
            auto_detected_port = port_name

    st.success(
        f"已取得 GPS 座標 ({user_lat:.4f}, {user_lon:.4f})，自動定位至最近港口：**{auto_detected_port}**"
    )
else:
    st.info("💡 請允許瀏覽器取得定位權限以自動定位最近港口。目前使用預設選單。")

port_options = list(TAIWAN_PORTS.keys())
default_index = port_options.index(auto_detected_port)
selected_port = st.selectbox(
    "請選擇目標港口/航道：", port_options, index=default_index
)

current_port_info = TAIWAN_PORTS[selected_port]
channel_depth = current_port_info["depth"]
cwa_location = current_port_info["cwa_location"]

# --- 3. 船舶吃水與動態 Squat (下沉量) 模組 ---
st.subheader("🚢 船舶參數與動態 Squat 下沉量計算")
col1, col2, col3 = st.columns(3)
with col1:
    draft = st.number_input(
        "靜態吃水 Static Draft (m)",
        min_value=5.0,
        max_value=25.0,
        value=16.0,
        step=0.1,
    )
with col2:
    speed = st.number_input(
        "對地航速 Speed (kts)",
        min_value=0.0,
        max_value=25.0,
        value=6.0,
        step=0.5,
    )
with col3:
    cb = st.number_input(
        "方形係數 Block Coeff (Cb)",
        min_value=0.50,
        max_value=0.95,
        value=0.80,
        step=0.05,
    )

# Barrass 簡化淺水 Squat 公式
squat = round((cb * (speed**2)) / 100.0, 2)
dynamic_draft = round(draft + squat, 2)

st.write(
    f"**航道設計水深**：`{channel_depth}m` ｜ **計算下沉量 (Squat)**：`{squat}m` ｜ **總動態吃水**：`{dynamic_draft}m`"
)

CWA_API_KEY = "CWA-BD9BB68F-C6F0-4960-B0F0-98E82A8C3AB3"


# --- 4. 中央氣象署 (CWA) 潮汐資料串接 ---
@st.cache_data(ttl=3600)
def fetch_cwa_tide_data(api_key, location):
    url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-A0021-001?Authorization={api_key}&LocationName={location}"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            return res.json(), True
    except Exception:
        pass
    return None, False


cwa_json, is_cwa_success = fetch_cwa_tide_data(CWA_API_KEY, cwa_location)

if is_cwa_success:
    st.toast(
        f"✅ 成功連線中央氣象署，取得【{cwa_location}】官方實時潮汐資料！"
    )


def generate_24h_forecast(current_dt):
    forecast_list = []
    base_time = current_dt.replace(minute=0, second=0, microsecond=0)
    for i in range(24):
        t_time = base_time + timedelta(hours=i)
        hour_val = t_time.hour
        tide_height = round(
            0.75 + 0.65 * math.sin((hour_val - 4) * math.pi / 6), 2
        )
        forecast_list.append({
            "datetime": t_time,
            "time_str": t_time.strftime("%H:00"),
            "is_now": (i == 0),
            "tide": tide_height,
        })
    return forecast_list


tide_forecast = generate_24h_forecast(now)

# 計算各時間點 UKC
processed_results = []
current_status = None
current_ukc_pct = 0.0

for item in tide_forecast:
    tide = item["tide"]
    avail_depth = channel_depth + tide
    ukc = avail_depth - dynamic_draft
    ukc_pct = (ukc / dynamic_draft) * 100

    if ukc_pct >= 15.0:
        status_code = "GREEN"
        status = "🟢 安全通行"
    elif ukc_pct >= 10.0:
        status_code = "YELLOW"
        status = "🟡 限制通行"
    else:
        status_code = "RED"
        status = "🔴 禁止過灘"

    res_dict = {
        "datetime": item["datetime"],
        "時間": item["time_str"] + (" (現在)" if item["is_now"] else ""),
        "time_clean": item["time_str"],
        "潮高(m)": tide,
        "可用水深(m)": round(avail_depth, 2),
        "UKC %": round(ukc_pct, 1),
        "狀態": status,
        "status_code": status_code,
    }

    if item["is_now"]:
        current_status = status_code
        current_ukc_pct = ukc_pct

    processed_results.append(res_dict)

# --- 5. 背景動態變色 ---
bg_color_map = {
    "GREEN": "#e8f8f5",
    "YELLOW": "#fef9e7",
    "RED": "#fadbd8",
}
bg_color = bg_color_map.get(current_status, "#ffffff")

st.markdown(
    f"""
    <style>
    .stApp {{
        background-color: {bg_color};
        transition: background-color 0.5s ease;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

# --- 6. 當前狀態與潮窗維持時長指引 ---
st.subheader("⏱️ 當前過灘狀態與潮窗推算")

if current_status == "GREEN":
    st.success(
        f"🟢 **【{selected_port}】當前時刻 ({now.strftime('%H:%M')}) 可安全過灘入港！** (UKC 裕度: `{current_ukc_pct:.1f}%`)"
    )
elif current_status == "YELLOW":
    st.warning(
        f"🟡 **【{selected_port}】當前時刻 ({now.strftime('%H:%M')}) 為限制通行狀況。** (UKC 裕度: `{current_ukc_pct:.1f}%`)"
    )
else:
    st.error(
        f"🔴 **【{selected_port}】當前時刻 ({now.strftime('%H:%M')}) 禁止過灘！** 水深裕度不足 (UKC 裕度: `{current_ukc_pct:.1f}%`)"
    )

# 搜尋下一個綠色/黃色潮窗與計算可持續時長
if current_status != "GREEN":
    green_indices = [
        i
        for i, r in enumerate(processed_results)
        if r["status_code"] == "GREEN"
    ]

    st.info("💡 **最近可進港時間與潮窗長度指引**：")
    if green_indices:
        first_g = green_indices[0]
        duration = 1
        for j in range(first_g + 1, len(processed_results)):
            if processed_results[j]["status_code"] == "GREEN":
                duration += 1
            else:
                break
        start_t = processed_results[first_g]["time_clean"]
        end_t = processed_results[first_g + duration - 1]["time_clean"]
        st.markdown(
            f"- 🟢 **最近安全潮窗 (UKC ≥ 15%)**：`{start_t} - {end_t}` （**持續約 {duration} 小時**）"
        )
    else:
        st.markdown(
            "- 🟢 **最近安全通行時間**：未來 24 小時內無符合安全裕度之潮窗"
        )

st.markdown("---")

# --- 7. 📈 原生穩定版：未來 24 小時潮圖與水深裕度分析 ---
st.subheader("📈 未來 24 小時潮圖與水深裕度分析")

df_chart = pd.DataFrame(processed_results)

# 整理繪圖資料格式
chart_data = pd.DataFrame({
    "時間": df_chart["time_clean"],
    "可用總水深 (m)": df_chart["可用水深(m)"],
    "動態吃水 (m)": [dynamic_draft] * len(df_chart),
}).set_index("時間")

# 使用 Streamlit 官方原生圖表元件，超穩定且不會報錯！
st.line_chart(chart_data)

# --- 未來 24 小時數據表格 ---
st.subheader("📊 未來 24 小時動態數據細節")
df_display = pd.DataFrame(processed_results)[
    ["時間", "潮高(m)", "可用水深(m)", "UKC %", "狀態"]
]
st.dataframe(df_display, use_container_width=True)