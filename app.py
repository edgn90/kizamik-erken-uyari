import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import re
import os
from datetime import datetime

# Makine Öğrenmesi Kütüphanesi (Holt-Winters için)
try:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
except ImportError:
    ExponentialSmoothing = None

# Sayfa Ayarları
st.set_page_config(page_title="Kızamık YZ Sürveyans Radarı", page_icon="🎯", layout="wide")

st.title("🎯 Kızamık YZ Sürveyans Radarı (V9.3: 4 Modüllü Entegre Sistem)")
st.markdown("Nüfus ve Koordinat altyapıları sisteme gömülmüştür. Sadece dinamik değişen **Vaka** ve **Aşı** verilerini yükleyiniz.")

# --- 1. YÜKLEME MODÜLÜ (SIDEBAR) ---
st.sidebar.header("📂 Aylık Dinamik Veri Yükleme")
file_cases = st.sidebar.file_uploader("1. Vaka Listesi (Kızamık.xlsx/csv)", type=["csv", "xlsx"])
file_vax = st.sidebar.file_uploader("2. Aşı Performansı (KKK.xlsx/csv)", type=["csv", "xlsx"])

aylar = {1: 'Ocak', 2: 'Şubat', 3: 'Mart', 4: 'Nisan', 5: 'Mayıs', 6: 'Haziran', 
         7: 'Temmuz', 8: 'Ağustos', 9: 'Eylül', 10: 'Ekim', 11: 'Kasım', 12: 'Aralık'}

# --- YARDIMCI FONKSİYONLAR ---
def tr_upper(text):
    """Türkçe karakterlere duyarlı büyük harf dönüştürücü."""
    if pd.isna(text): return ""
    text = str(text).replace('i', 'İ').replace('ı', 'I').replace('i̇', 'İ')
    return text.upper().strip()

def haversine_vectorized(lat1, lon1, lat2_array, lon2_array):
    R = 6371.0
    lat1, lon1 = np.radians(lat1), np.radians(lon1)
    lat2_array, lon2_array = np.radians(lat2_array), np.radians(lon2_array)
    dlat = lat2_array - lat1
    dlon = lon2_array - lon1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1) * np.cos(lat2_array) * np.sin(dlon/2.0)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return R * c

def extract_ahb_no(text):
    nums = re.findall(r'\d+', str(text))
    return str(int(nums[0])) if nums else "0" 

