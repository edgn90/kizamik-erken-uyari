import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

# Sayfa Ayarları
st.set_page_config(page_title="Kızamık YZ Sürveyans Radarı", page_icon="⏳", layout="wide")

st.title("⏳ Kızamık YZ Sürveyans Radarı (V5: Mekansal + Zaman Zayıflatmalı)")
st.markdown("Bu sistem; 3 KM'lik fiziksel bulaş çemberlerini ve vakaların zamanla eriyen **Üstel Zayıflatma (Time Decay)** ağırlıklarını kullanarak en güncel aktif tehdidi hesaplar.")

# --- 1. YÜKLEME MODÜLÜ (SIDEBAR) ---
st.sidebar.header("📂 Veri Yükleme Paneli")
file_cases = st.sidebar.file_uploader("1. Vaka Listesi (Kızamık.xlsx/csv)", type=["csv", "xlsx"])
file_pop = st.sidebar.file_uploader("2. Nüfus Verisi (Nüfus.xlsx/csv)", type=["csv", "xlsx"])
file_vax = st.sidebar.file_uploader("3. Aşı Performansı (KKK.xlsx/csv)", type=["csv", "xlsx"])
file_geo = st.sidebar.file_uploader("4. AHB Koordinatları (Geocoded.xlsx/csv)", type=["csv", "xlsx"])

aylar = {1: 'Ocak', 2: 'Şubat', 3: 'Mart', 4: 'Nisan', 5: 'Mayıs', 6: 'Haziran', 
         7: 'Temmuz', 8: 'Ağustos', 9: 'Eylül', 10: 'Ekim', 11: 'Kasım', 12: 'Aralık'}

# Haversine Formülü (Mesafe Hesaplayıcı)
def haversine_vectorized(lat1, lon1, lat2_array, lon2_array):
    R = 6371.0
    lat1, lon1 = np.radians(lat1), np.radians(lon1)
    lat2_array, lon2_array = np.radians(lat2_array), np.radians(lon2_array)
    dlat = lat2_array - lat1
    dlon = lon2_array - lon1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1) * np.cos(lat2_array) * np.sin(dlon/2.0)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return R * c

