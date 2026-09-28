import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import pytz
import math
from streamlit_js_eval import get_geolocation

# 頁面基本設定
st.set_page_config(
    page_title="臺灣主要港口 UKC 動態評估系統 v3.4",
    page_icon="🚢",
    layout="centered"
)

# 時區設定（台灣時間）
tw_tz = pytz.timezone('Asia/Taipei')
now = datetime.now(tw_tz)

st.title("🚢 臺灣主要港口 UKC 動態評估系統 (v3.4 雙軌架構)")
st.caption(f"📅 當前時間：{now.strftime('%Y-%m-%d %H:%M:%S')} (CST)")

# API Key 安全讀取（優先讀取 st.secrets，若無則使用預設值）
CWA_API_KEY = st.secrets.get("CWA_API_KEY", "CWA-BD9BB68F-C6F0-4960-B0F0-98E82A8C3AB3")

# --- 1. 臺灣主要商港與工業港資料庫 ---
PORTS_DB = {
    "高雄港第二港口": {"lat": 22.55, "lon": 120.30, "depth": 17.0, "cwa_loc": "高雄市"},
    "高雄港第一港口": {"lat": 22.62, "lon": 120.27, "depth": 15.0, "cwa_loc": "高雄市"},
    "臺北港": {"lat": 25.16, "lon": 121.38, "depth": 16.0, "cwa_loc": "新北市"},
    "基隆港": {"lat": 25.15, "lon": 121.74, "depth": 14.5, "cwa_loc": "基隆市"},
    "臺中港": {"lat": 24.28, "lon": 120.52, "depth": 16.0, "cwa_loc": "臺中市"},
    "花蓮港": {"lat": 24.00, "lon": 121.64, "depth": 14.0, "cwa_loc": "花蓮縣"},
    "蘇澳港": {"lat": 24.58, "lon": 121.86, "depth": 15.0, "cwa_loc": "宜蘭縣"},
    "麥寮港 (工業專用港)": {"lat": 23.80, "lon": 120.20, "depth": 24.0, "cwa_loc": "雲林縣"},
    "安平港": {"lat": 22.98, "lon": 120.15, "depth": 7.5, "cwa_loc": "臺南市"},
    "興達港": {"lat": 22.87, "lon": 120.21, "depth": 6.0, "cwa_loc": "高雄市"},
    "布袋港": {"lat": 23.37, "lon": 120.15, "depth": 6.5, "cwa_loc": "嘉義縣"},
    "澎湖港 (馬公)": {"lat": 23.57, "lon": 119.58, "depth": 7.0, "cwa_loc": "澎湖縣"}
}

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

# --- 2. 實時定位 (GPS) 與港口選擇 ---
st.subheader("📍 實時定位與港口選擇")
geo_data = get_geolocation()

default_port = "高雄港第二港口"

if geo_data and 'coords' in geo_data:
    lat = geo_data['coords']['latitude']
    lon = geo_data['coords']['longitude']
    st.success(f"已獲取定位 GPS: {lat:.4f}, {lon:.4f}")
    
    min_dist = float('inf')
    closest_port = default_port
    for p_name, info in PORTS_DB.items():
        dist = calculate_distance(lat, lon, info["lat"], info["lon"])
        if dist < min_dist:
            min_dist = dist
            closest_port = p_name
            
    default_port = closest_port
    st.info(f"🎯 系統已自動幫您判定離您最近的港口為：**{default_port}** (直線距離約 {min_dist:.1f} 公里)")
else:
    st.warning("⚠️ 尚未取得 GPS 授權，預設為高雄港第二港口。您可透過下方選單切換全臺任一港口。")

port_names = list(PORTS_DB.keys())
default_index = port_names.index(default_port) if default_port in port_names else 0
selected_port = st.selectbox("選擇或切換港口與航道", port_names, index=default_index)

current_port_info = PORTS_DB[selected_port]
channel_depth = current_port_info["depth"]
cwa_location = current_port_info["cwa_loc"]

st.write(f"**當前選定港口**：`{selected_port}` ｜ **對應氣象測站**：`{cwa_location}` ｜ **預設設計水深**：`{channel_depth}m`")

# 參數輸入
draft = st.number_input("船舶吃水 Draft (m)", min_value=3.0, max_value=30.0, value=16.0, step=0.1)

# --- 3. 雙軌智慧架構 ---
@st.cache_data(ttl=3600)
def fetch_cwa_tide_data(api_key, location_name):
    url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-A0021-001?Authorization={api_key}&LocationName={location_name}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            locations = data.get("records", {}).get("location", [])
            for loc in locations:
                if loc.get("locationName") == location_name:
                    return loc, True
    except Exception:
        pass
    return None, False

cwa_loc_data, is_cwa_success = fetch_cwa_tide_data(CWA_API_KEY, cwa_location)

