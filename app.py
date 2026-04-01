import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import re
import os
import io
from datetime import datetime

# Gelecek Tahmini Kütüphanesi
try:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
except ImportError:
    ExponentialSmoothing = None

# PDF Oluşturma Kütüphanesi
try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

# Sayfa Ayarları
st.set_page_config(page_title="Kızamık YZ Sürveyans Radarı", page_icon="🎯", layout="wide")

st.title("🎯 Kızamık YZ Sürveyans Radarı (V9.5: İleri Düzey Raporlama)")
st.markdown("Nüfus/Koordinat altyapıları gömülüdür. Risk eşiğini aşan merkezleri artık **Excel ve PDF** formatında tek tıkla indirebilirsiniz.")

# --- 1. YÜKLEME VE AYAR MODÜLÜ (SIDEBAR) ---
st.sidebar.header("📂 Aylık Dinamik Veri Yükleme")
file_cases = st.sidebar.file_uploader("1. Vaka Listesi (Kızamık.xlsx/csv)", type=["csv", "xlsx"])
file_vax = st.sidebar.file_uploader("2. Aşı Performansı (KKK.xlsx/csv)", type=["csv", "xlsx"])

st.sidebar.markdown("---")
st.sidebar.header("🎛️ Radar Ayarları")
risk_esigi = st.sidebar.slider("🚨 Kırmızı Alarm Eşiği (Risk Skoru)", min_value=40, max_value=100, value=70, step=5, 
                               help="Sadece bu puanın üzerindeki merkezler listeye ve raporlara dahil edilir.")

aylar = {1: 'Ocak', 2: 'Şubat', 3: 'Mart', 4: 'Nisan', 5: 'Mayıs', 6: 'Haziran', 
         7: 'Temmuz', 8: 'Ağustos', 9: 'Eylül', 10: 'Ekim', 11: 'Kasım', 12: 'Aralık'}

# --- YARDIMCI FONKSİYONLAR ---
def tr_upper(text):
    if pd.isna(text): return ""
    return str(text).replace('i', 'İ').replace('ı', 'I').replace('i̇', 'İ').upper().strip()

def clean_tr_chars(text):
    """PDF içindeki olası font hatalarını önlemek için Türkçe karakterleri standart Latin harflerine çevirir."""
    tr_map = {'ç':'c', 'ğ':'g', 'ı':'i', 'ö':'o', 'ş':'s', 'ü':'u', 'Ç':'C', 'Ğ':'G', 'İ':'I', 'Ö':'O', 'Ş':'S', 'Ü':'U'}
    res = str(text)
    for k, v in tr_map.items(): res = res.replace(k, v)
    return res

def haversine_vectorized(lat1, lon1, lat2_array, lon2_array):
    R = 6371.0
    lat1, lon1 = np.radians(lat1), np.radians(lon1)
    lat2_array, lon2_array = np.radians(lat2_array), np.radians(lon2_array)
    dlat = lat2_array - lat1; dlon = lon2_array - lon1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1) * np.cos(lat2_array) * np.sin(dlon/2.0)**2
    return R * (2 * np.arcsin(np.sqrt(a)))

def extract_ahb_no(text):
    nums = re.findall(r'\d+', str(text))
    return str(int(nums[0])) if nums else "0" 

