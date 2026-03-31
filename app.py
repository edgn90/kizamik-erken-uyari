import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

# Sayfa Ayarları
st.set_page_config(page_title="Kızamık YZ Sürveyans Radarı", page_icon="🧬", layout="wide")

st.title("🧬 Kızamık YZ Sürveyans Radarı (V6: Backtesting Entegreli)")
st.markdown("Mekansal Analiz (3KM), Üstel Zaman Zayıflatması (Time Decay) ve **Geriye Dönük Kör Test (Backtesting)** yeteneklerine sahip tam teşekküllü epidemiyolojik model.")

# --- 1. YÜKLEME MODÜLÜ (SIDEBAR) ---
st.sidebar.header("📂 Veri Yükleme Paneli")
file_cases = st.sidebar.file_uploader("1. Vaka Listesi (Kızamık.xlsx/csv)", type=["csv", "xlsx"])
file_pop = st.sidebar.file_uploader("2. Nüfus Verisi (Nüfus.xlsx/csv)", type=["csv", "xlsx"])
file_vax = st.sidebar.file_uploader("3. Aşı Performansı (KKK.xlsx/csv)", type=["csv", "xlsx"])
file_geo = st.sidebar.file_uploader("4. AHB Koordinatları (Geocoded.xlsx/csv)", type=["csv", "xlsx"])

aylar = {1: 'Ocak', 2: 'Şubat', 3: 'Mart', 4: 'Nisan', 5: 'Mayıs', 6: 'Haziran', 
         7: 'Temmuz', 8: 'Ağustos', 9: 'Eylül', 10: 'Ekim', 11: 'Kasım', 12: 'Aralık'}

# Haversine Formülü
def haversine_vectorized(lat1, lon1, lat2_array, lon2_array):
    R = 6371.0
    lat1, lon1 = np.radians(lat1), np.radians(lon1)
    lat2_array, lon2_array = np.radians(lat2_array), np.radians(lon2_array)
    dlat = lat2_array - lat1
    dlon = lon2_array - lon1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1) * np.cos(lat2_array) * np.sin(dlon/2.0)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return R * c

# Ortak Risk Hesaplama Fonksiyonu (Hem Canlı hem Test için kullanılacak)
def calculate_risk_scores(recent_cases, df_pop, df_vax, df_geo, target_date):
    # Veri Hazırlığı
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

    # Zaman Zayıflatması (Time Decay)
    recent_cases['Gun_Farki'] = (target_date - recent_cases['Tarih']).dt.days
    recent_cases['Gun_Farki'] = recent_cases['Gun_Farki'].apply(lambda x: 0 if x < 0 else x)
    recent_cases['Vaka_Agirligi'] = 0.5 ** (recent_cases['Gun_Farki'] / 30.0)

    recent_cases_geo = recent_cases.dropna(subset=['Lat', 'Lon'])
    vaka_lat_array = recent_cases_geo['Lat'].values
    vaka_lon_array = recent_cases_geo['Lon'].values
    vaka_weight_array = recent_cases_geo['Vaka_Agirligi'].values

    def calculate_3km_weighted(row):
        if pd.isna(row['Lat']) or pd.isna(row['Lon']): return 0.0
        distances = haversine_vectorized(row['Lat'], row['Lon'], vaka_lat_array, vaka_lon_array)
        return np.sum(vaka_weight_array[distances <= 3.0])

    df_clean['Cember_Vaka_Yuk'] = df_clean.apply(calculate_3km_weighted, axis=1).round(1)

    # Skorlama
    max_vuln = df_clean['Korunmasız_Cocuk'].max()
    max_cases = df_clean['Cember_Vaka_Yuk'].max()
    df_clean['Vuln_Score'] = df_clean['Korunmasız_Cocuk'] / max_vuln if max_vuln > 0 else 0
    df_clean['Case_Score'] = df_clean['Cember_Vaka_Yuk'] / max_cases if max_cases > 0 else 0
    df_clean['Ham_Risk'] = ((df_clean['Vuln_Score'] * 0.5) + (df_clean['Case_Score'] * 0.5)) * 100
    
    df_clean['Esik_Farki'] = 95 - df_clean['Toplam Aşılama Hızı']
    df_clean['Esik_Farki'] = df_clean['Esik_Farki'].apply(lambda x: x if x > 0 else 0)
    df_clean['Ceza_Puani'] = (df_clean['Esik_Farki'] ** 1.3) * 0.4 
    
    df_clean['Risk_Skoru'] = df_clean['Ham_Risk'] + df_clean['Ceza_Puani']
    df_clean['Risk_Skoru'] = df_clean['Risk_Skoru'].apply(lambda x: 100 if x > 100 else x).round(1)
    
    return df_clean[df_clean['Target_Pop'] > 50].sort_values('Risk_Skoru', ascending=False)