def generate_24h_forecast(current_dt, api_success, loc_data):
    forecast_list = []
    base_time = current_dt.replace(minute=0, second=0, microsecond=0)
    
    # 建立 CWA API 時間序列索引字典 (若 API 抓取成功)
    cwa_tide_map = {}
    if api_success and loc_data:
        try:
            time_periods = loc_data.get("validTime", [])
            for period in time_periods:
                # 依氣象署 F-A0021-001 結構提取時間與潮高 (公分轉公尺)
                t_str = period.get("startTime")
                weather_elements = period.get("weatherElement", [])
                tide_cm = None
                for elem in weather_elements:
                    if elem.get("elementName") in ["TideHeight", "潮高"]:
                        tide_cm = float(elem.get("elementValue", 0))
                        break
                if t_str and tide_cm is not None:
                    # 轉換時間格式解析
                    dt_obj = datetime.strptime(t_str[:19], "%Y-%m-%d %H:%M:%S")
                    cwa_tide_map[dt_obj.strftime("%Y-%m-%d %H:00")] = round(tide_cm / 100.0, 2)
        except Exception:
            cwa_tide_map = {}

    for i in range(24):
        t_time = base_time + timedelta(hours=i)
        t_key = t_time.strftime("%Y-%m-%d %H:00")
        
        # 軌道一：使用 API 數據；軌道二：無數據時降級回備援天文潮數學模型
        if t_key in cwa_tide_map:
            tide_height = cwa_tide_map[t_key]
        else:
            hour_val = t_time.hour
            tide_height = round(0.8 + 0.7 * math.sin((hour_val - 3) * math.pi / 6), 2)

        forecast_list.append({
            "datetime": t_time,
            "time_str": t_time.strftime("%H:00"),
            "is_now": (i == 0),
            "tide": tide_height
        })
    return forecast_list

tide_forecast = generate_24h_forecast(now, is_cwa_success, cwa_loc_data)

if is_cwa_success:
    st.toast(f"✅ 成功連線 {cwa_location} 官方即時潮汐資料軌道")
else:
    st.toast("ℹ️ 官方 API 無回應或超時，已切換至備援天文潮模型軌道", icon="🔄")

# --- 4. 計算 UKC 與燈號 ---
processed_results = []
current_status = "GREEN"
current_ukc_pct = 0.0

for item in tide_forecast:
    tide = item["tide"]
    avail_depth = channel_depth + tide
    ukc = avail_depth - draft
    ukc_pct = (ukc / draft) * 100
    
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
        "潮高(m)": tide,
        "可用水深(m)": round(avail_depth, 2),
        "UKC %": round(ukc_pct, 1),
        "狀態": status,
        "status_code": status_code
    }
    
    if item["is_now"]:
        current_status = status_code
        current_ukc_pct = ukc_pct
        
    processed_results.append(res_dict)

# --- 5. 動態背景與文字顏色設定 ---
bg_theme_map = {
    "GREEN": {"bg": "#e8f8f5", "text": "#145a32"},
    "YELLOW": {"bg": "#fef9e7", "text": "#7d6608"},
    "RED": {"bg": "#fadbd8", "text": "#78281f"}
}
style_cfg = bg_theme_map.get(current_status, {"bg": "#ffffff", "text": "#000000"})

st.markdown(
    f"""
    <style>
    .stApp {{
        background-color: {style_cfg['bg']};
        color: {style_cfg['text']};
        transition: background-color 0.5s ease;
    }}
    </style>
    """,
    unsafe_allow_html=True
)

# --- 6. 當前狀態與智慧進港時間建議 ---
st.subheader("⏱️ 當前過灘狀態評估")

if current_status == "GREEN":
    st.success(f"🟢 **當前時刻 ({now.strftime('%H:%M')}) 在 {selected_port} 可安全過灘入港！** (UKC 裕度: `{current_ukc_pct:.1f}%`)")
elif current_status == "YELLOW":
    st.warning(f"🟡 **當前時刻 ({now.strftime('%H:%M')}) 在 {selected_port} 為限制通行狀況。** (UKC 裕度: `{current_ukc_pct:.1f}%`)")
else:
    st.error(f"🔴 **當前時刻 ({now.strftime('%H:%M')}) 在 {selected_port} 禁止過灘！** 水深裕度不足 (UKC 裕度: `{current_ukc_pct:.1f}%`)")

next_green = next((r for r in processed_results if r["status_code"] == "GREEN"), None)
next_yellow = next((r for r in processed_results if r["status_code"] == "YELLOW"), None)

st.info("💡 **最近可進港時間指引**：")
if next_green:
    st.markdown(f"- 🟢 **最近安全通行時間 (UKC ≥ 15%)**：`{next_green['時間']}`（預測潮高 `{next_green['潮高(m)']}m`）")
else:
    st.markdown("- 🟢 **最近安全通行時間**：未來 24 小時內無符合安全裕度之潮窗")
    
if current_status == "RED" and next_yellow:
    st.markdown(f"- 🟡 **最近限制通行時間 (UKC 10-15%)**：`{next_yellow['時間']}`（預測潮高 `{next_yellow['潮高(m)']}m`）")

st.markdown("---")

# --- 7. 未來 24 小時動態潮窗預報 ---
st.subheader("📊 該港未來 24 小時動態潮窗預報")
df = pd.DataFrame(processed_results)
df_display = df[["時間", "潮高(m)", "可用水深(m)", "UKC %", "狀態"]]
st.dataframe(df_display, use_container_width=True)