# --- ANA İŞLEYİŞ ---
if file_cases and file_pop and file_vax and file_geo:
    with st.spinner('Mekansal Çemberler Çiziliyor ve Zaman Zayıflatma (Time Decay) Hesaplanıyor...'):
        try:
            # Verileri Oku
            df_cases = pd.read_csv(file_cases) if file_cases.name.endswith('.csv') else pd.read_excel(file_cases)
            df_pop = pd.read_csv(file_pop) if file_pop.name.endswith('.csv') else pd.read_excel(file_pop)
            df_vax = pd.read_csv(file_vax) if file_vax.name.endswith('.csv') else pd.read_excel(file_vax)
            df_geo = pd.read_csv(file_geo) if file_geo.name.endswith('.csv') else pd.read_excel(file_geo)

            # Tarih ve Koordinat Ön Hazırlığı
            df_cases['Tarih'] = pd.to_datetime(df_cases['Tarih'], errors='coerce')
            latest_date = df_cases['Tarih'].max()
            
            if 'Lat' in df_cases.columns and 'Lon' in df_cases.columns:
                df_cases['Lat'] = pd.to_numeric(df_cases['Lat'], errors='coerce')
                df_cases['Lon'] = pd.to_numeric(df_cases['Lon'], errors='coerce')

            tab1, tab2 = st.tabs(["🎯 YZ ERKEN UYARI (Mekan + Zaman Radarı)", "📊 TARİHSEL ANALİZ"])
            
            with tab1:
                six_months_ago = latest_date - pd.DateOffset(months=5) 
                target_date = latest_date + pd.DateOffset(months=1)
                start_str, end_str, target_str = f"{aylar[six_months_ago.month]} {six_months_ago.year}", f"{aylar[latest_date.month]} {latest_date.year}", f"{aylar[target_date.month]} {target_date.year}"

                # Son 6 ay vakalarını al ve ZAMAN AĞIRLIĞI (Time Decay) Hesapla
                recent_cases = df_cases[df_cases['Tarih'] >= (latest_date - pd.DateOffset(months=6))].copy()
                recent_cases_geo = recent_cases.dropna(subset=['Lat', 'Lon']).copy()
                
                # YENİ: Vaka üzerinden geçen gün sayısına göre ağırlık hesaplama (Yarı ömür = 30 gün)
                recent_cases_geo['Gun_Farki'] = (latest_date - recent_cases_geo['Tarih']).dt.days
                recent_cases_geo['Gun_Farki'] = recent_cases_geo['Gun_Farki'].apply(lambda x: 0 if x < 0 else x)
                recent_cases_geo['Vaka_Agirligi'] = 0.5 ** (recent_cases_geo['Gun_Farki'] / 30.0)

                # Nüfus, Aşı ve Koordinat Birleştirme
                df_pop['Target_Pop'] = pd.to_numeric(df_pop['Bebek Sayısı'], errors='coerce').fillna(0) + pd.to_numeric(df_pop['Çocuk Sayısı'], errors='coerce').fillna(0)
                df_vax['Toplam Aşılama Hızı'] = pd.to_numeric(df_vax['Toplam Aşılama Hızı'], errors='coerce')
                df_pop['Kurum_Temiz'] = df_pop['Kurum Adı'].astype(str).str.strip().str.upper()
                df_vax['Kurum_Temiz'] = df_vax['Kurum Adı'].astype(str).str.strip().str.upper()
                df_geo['Kurum_Temiz'] = df_geo['Birim Adı'].astype(str).str.strip().str.upper()
                
                df_merged = pd.merge(df_pop[['Kurum_Temiz', 'İlçe', 'Kurum Adı', 'Target_Pop']], df_vax[['Kurum_Temiz', 'Toplam Aşılama Hızı']], on='Kurum_Temiz', how='inner')
                df_merged = pd.merge(df_merged, df_geo[['Kurum_Temiz', 'Lat', 'Lon']], on='Kurum_Temiz', how='left')
                
                df_merged['Unvax_Rate'] = 100 - df_merged['Toplam Aşılama Hızı']
                df_merged['Korunmasız_Cocuk'] = (df_merged['Target_Pop'] * df_merged['Unvax_Rate'] / 100).fillna(0).astype(int)
                df_clean = df_merged[(df_merged['İlçe'].notna()) & (df_merged['İlçe'] != 'TUM') & (df_merged['İlçe'] != 'NAN')].copy()

                # --- 3 KM İÇİNDEKİ "ZAMAN AĞIRLIKLI" VAKA YÜKÜNÜ HESAPLAMA ---
                vaka_lat_array = recent_cases_geo['Lat'].values
                vaka_lon_array = recent_cases_geo['Lon'].values
                vaka_weight_array = recent_cases_geo['Vaka_Agirligi'].values
                
                def calculate_3km_weighted_cases(row):
                    if pd.isna(row['Lat']) or pd.isna(row['Lon']):
                        return 0.0
                    distances = haversine_vectorized(row['Lat'], row['Lon'], vaka_lat_array, vaka_lon_array)
                    # Sadece 3 km içindekilerin "Zaman Ağırlıklarını" topla
                    return np.sum(vaka_weight_array[distances <= 3.0])

                df_clean['Cember_Vaka_Yuk_3KM'] = df_clean.apply(calculate_3km_weighted_cases, axis=1).round(1)
                
                # --- YZ RİSK SKORU ---
                max_vuln = df_clean['Korunmasız_Cocuk'].max()
                max_cases = df_clean['Cember_Vaka_Yuk_3KM'].max()
                
                df_clean['Vuln_Score'] = df_clean['Korunmasız_Cocuk'] / max_vuln if max_vuln > 0 else 0
                df_clean['Case_Score'] = df_clean['Cember_Vaka_Yuk_3KM'] / max_cases if max_cases > 0 else 0
                df_clean['Ham_Risk'] = ((df_clean['Vuln_Score'] * 0.5) + (df_clean['Case_Score'] * 0.5)) * 100
                
                df_clean['Esik_Farki'] = 95 - df_clean['Toplam Aşılama Hızı']
                df_clean['Esik_Farki'] = df_clean['Esik_Farki'].apply(lambda x: x if x > 0 else 0)
                df_clean['Ceza_Puani'] = (df_clean['Esik_Farki'] ** 1.3) * 0.4 
                
                df_clean['Risk_Skoru'] = df_clean['Ham_Risk'] + df_clean['Ceza_Puani']
                df_clean['Risk_Skoru'] = df_clean['Risk_Skoru'].apply(lambda x: 100 if x > 100 else x).round(1)
                
                df_final = df_clean[df_clean['Target_Pop'] > 50].sort_values('Risk_Skoru', ascending=False)
                df_table = df_final[['İlçe', 'Kurum Adı', 'Target_Pop', 'Toplam Aşılama Hızı', 'Korunmasız_Cocuk', 'Cember_Vaka_Yuk_3KM', 'Risk_Skoru']].copy()
                df_table.columns = ['İlçe', 'Aile Hekimliği Birimi', 'Hedef Nüfus', 'Aşı Hızı (%)', 'Korumasız Çocuk', '3KM Aktif Vaka Yükü (Zaman Ağırlıklı)', 'YZ Risk Skoru']
                
                # Ekran Çıktıları
                st.info(f"🎯 **Zaman Zayıflatmalı Mekansal Analiz:** Algoritma 3 KM çemberindeki eski vakaların puanını düşürüp, taze vakalara odaklanarak {target_str} ayının en sıcak hedeflerini belirledi.")
                st.warning("💡 **Neden Küsuratlı Vaka Sayıları Var?** Çünkü sistem vakaları tek tek saymaz, tehdit ağırlıklarını toplar. 1 ay önceki bir vaka 0.5 puan değerindedir. Sayı ne kadar yüksekse, taze vaka o kadar fazladır.")
                
                col1, col2, col3 = st.columns(3)
                col1.metric(f"Toplam Vaka İhbarı ({start_str}-{end_str})", len(recent_cases))
                col2.metric("İl Geneli Korumasız Çocuk", f"{df_table['Korumasız Çocuk'].sum():,}")
                col3.metric(f"En Kritik Merkez ({target_str})", df_table.iloc[0]['İlçe'] if not df_table.empty else "Veri Yok")

                # Harita
                st.markdown("---")
                st.subheader("🗺️ Taktik Sürveyans Haritası")
                fig_map = go.Figure()
                fig_map.add_trace(go.Densitymapbox(lat=recent_cases_geo['Lat'], lon=recent_cases_geo['Lon'], z=recent_cases_geo['Vaka_Agirligi'],
                                                   radius=12, colorscale='Inferno', name='Taze Vaka Yoğunluğu', opacity=0.7))
                top_ahb = df_final.head(30).dropna(subset=['Lat', 'Lon'])
                hover_texts = top_ahb['Kurum Adı'] + "<br>Zaman Ağırlıklı Vaka Yükü: " + top_ahb['Cember_Vaka_Yuk_3KM'].astype(str) + "<br>Skor: " + top_ahb['Risk_Skoru'].astype(str)
                fig_map.add_trace(go.Scattermapbox(lat=top_ahb['Lat'], lon=top_ahb['Lon'], mode='markers', 
                                                   marker=dict(size=14, color='cyan', opacity=0.9, symbol='circle'), 
                                                   text=hover_texts, name='Kritik ASM Merkezleri', hoverinfo='text'))
                fig_map.update_layout(mapbox_style="carto-darkmatter", mapbox_center_lon=28.97, mapbox_center_lat=41.05, 
                                      mapbox_zoom=9.5, margin={"r":0,"t":0,"l":0,"b":0})
                st.plotly_chart(fig_map, use_container_width=True)

                # Tablo
                st.markdown("---")
                st.subheader(f"🔴 Nokta Atışı Müdahale Listesi ({target_str} Ayı)")
                def highlight_risk(val):
                    color = '#ff4b4b' if val > 80 else '#ffa500' if val > 60 else ''
                    return f'background-color: {color}'
                st.dataframe(df_table.head(30).style.applymap(highlight_risk, subset=['YZ Risk Skoru']).format({"Aşı Hızı (%)": "{:.1f}", "YZ Risk Skoru": "{:.1f}"}), use_container_width=True)

            with tab2:
                st.info("Bu sayfa, yüklediğiniz vaka listesindeki tüm yılları (2022'den bugüne) kapsayan makro epidemiyolojik trendleri gösterir.")
                df_cases['Yıl_Ay'] = df_cases['Tarih'].dt.to_period('M').astype(str)
                epi_data = df_cases.groupby('Yıl_Ay').size().reset_index(name='Vaka Sayısı')
                fig_epi = px.line(epi_data[epi_data['Yıl_Ay'] != 'NaT'], x='Yıl_Ay', y='Vaka Sayısı', markers=True, color_discrete_sequence=['#d62728'])
                st.plotly_chart(fig_epi, use_container_width=True)

        except Exception as e:
            st.error(f"Veri işlenirken hata oluştu. Lütfen dosyaları kontrol edin. Hata: {e}")
else:
    st.info("👆 Lütfen analiz edilecek 4 dosyayı da sol menüden yükleyin.")