# --- ANA İŞLEYİŞ ---
if file_cases and file_pop and file_vax and file_geo:
    with st.spinner('Yapay Zeka Modülleri Yükleniyor...'):
        try:
            # Verileri Oku
            df_cases = pd.read_csv(file_cases) if file_cases.name.endswith('.csv') else pd.read_excel(file_cases)
            df_pop = pd.read_csv(file_pop) if file_pop.name.endswith('.csv') else pd.read_excel(file_pop)
            df_vax = pd.read_csv(file_vax) if file_vax.name.endswith('.csv') else pd.read_excel(file_vax)
            df_geo = pd.read_csv(file_geo) if file_geo.name.endswith('.csv') else pd.read_excel(file_geo)

            df_cases['Tarih'] = pd.to_datetime(df_cases['Tarih'], errors='coerce')
            latest_date = df_cases['Tarih'].max()
            if 'Lat' in df_cases.columns and 'Lon' in df_cases.columns:
                df_cases['Lat'] = pd.to_numeric(df_cases['Lat'], errors='coerce')
                df_cases['Lon'] = pd.to_numeric(df_cases['Lon'], errors='coerce')

            tab1, tab2, tab3 = st.tabs(["🎯 YZ ERKEN UYARI (Canlı Veri)", "📊 TARİHSEL ANALİZ", "🧪 BACKTESTING (Model Sınama)"])
            
            # ==========================================
            # TAB 1: YZ ERKEN UYARI (Mevcut Durum)
            # ==========================================
            with tab1:
                six_months_ago = latest_date - pd.DateOffset(months=5)
                recent_cases = df_cases[df_cases['Tarih'] >= (latest_date - pd.DateOffset(months=6))].copy()
                
                df_final = calculate_risk_scores(recent_cases, df_pop.copy(), df_vax.copy(), df_geo.copy(), latest_date)
                
                target_str = f"{aylar[(latest_date + pd.DateOffset(months=1)).month]} {(latest_date + pd.DateOffset(months=1)).year}"
                
                st.info(f"🎯 **Canlı Radar:** Son 6 ayın ivmesiyle **{target_str}** ayı hedefleri belirlendi.")
                st.dataframe(df_final[['İlçe', 'Kurum Adı', 'Target_Pop', 'Toplam Aşılama Hızı', 'Korunmasız_Cocuk', 'Cember_Vaka_Yuk', 'Risk_Skoru']].head(30), use_container_width=True)

            # ==========================================
            # TAB 2: TARİHSEL ANALİZ
            # ==========================================
            with tab2:
                df_cases['Yıl_Ay'] = df_cases['Tarih'].dt.to_period('M').astype(str)
                epi_data = df_cases.groupby('Yıl_Ay').size().reset_index(name='Vaka Sayısı')
                st.plotly_chart(px.line(epi_data[epi_data['Yıl_Ay'] != 'NaT'], x='Yıl_Ay', y='Vaka Sayısı', markers=True, title="Salgın Eğrisi"), use_container_width=True)

            # ==========================================
            # TAB 3: BACKTESTING (MODELİ KANITLAMA)
            # ==========================================
            with tab3:
                st.markdown("### 🧪 Model Doğrulama ve Kör Test (Backtesting)")
                st.markdown("Geçmiş bir tarihi seçin. Sistem o tarihten sonrasını bilmediğini varsayarak bir tahmin listesi oluşturacak, ardından bu tahmini **o ay gerçekten çıkan vakalarla** harita üzerinde çarpıştırıp modelin doğruluk oranını hesaplayacaktır.")
                
                # Sınanabilecek ayları bul (En az 6 ay geçmişi olanlar)
                min_date = df_cases['Tarih'].min() + pd.DateOffset(months=6)
                valid_months = pd.date_range(start=min_date, end=latest_date, freq='M').strftime('%Y-%m').tolist()
                
                test_month_str = st.selectbox("Sınamak İstediğiniz Gelecek Ayı (Hedef Ay) Seçin:", valid_months[::-1])
                
                if st.button("🚀 Kör Testi Başlat (Backtest)", type="primary"):
                    with st.spinner(f"{test_month_str} tarihi için zaman makinesi çalıştırılıyor..."):
                        # Tarih sınırlarını belirle
                        target_start = pd.to_datetime(test_month_str)
                        target_end = target_start + pd.offsets.MonthEnd(1)
                        context_end = target_start - pd.Timedelta(days=1)
                        context_start = context_end - pd.DateOffset(months=6)
                        
                        # Veriyi böl (Eğitim Seti ve Gerçek Set)
                        context_cases = df_cases[(df_cases['Tarih'] >= context_start) & (df_cases['Tarih'] <= context_end)].copy()
                        target_cases = df_cases[(df_cases['Tarih'] >= target_start) & (df_cases['Tarih'] <= target_end)].dropna(subset=['Lat', 'Lon']).copy()
                        
                        if len(target_cases) == 0:
                            st.warning(f"{test_month_str} ayında gerçekleşmiş hiç vaka kaydı yok. Sınama yapılamadı.")
                        else:
                            # 1. Modeli Çalıştır (Sadece geçmiş veriyi kullanarak)
                            predicted_df = calculate_risk_scores(context_cases, df_pop.copy(), df_vax.copy(), df_geo.copy(), context_end)
                            
                            # En riskli 30 merkezi al
                            top_30_predicted = predicted_df.head(30).dropna(subset=['Lat', 'Lon'])
                            top_lats = top_30_predicted['Lat'].values
                            top_lons = top_30_predicted['Lon'].values
                            
                            # 2. Gerçekliği Kontrol Et (Hit Rate)
                            hits = 0
                            hit_cases_lat, hit_cases_lon = [], []
                            miss_cases_lat, miss_cases_lon = [], []
                            
                            for _, row in target_cases.iterrows():
                                dists = haversine_vectorized(row['Lat'], row['Lon'], top_lats, top_lons)
                                if np.any(dists <= 3.0): # Eğer vaka, öngörülen 30 merkezin herhangi birinin 3KM içindeyse
                                    hits += 1
                                    hit_cases_lat.append(row['Lat'])
                                    hit_cases_lon.append(row['Lon'])
                                else:
                                    miss_cases_lat.append(row['Lat'])
                                    miss_cases_lon.append(row['Lon'])
                            
                            accuracy = (hits / len(target_cases)) * 100
                            
                            # 3. Test Sonuçlarını Ekrana Bas
                            st.success(f"✅ Test Tamamlandı! Dönem: {test_month_str}")
                            st.markdown("---")
                            
                            col_a, col_b, col_c = st.columns(3)
                            col_a.metric(f"Gerçekleşen Toplam Vaka", len(target_cases))
                            col_b.metric("Radarımızın Yakaladığı Vaka", hits)
                            col_c.metric("Modelin İsabet Oranı (Accuracy)", f"%{accuracy:.1f}")
                            
                            # 4. Kanıt Haritası (Kör Test Sonucu)
                            st.markdown("#### 🗺️ Çarpışma Haritası (Tahminler vs Gerçekleşenler)")
                            st.markdown("Mavi İğneler: Modelin 1 ay önceden işaretlediği **Kırmızı Alarm Noktaları**.")
                            st.markdown("Kırmızı Noktalar: O ay gerçekten çıkan **Vakalar**.")
                            
                            fig_test = go.Figure()
                            
                            # Tahmin Edilen ASM'ler (Mavi Radar)
                            hover_pred = top_30_predicted['Kurum Adı'] + "<br>Model Skoru: " + top_30_predicted['Risk_Skoru'].astype(str)
                            fig_test.add_trace(go.Scattermapbox(lat=top_lats, lon=top_lons, mode='markers', 
                                                               marker=dict(size=25, color='rgba(0, 255, 255, 0.3)'), 
                                                               name='Tahmin Edilen 3KM Radar Alanları', hoverinfo='none'))
                            fig_test.add_trace(go.Scattermapbox(lat=top_lats, lon=top_lons, mode='markers', 
                                                               marker=dict(size=8, color='cyan'), 
                                                               text=hover_pred, name='Tahmin Merkezleri', hoverinfo='text'))
                            
                            # Radar Tarafından Yakalanan Gerçek Vakalar (Yeşilimsi Kırmızı)
                            if hits > 0:
                                fig_test.add_trace(go.Scattermapbox(lat=hit_cases_lat, lon=hit_cases_lon, mode='markers', 
                                                                   marker=dict(size=8, color='#00ff00'), 
                                                                   name='Radar Tarafından Yakalanan Vakalar (Başarı)'))
                            
                            # Radardan Kaçan Gerçek Vakalar (Kırmızı)
                            if len(miss_cases_lat) > 0:
                                fig_test.add_trace(go.Scattermapbox(lat=miss_cases_lat, lon=miss_cases_lon, mode='markers', 
                                                                   marker=dict(size=8, color='#ff0000'), 
                                                                   name='Radardan Kaçan Vakalar (Hata)'))
                                                                   
                            fig_test.update_layout(mapbox_style="carto-darkmatter", mapbox_center_lon=28.97, mapbox_center_lat=41.05, 
                                                  mapbox_zoom=10, margin={"r":0,"t":0,"l":0,"b":0},
                                                  legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01))
                            st.plotly_chart(fig_test, use_container_width=True)

        except Exception as e:
            st.error(f"Hata oluştu: {e}")
else:
    st.info("👆 Lütfen analiz edilecek 4 dosyayı sol menüden yükleyin.")