def calculate_risk_scores(recent_cases, df_pop, df_vax, df_geo, target_date):
    df_pop['Target_Pop'] = pd.to_numeric(df_pop['Bebek Sayısı'], errors='coerce').fillna(0) + pd.to_numeric(df_pop['Çocuk Sayısı'], errors='coerce').fillna(0)
    df_vax['Toplam Aşılama Hızı'] = pd.to_numeric(df_vax['Toplam Aşılama Hızı'], errors='coerce')
    
    # Akıllı Eşleşme
    df_pop['İlçe_Eslenik'] = df_pop['İlçe'].apply(tr_upper)
    df_pop['AHB_No'] = df_pop['Kurum Adı'].apply(extract_ahb_no)
    
    df_vax['İlçe_Eslenik'] = df_vax['İlçe'].apply(tr_upper)
    df_vax['AHB_No'] = df_vax['Kurum Adı'].apply(extract_ahb_no)
    
    df_merged = pd.merge(df_pop[['İlçe_Eslenik', 'AHB_No', 'İlçe', 'Kurum Adı', 'Target_Pop']], 
                         df_vax[['İlçe_Eslenik', 'AHB_No', 'Toplam Aşılama Hızı']], 
                         on=['İlçe_Eslenik', 'AHB_No'], how='inner')
    
    col_name = 'Birim Adı' if 'Birim Adı' in df_geo.columns else 'Kurum Adı'
    df_geo['İlçe_Eslenik'] = df_geo['İlçe'].apply(tr_upper) if 'İlçe' in df_geo.columns else "BİLİNMİYOR"
    df_geo['AHB_No'] = df_geo[col_name].apply(extract_ahb_no)
    
    df_geo_unique = df_geo.dropna(subset=['Lat', 'Lon']).drop_duplicates(subset=['İlçe_Eslenik', 'AHB_No'])
    
    df_clean = pd.merge(df_merged, df_geo_unique[['İlçe_Eslenik', 'AHB_No', 'Lat', 'Lon']], on=['İlçe_Eslenik', 'AHB_No'], how='left')
    df_clean = df_clean[(df_clean['İlçe'].notna()) & (df_clean['İlçe'] != 'TUM') & (df_clean['İlçe'] != 'NAN')].copy()
    
    df_clean['Unvax_Rate'] = 100 - df_clean['Toplam Aşılama Hızı']
    df_clean['Korunmasız_Cocuk'] = (df_clean['Target_Pop'] * df_clean['Unvax_Rate'] / 100).fillna(0).astype(int)

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
if file_cases and file_vax:
    with st.spinner('Sistem Başlatılıyor ve Gömülü Altyapı Verileri Okunuyor...'):
        try:
            # 1. Kullanıcının Yüklediği Değişken Dosyalar
            df_cases = pd.read_csv(file_cases) if file_cases.name.endswith('.csv') else pd.read_excel(file_cases)
            df_vax = pd.read_csv(file_vax) if file_vax.name.endswith('.csv') else pd.read_excel(file_vax)

            # 2. SİSTEME GÖMÜLÜ SABİT DOSYALARI OTOMATİK OKUMA
            if os.path.exists('ahb_geocoded.csv'): df_geo = pd.read_csv('ahb_geocoded.csv')
            elif os.path.exists('ahb_geocoded.xlsx'): df_geo = pd.read_excel('ahb_geocoded.xlsx')
            else:
                st.error("🚨 KRİTİK HATA: 'ahb_geocoded' (Koordinat) dosyası sistemde bulunamadı!")
                st.stop()

            if os.path.exists('nufus_verisi.csv'): df_pop = pd.read_csv('nufus_verisi.csv')
            elif os.path.exists('nufus_verisi.xlsx'): df_pop = pd.read_excel('nufus_verisi.xlsx')
            else:
                st.error("🚨 KRİTİK HATA: 'nufus_verisi' (Nüfus) dosyası sistemde bulunamadı!")
                st.stop()

            df_cases['Tarih'] = pd.to_datetime(df_cases['Tarih'], errors='coerce')
            latest_date = df_cases['Tarih'].max()
            if 'Lat' in df_cases.columns and 'Lon' in df_cases.columns:
                df_cases['Lat'] = pd.to_numeric(df_cases['Lat'], errors='coerce')
                df_cases['Lon'] = pd.to_numeric(df_cases['Lon'], errors='coerce')

            # --- SEKMELER (4 ADET OLARAK GÜNCELLENDİ) ---
            tab1, tab2, tab3, tab4 = st.tabs([
                "🎯 YZ ERKEN UYARI", 
                "📊 TARİHSEL ANALİZ", 
                "📈 HOLT-WINTERS GELECEK TAHMİNİ", 
                "🧪 BACKTESTING (Model Sınama)"
            ])
            
            # ==========================================
            # TAB 1: YZ ERKEN UYARI
            # ==========================================
            with tab1:
                recent_cases = df_cases[df_cases['Tarih'] >= (latest_date - pd.DateOffset(months=6))].copy()
                df_final = calculate_risk_scores(recent_cases, df_pop.copy(), df_vax.copy(), df_geo.copy(), latest_date)
                
                target_str = f"{aylar[(latest_date + pd.DateOffset(months=1)).month]} {(latest_date + pd.DateOffset(months=1)).year}"
                st.info(f"🎯 **Canlı Radar:** Gömülü altyapı kullanılarak **{target_str}** ayı hedefleri belirlendi.")
                
                def highlight_risk(val):
                    color = '#ff4b4b' if val > 80 else '#ffa500' if val > 60 else ''
                    return f'background-color: {color}'
                
                st.dataframe(df_final[['İlçe', 'Kurum Adı', 'Target_Pop', 'Toplam Aşılama Hızı', 'Korunmasız_Cocuk', 'Cember_Vaka_Yuk', 'Risk_Skoru']].head(30).style.map(highlight_risk, subset=['Risk_Skoru']).format({"Toplam Aşılama Hızı": "{:.1f}", "Risk_Skoru": "{:.1f}"}), use_container_width=True)

                st.markdown("---")
                st.subheader("🗺️ Taktik Sürveyans Haritası")
                fig_map = go.Figure()
                recent_cases_geo = recent_cases.dropna(subset=['Lat', 'Lon'])
                
                if not recent_cases_geo.empty:
                    recent_cases_geo['Gun_Farki'] = (latest_date - recent_cases_geo['Tarih']).dt.days
                    recent_cases_geo['Gun_Farki'] = recent_cases_geo['Gun_Farki'].apply(lambda x: 0 if x < 0 else x)
                    recent_cases_geo['Vaka_Agirligi'] = 0.5 ** (recent_cases_geo['Gun_Farki'] / 30.0)
                    fig_map.add_trace(go.Densitymapbox(lat=recent_cases_geo['Lat'], lon=recent_cases_geo['Lon'], z=recent_cases_geo['Vaka_Agirligi'],
                                                       radius=12, colorscale='Inferno', name='Taze Vaka Yoğunluğu', opacity=0.7))
                
                top_ahb = df_final.head(30).dropna(subset=['Lat', 'Lon'])
                if not top_ahb.empty:
                    hover_texts = top_ahb['Kurum Adı'] + "<br>Zaman Ağırlıklı Vaka Yükü: " + top_ahb['Cember_Vaka_Yuk'].astype(str) + "<br>Skor: " + top_ahb['Risk_Skoru'].astype(str)
                    fig_map.add_trace(go.Scattermapbox(lat=top_ahb['Lat'], lon=top_ahb['Lon'], mode='markers', 
                                                       marker=dict(size=14, color='cyan', opacity=0.9, symbol='circle'), 
                                                       text=hover_texts, name='Kritik ASM Merkezleri', hoverinfo='text'))
                else:
                    st.warning("⚠️ Mavi iğneler çizilemedi. Nüfus ve Koordinat eşleşmesi başarısız.")
                
                fig_map.update_layout(mapbox_style="carto-darkmatter", mapbox_center_lon=28.97, mapbox_center_lat=41.05, 
                                      mapbox_zoom=9.5, margin={"r":0,"t":0,"l":0,"b":0})
                st.plotly_chart(fig_map, use_container_width=True)

            # ==========================================
            # TAB 2: TARİHSEL ANALİZ
            # ==========================================
            with tab2:
                st.markdown("### 📊 Tarihsel Salgın Eğrisi")
                st.info("Bu grafik, yüklediğiniz verilerdeki geçmiş ayların genel salgın eğilimini gösterir.")
                
                df_cases_valid = df_cases.dropna(subset=['Tarih']).copy()
                df_cases_valid['Yıl_Ay'] = df_cases_valid['Tarih'].dt.strftime('%Y-%m') 
                epi_data = df_cases_valid.groupby('Yıl_Ay').size().reset_index(name='Vaka Sayısı')
                st.plotly_chart(px.line(epi_data, x='Yıl_Ay', y='Vaka Sayısı', markers=True, title="Tarihsel Vaka Gelişimi"), use_container_width=True)

            # ==========================================
            # TAB 3: HOLT-WINTERS GELECEK TAHMİNİ
            # ==========================================
            with tab3:
                st.markdown("### 📈 Holt-Winters ile Mevsimsel Gelecek Projeksiyonu")
                st.markdown("Sistem, klasik epidemiyolojinin altın standardı olan Üstel Düzleştirme (Holt-Winters) modelini kullanarak geçmiş verilerinizdeki mevsimsel döngüleri öğrenir ve gelecek 6 ayın risk haritasını çıkarır.")
                
                if ExponentialSmoothing is None:
                    st.error("🚨 **Statsmodels Kütüphanesi Eksik!** Lütfen terminalinizde `pip install statsmodels` komutunu çalıştırın veya requirements.txt dosyanıza ekleyin.")
                else:
                    try:
                        # Pandas frekans hatasından kaçınmak için M/ME kontrolü
                        try:
                            ts_df = df_cases_valid.groupby(pd.Grouper(key='Tarih', freq='ME')).size()
                            idx = pd.date_range(ts_df.index.min(), latest_date, freq='ME')
                        except ValueError:
                            ts_df = df_cases_valid.groupby(pd.Grouper(key='Tarih', freq='M')).size()
                            idx = pd.date_range(ts_df.index.min(), latest_date, freq='M')
                            
                        ts_df = ts_df.reindex(idx, fill_value=0)
                        
                        if len(ts_df) < 24: 
                            st.warning("Holt-Winters algoritmasının salgının mevsimsel döngüsünü (yaz/kış farklarını) doğru öğrenebilmesi için sisteme en az 24 aylık geçmiş veri yüklemeniz tavsiye edilir.")
                        
                        with st.spinner("Holt-Winters Algoritması tarihsel döngüleri analiz ediyor..."):
                            model = ExponentialSmoothing(
                                ts_df, 
                                trend='add', 
                                seasonal='add', 
                                seasonal_periods=12 if len(ts_df) >= 24 else None,
                                initialization_method="estimated"
                            ).fit()
                            
                            forecast = model.forecast(6)
                            forecast = forecast.apply(lambda x: max(0, x)) 
                            
                            peak_date = forecast.idxmax()
                            peak_value = int(forecast.max())
                            
                            ay_adi = aylar.get(peak_date.month, str(peak_date.month))
                            yil = peak_date.year
                            
                            st.error(f"🚨 **ALGORİTMA ÖNGÖRÜSÜ:** Tarihsel trendler ve mevsimsel döngülere bakılırsa, önümüzdeki 6 ay içindeki en büyük risk **{ay_adi} {yil}** döneminde beklenmektedir. Bu ayda il genelinde tahmini vaka sayısının **{peak_value}** seviyelerine ulaşma potansiyeli vardır.")
                            
                            fig_hw = go.Figure()
                            
                            # GÖRSEL HATA BURADA ÇÖZÜLDÜ: Renk 'white' yerine '#1f77b4' (Mavi) yapıldı.
                            fig_hw.add_trace(go.Scatter(x=ts_df.index, y=ts_df.values, mode='lines+markers', name='Gerçekleşen Vakalar', line=dict(color='#1f77b4', width=2)))
                            
                            fig_hw.add_trace(go.Scatter(x=forecast.index, y=forecast.values, mode='lines+markers', name='Holt-Winters YZ Tahmini', line=dict(color='#00ff00', width=3, dash='dot')))
                            
                            fig_hw.update_layout(
                                title='Holt-Winters Algoritması ile 6 Aylık Epidemiyolojik Projeksiyon', 
                                xaxis_title='Zaman (Aylık)', 
                                yaxis_title='Vaka Sayısı', 
                                hovermode="x unified"
                            )
                            st.plotly_chart(fig_hw, use_container_width=True)
                            
                    except Exception as e:
                        st.error(f"Tahmin motorunda hata oluştu (Veriniz çok kısa veya düzensiz olabilir): {e}")

            # ==========================================
            # TAB 4: BACKTESTING
            # ==========================================
            with tab4:
                st.markdown("### 🧪 Model Doğrulama ve Kör Test (Backtesting)")
                min_date = df_cases['Tarih'].min() + pd.DateOffset(months=6)
                
                try:
                    valid_months = pd.date_range(start=min_date, end=latest_date, freq='ME').strftime('%Y-%m').tolist()
                except ValueError:
                    valid_months = pd.date_range(start=min_date, end=latest_date, freq='M').strftime('%Y-%m').tolist()

                test_month_str = st.selectbox("Sınamak İstediğiniz Gelecek Ayı Seçin:", valid_months[::-1])
                
                if st.button("🚀 Kör Testi Başlat (Backtest)", type="primary"):
                    with st.spinner("Zaman makinesi çalıştırılıyor..."):
                        target_start = pd.to_datetime(test_month_str)
                        target_end = target_start + pd.offsets.MonthEnd(1)
                        context_end = target_start - pd.Timedelta(days=1)
                        context_start = context_end - pd.DateOffset(months=6)
                        
                        context_cases = df_cases[(df_cases['Tarih'] >= context_start) & (df_cases['Tarih'] <= context_end)].copy()
                        target_cases = df_cases[(df_cases['Tarih'] >= target_start) & (df_cases['Tarih'] <= target_end)].dropna(subset=['Lat', 'Lon']).copy()
                        
                        if len(target_cases) == 0:
                            st.warning("Gerçekleşmiş vaka kaydı yok.")
                        else:
                            predicted_df = calculate_risk_scores(context_cases, df_pop.copy(), df_vax.copy(), df_geo.copy(), context_end)
                            top_30_predicted = predicted_df.head(30).dropna(subset=['Lat', 'Lon'])
                            
                            if top_30_predicted.empty:
                                st.error("Eşleşme hatası! Mavi merkezler bulunamıyor.")
                            else:
                                top_lats = top_30_predicted['Lat'].values
                                top_lons = top_30_predicted['Lon'].values
                                
                                hits = 0
                                hit_cases_lat, hit_cases_lon = [], []
                                miss_cases_lat, miss_cases_lon = [], []
                                
                                for _, row in target_cases.iterrows():
                                    dists = haversine_vectorized(row['Lat'], row['Lon'], top_lats, top_lons)
                                    if np.any(dists <= 3.0): 
                                        hits += 1
                                        hit_cases_lat.append(row['Lat'])
                                        hit_cases_lon.append(row['Lon'])
                                    else:
                                        miss_cases_lat.append(row['Lat'])
                                        miss_cases_lon.append(row['Lon'])
                                
                                accuracy = (hits / len(target_cases)) * 100
                                
                                st.success(f"✅ Test Tamamlandı! Dönem: {test_month_str}")
                                col_a, col_b, col_c = st.columns(3)
                                col_a.metric("Gerçekleşen Toplam Vaka", len(target_cases))
                                col_b.metric("Radarımızın Yakaladığı Vaka", hits)
                                col_c.metric("Modelin İsabet Oranı", f"%{accuracy:.1f}")
                                
                                st.markdown("#### 🗺️ Çarpışma Haritası (Tahminler vs Gerçekleşenler)")
                                st.markdown("Açık Mavi: Modelin 1 ay önce çizdiği 3KM radar çemberleri. Yeşil Noktalar: Radarın yakaladığı vakalar. Kırmızı Noktalar: Radarın dışına düşen vakalar.")
                                fig_test = go.Figure()
                                
                                hover_pred = top_30_predicted['Kurum Adı'] + "<br>Model Skoru: " + top_30_predicted['Risk_Skoru'].astype(str)
                                
                                fig_test.add_trace(go.Scattermapbox(lat=top_lats, lon=top_lons, mode='markers', 
                                                                   marker=dict(size=25, color='rgba(0, 255, 255, 0.3)'), 
                                                                   name='Tahmin Edilen 3KM Radar Alanları', hoverinfo='none'))
                                fig_test.add_trace(go.Scattermapbox(lat=top_lats, lon=top_lons, mode='markers', 
                                                                   marker=dict(size=8, color='cyan'), 
                                                                   text=hover_pred, name='Tahmin Merkezleri', hoverinfo='text'))
                                
                                if hits > 0:
                                    fig_test.add_trace(go.Scattermapbox(lat=hit_cases_lat, lon=hit_cases_lon, mode='markers', 
                                                                       marker=dict(size=8, color='#00ff00'), 
                                                                       name='Yakalanan Vakalar (Başarı)'))
                                
                                if len(miss_cases_lat) > 0:
                                    fig_test.add_trace(go.Scattermapbox(lat=miss_cases_lat, lon=miss_cases_lon, mode='markers', 
                                                                       marker=dict(size=8, color='#ff0000'), 
                                                                       name='Kaçan Vakalar (Hata)'))
                                                                       
                                fig_test.update_layout(mapbox_style="carto-darkmatter", mapbox_center_lon=28.97, mapbox_center_lat=41.05, 
                                                      mapbox_zoom=9.5, margin={"r":0,"t":0,"l":0,"b":0},
                                                      legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01))
                                st.plotly_chart(fig_test, use_container_width=True)

        except Exception as e:
            st.error(f"Hata oluştu: {e}")
else:
    st.info("👆 Lütfen sistemin çalışması için aylık 'Vaka' ve 'Aşı' dosyalarını sol menüden yükleyin.")