def calculate_risk_scores(recent_cases, df_pop, df_vax, df_geo, target_date):
    df_pop['Target_Pop'] = pd.to_numeric(df_pop['Bebek Sayısı'], errors='coerce').fillna(0) + pd.to_numeric(df_pop['Çocuk Sayısı'], errors='coerce').fillna(0)
    df_vax['Toplam Aşılama Hızı'] = pd.to_numeric(df_vax['Toplam Aşılama Hızı'], errors='coerce')
    
    df_pop['İlçe_Eslenik'] = df_pop['İlçe'].apply(tr_upper)
    df_pop['AHB_No'] = df_pop['Kurum Adı'].apply(extract_ahb_no)
    df_vax['İlçe_Eslenik'] = df_vax['İlçe'].apply(tr_upper)
    df_vax['AHB_No'] = df_vax['Kurum Adı'].apply(extract_ahb_no)
    
    df_merged = pd.merge(df_pop[['İlçe_Eslenik', 'AHB_No', 'İlçe', 'Kurum Adı', 'Target_Pop']], df_vax[['İlçe_Eslenik', 'AHB_No', 'Toplam Aşılama Hızı']], on=['İlçe_Eslenik', 'AHB_No'], how='inner')
    
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
    vaka_lat_array, vaka_lon_array, vaka_weight_array = recent_cases_geo['Lat'].values, recent_cases_geo['Lon'].values, recent_cases_geo['Vaka_Agirligi'].values

    def calculate_3km_weighted(row):
        if pd.isna(row['Lat']) or pd.isna(row['Lon']): return 0.0
        return np.sum(vaka_weight_array[haversine_vectorized(row['Lat'], row['Lon'], vaka_lat_array, vaka_lon_array) <= 3.0])

    df_clean['Cember_Vaka_Yuk'] = df_clean.apply(calculate_3km_weighted, axis=1).round(1)

    max_vuln, max_cases = df_clean['Korunmasız_Cocuk'].max(), df_clean['Cember_Vaka_Yuk'].max()
    df_clean['Ham_Risk'] = ((df_clean['Korunmasız_Cocuk'] / max_vuln if max_vuln > 0 else 0) * 0.5 + (df_clean['Cember_Vaka_Yuk'] / max_cases if max_cases > 0 else 0) * 0.5) * 100
    df_clean['Ceza_Puani'] = (df_clean['Toplam Aşılama Hızı'].apply(lambda x: max(0, 95 - x)) ** 1.3) * 0.4 
    df_clean['Risk_Skoru'] = (df_clean['Ham_Risk'] + df_clean['Ceza_Puani']).apply(lambda x: min(100, x)).round(1)
    
    return df_clean[df_clean['Target_Pop'] > 50].sort_values('Risk_Skoru', ascending=False)

def create_pdf_report(dataframe, target_month_str):
    """Verilen DataFrame'i kusursuz bir PDF Tablosuna dönüştürür."""
    if FPDF is None: return None
    pdf = FPDF(orientation='L', unit='mm', format='A4') # Yatay (Landscape) geniş tablo için
    pdf.add_page()
    
    # Başlık
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(277, 10, txt=f"YAPAY ZEKA ERKEN UYARI RAPORU ({target_month_str})", ln=True, align='C')
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(277, 10, txt="Sahada oncelikli mudahale edilmesi gereken riskli merkezler listesi.", ln=True, align='C')
    pdf.ln(5)
    
    # Tablo Sütun Genişlikleri
    col_widths = [30, 80, 25, 25, 35, 35, 25] # Toplam 255mm
    headers = ["Ilce", "Kurum Adi", "Hedef Nufus", "Asi Hizi(%)", "Korunmasiz Cocuk", "Cevre Vaka Yuku", "Risk Skoru"]
    
    # Tablo Başlıkları
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(200, 220, 255) # Açık mavi arka plan
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 10, str(header), border=1, align='C', fill=True)
    pdf.ln()
    
    # Tablo Satırları
    pdf.set_font("Arial", '', 9)
    for _, row in dataframe.iterrows():
        pdf.cell(col_widths[0], 10, clean_tr_chars(row['İlçe']), border=1, align='C')
        pdf.cell(col_widths[1], 10, clean_tr_chars(row['Kurum Adı'])[:45], border=1, align='L') # Çok uzun isimleri kes
        pdf.cell(col_widths[2], 10, str(int(row['Target_Pop'])), border=1, align='C')
        pdf.cell(col_widths[3], 10, f"%{row['Toplam Aşılama Hızı']:.1f}", border=1, align='C')
        pdf.cell(col_widths[4], 10, str(int(row['Korunmasız_Cocuk'])), border=1, align='C')
        pdf.cell(col_widths[5], 10, f"{row['Cember_Vaka_Yuk']:.1f}", border=1, align='C')
        pdf.cell(col_widths[6], 10, f"{row['Risk_Skoru']:.1f}", border=1, align='C')
        pdf.ln()
        
    # PDF'i Byte olarak döndür
    return pdf.output(dest='S').encode('latin-1', 'ignore')

# --- ANA İŞLEYİŞ ---
if file_cases and file_vax:
    with st.spinner('Sistem Başlatılıyor ve Gömülü Altyapı Verileri Okunuyor...'):
        try:
            df_cases = pd.read_csv(file_cases) if file_cases.name.endswith('.csv') else pd.read_excel(file_cases)
            df_vax = pd.read_csv(file_vax) if file_vax.name.endswith('.csv') else pd.read_excel(file_vax)

            if os.path.exists('ahb_geocoded.csv'): df_geo = pd.read_csv('ahb_geocoded.csv')
            elif os.path.exists('ahb_geocoded.xlsx'): df_geo = pd.read_excel('ahb_geocoded.xlsx')
            else: st.error("🚨 KRİTİK HATA: Koordinat dosyası bulunamadı!"); st.stop()

            if os.path.exists('nufus_verisi.csv'): df_pop = pd.read_csv('nufus_verisi.csv')
            elif os.path.exists('nufus_verisi.xlsx'): df_pop = pd.read_excel('nufus_verisi.xlsx')
            else: st.error("🚨 KRİTİK HATA: Nüfus dosyası bulunamadı!"); st.stop()

            df_cases['Tarih'] = pd.to_datetime(df_cases['Tarih'], errors='coerce')
            latest_date = df_cases['Tarih'].max()
            if 'Lat' in df_cases.columns and 'Lon' in df_cases.columns:
                df_cases['Lat'] = pd.to_numeric(df_cases['Lat'], errors='coerce')
                df_cases['Lon'] = pd.to_numeric(df_cases['Lon'], errors='coerce')

            tab1, tab2, tab3, tab4 = st.tabs([
                "🎯 YZ ERKEN UYARI", 
                "📊 TARİHSEL ANALİZ", 
                "📈 HOLT-WINTERS GELECEK TAHMİNİ", 
                "🧪 BACKTESTING (Model Sınama)"
            ])
            
            # ==========================================
            # TAB 1: YZ ERKEN UYARI (DİNAMİK EŞİK & RAPORLAMA)
            # ==========================================
            with tab1:
                recent_cases = df_cases[df_cases['Tarih'] >= (latest_date - pd.DateOffset(months=6))].copy()
                df_final = calculate_risk_scores(recent_cases, df_pop.copy(), df_vax.copy(), df_geo.copy(), latest_date)
                
                # EŞİĞE GÖRE FİLTRELEME VE RAPORLAMA İÇİN ANA TABLOYU HAZIRLA
                top_ahb_df = df_final[df_final['Risk_Skoru'] >= risk_esigi].copy()
                top_ahb_geo = top_ahb_df.dropna(subset=['Lat', 'Lon'])
                
                target_month_str = f"{aylar[(latest_date + pd.DateOffset(months=1)).month]} {(latest_date + pd.DateOffset(months=1)).year}"
                st.info(f"🎯 **Taktik Radar:** {target_month_str} dönemi için Risk Skoru **{risk_esigi} ve üzeri** olan toplam **{len(top_ahb_geo)} merkez** tespit edildi.")
                
                # --- İNDİRME (EXPORT) BUTONLARI ---
                if not top_ahb_df.empty:
                    export_cols = ['İlçe', 'Kurum Adı', 'Target_Pop', 'Toplam Aşılama Hızı', 'Korunmasız_Cocuk', 'Cember_Vaka_Yuk', 'Risk_Skoru']
                    df_export = top_ahb_df[export_cols].copy()
                    
                    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
                    
                    # 1. EXCEL OLUŞTURMA
                    excel_buffer = io.BytesIO()
                    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                        df_export.to_excel(writer, index=False, sheet_name='Riskli Merkezler')
                    excel_data = excel_buffer.getvalue()
                    
                    col1.download_button(
                        label="📥 Excel Olarak İndir (.xlsx)", 
                        data=excel_data, 
                        file_name=f"Kizamik_Risk_Raporu_{target_month_str}.xlsx", 
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        type="primary"
                    )
                    
                    # 2. PDF OLUŞTURMA
                    if FPDF is not None:
                        pdf_data = create_pdf_report(df_export, target_month_str)
                        col2.download_button(
                            label="📄 PDF Olarak İndir (.pdf)", 
                            data=pdf_data, 
                            file_name=f"Kizamik_Risk_Raporu_{target_month_str}.pdf", 
                            mime="application/pdf",
                            type="primary"
                        )
                    else:
                        col2.error("PDF için 'fpdf' kütüphanesi gerekli.")

                st.markdown("---")
                def highlight_risk(val):
                    color = '#ff4b4b' if val > 80 else '#ffa500' if val > 60 else ''
                    return f'background-color: {color}'
                
                # Tabloda gösterim
                if not top_ahb_df.empty:
                    st.dataframe(top_ahb_df[['İlçe', 'Kurum Adı', 'Target_Pop', 'Toplam Aşılama Hızı', 'Korunmasız_Cocuk', 'Cember_Vaka_Yuk', 'Risk_Skoru']].style.map(highlight_risk, subset=['Risk_Skoru']).format({"Toplam Aşılama Hızı": "{:.1f}", "Risk_Skoru": "{:.1f}"}), use_container_width=True)

                st.subheader("🗺️ Taktik Sürveyans Haritası")
                fig_map = go.Figure()
                recent_cases_geo = recent_cases.dropna(subset=['Lat', 'Lon'])
                
                if not recent_cases_geo.empty:
                    recent_cases_geo['Gun_Farki'] = (latest_date - recent_cases_geo['Tarih']).dt.days
                    recent_cases_geo['Vaka_Agirligi'] = 0.5 ** (recent_cases_geo['Gun_Farki'].apply(lambda x: max(0, x)) / 30.0)
                    fig_map.add_trace(go.Densitymapbox(lat=recent_cases_geo['Lat'], lon=recent_cases_geo['Lon'], z=recent_cases_geo['Vaka_Agirligi'], radius=12, colorscale='Inferno', name='Taze Vaka Yoğunluğu', opacity=0.7))
                
                if not top_ahb_geo.empty:
                    hover_texts = top_ahb_geo['Kurum Adı'] + "<br>Vaka Yükü: " + top_ahb_geo['Cember_Vaka_Yuk'].astype(str) + "<br>Skor: " + top_ahb_geo['Risk_Skoru'].astype(str)
                    fig_map.add_trace(go.Scattermapbox(lat=top_ahb_geo['Lat'], lon=top_ahb_geo['Lon'], mode='markers', marker=dict(size=14, color='cyan', opacity=0.9, symbol='circle'), text=hover_texts, name=f'Kritik Merkezler (>{risk_esigi})', hoverinfo='text'))
                else:
                    st.success(f"✅ Harika Haber! Şehirde risk puanı {risk_esigi} üzerinde olan merkez bulunamadı.")
                
                fig_map.update_layout(mapbox_style="carto-darkmatter", mapbox_center_lon=28.97, mapbox_center_lat=41.05, mapbox_zoom=9.5, margin={"r":0,"t":0,"l":0,"b":0})
                st.plotly_chart(fig_map, use_container_width=True)

            # ==========================================
            # TAB 2 & 3: TARİHSEL VE GELECEK TAHMİNİ
            # ==========================================
            with tab2:
                df_cases_valid = df_cases.dropna(subset=['Tarih']).copy()
                df_cases_valid['Yıl_Ay'] = df_cases_valid['Tarih'].dt.strftime('%Y-%m') 
                st.plotly_chart(px.line(df_cases_valid.groupby('Yıl_Ay').size().reset_index(name='Vaka Sayısı'), x='Yıl_Ay', y='Vaka Sayısı', markers=True, title="Tarihsel Eğri"), use_container_width=True)

            with tab3:
                if ExponentialSmoothing:
                    try:
                        ts_df = df_cases.dropna(subset=['Tarih']).groupby(pd.Grouper(key='Tarih', freq='ME' if hasattr(pd.Grouper, 'freq') else 'M')).size()
                        ts_df = ts_df.reindex(pd.date_range(ts_df.index.min(), latest_date, freq='ME' if hasattr(pd.Grouper, 'freq') else 'M'), fill_value=0)
                        if len(ts_df) >= 12:
                            model = ExponentialSmoothing(ts_df, trend='add', seasonal='add', seasonal_periods=12 if len(ts_df)>=24 else None, initialization_method="estimated").fit()
                            forecast = model.forecast(6).apply(lambda x: max(0, x))
                            st.error(f"🚨 ÖNGÖRÜ: Gelecek 6 ayın zirvesi **{aylar.get(forecast.idxmax().month)} {forecast.idxmax().year}** (Tahmini Vaka: {int(forecast.max())})")
                            fig_hw = go.Figure()
                            fig_hw.add_trace(go.Scatter(x=ts_df.index, y=ts_df.values, mode='lines+markers', name='Gerçekleşen', line=dict(color='#1f77b4', width=2)))
                            fig_hw.add_trace(go.Scatter(x=forecast.index, y=forecast.values, mode='lines+markers', name='Tahmin', line=dict(color='#00ff00', width=3, dash='dot')))
                            fig_hw.update_layout(template="plotly_dark", hovermode="x unified")
                            st.plotly_chart(fig_hw, use_container_width=True)
                    except: pass

            # ==========================================
            # TAB 4: BACKTESTING
            # ==========================================
            with tab4:
                valid_months = pd.date_range(start=df_cases['Tarih'].min() + pd.DateOffset(months=6), end=latest_date, freq='ME' if hasattr(pd.Grouper, 'freq') else 'M').strftime('%Y-%m').tolist()
                test_month_str = st.selectbox("Sınamak İstediğiniz Ayı Seçin:", valid_months[::-1])
                
                if st.button("🚀 Kör Testi Başlat", type="primary"):
                    target_start = pd.to_datetime(test_month_str); target_end = target_start + pd.offsets.MonthEnd(1)
                    context_end = target_start - pd.Timedelta(days=1); context_start = context_end - pd.DateOffset(months=6)
                    target_cases = df_cases[(df_cases['Tarih'] >= target_start) & (df_cases['Tarih'] <= target_end)].dropna(subset=['Lat', 'Lon'])
                    
                    if len(target_cases) > 0:
                        predicted_df = calculate_risk_scores(df_cases[(df_cases['Tarih'] >= context_start) & (df_cases['Tarih'] <= context_end)], df_pop.copy(), df_vax.copy(), df_geo.copy(), context_end)
                        top_test_ahb = predicted_df[predicted_df['Risk_Skoru'] >= risk_esigi].dropna(subset=['Lat', 'Lon'])
                        
                        if not top_test_ahb.empty:
                            top_lats, top_lons = top_test_ahb['Lat'].values, top_test_ahb['Lon'].values
                            hits = sum(1 for _, r in target_cases.iterrows() if np.any(haversine_vectorized(r['Lat'], r['Lon'], top_lats, top_lons) <= 3.0))
                            st.success(f"Risk Skoru {risk_esigi} Üzeri Olan Merkezlerle Yapılan Test Sonucu:")
                            c1, c2, c3 = st.columns(3)
                            c1.metric("Gerçekleşen Vaka", len(target_cases)); c2.metric("Yakalanan Vaka", hits); c3.metric("İsabet Oranı", f"%{(hits/len(target_cases)*100):.1f}")
                            
                            fig_test = go.Figure()
                            fig_test.add_trace(go.Scattermapbox(lat=top_lats, lon=top_lons, mode='markers', marker=dict(size=25, color='rgba(0, 255, 255, 0.3)'), hoverinfo='none'))
                            fig_test.add_trace(go.Scattermapbox(lat=top_lats, lon=top_lons, mode='markers', marker=dict(size=8, color='cyan'), text=top_test_ahb['Kurum Adı']))
                            fig_test.add_trace(go.Scattermapbox(lat=[r['Lat'] for _, r in target_cases.iterrows() if np.any(haversine_vectorized(r['Lat'], r['Lon'], top_lats, top_lons) <= 3.0)], lon=[r['Lon'] for _, r in target_cases.iterrows() if np.any(haversine_vectorized(r['Lat'], r['Lon'], top_lats, top_lons) <= 3.0)], mode='markers', marker=dict(size=8, color='#00ff00')))
                            fig_test.add_trace(go.Scattermapbox(lat=[r['Lat'] for _, r in target_cases.iterrows() if not np.any(haversine_vectorized(r['Lat'], r['Lon'], top_lats, top_lons) <= 3.0)], lon=[r['Lon'] for _, r in target_cases.iterrows() if not np.any(haversine_vectorized(r['Lat'], r['Lon'], top_lats, top_lons) <= 3.0)], mode='markers', marker=dict(size=8, color='#ff0000')))
                            fig_test.update_layout(mapbox_style="carto-darkmatter", mapbox_center_lon=28.97, mapbox_center_lat=41.05, mapbox_zoom=9.5, margin={"r":0,"t":0,"l":0,"b":0})
                            st.plotly_chart(fig_test, use_container_width=True)

        except Exception as e: st.error(f"Hata: {e}")
