import streamlit as st
import pandas as pd
import plotly.express as px

# Sayfa Ayarları
st.set_page_config(page_title="Kızamık Sürveyans ve Uyarı Sistemi", page_icon="🚨", layout="wide")

st.title("🚨 Kızamık Erken Uyarı ve YZ Sürveyans Radarı")
st.markdown("Bu sistem; vakaların coğrafi koordinatlarını ve üstel sürü bağışıklığı cezalarını kullanarak yüksek hassasiyetli risk tahminleri yapar.")

# --- 1. YÜKLEME MODÜLÜ (SIDEBAR) ---
st.sidebar.header("📂 Veri Yükleme Paneli")
st.sidebar.markdown("Analiz edilecek dosyaları yükleyin.")

file_cases = st.sidebar.file_uploader("1. Vaka Listesi (Kızamık.xlsx/csv)", type=["csv", "xlsx"])
file_pop = st.sidebar.file_uploader("2. Nüfus Verisi (Nüfus.xlsx/csv)", type=["csv", "xlsx"])
file_vax = st.sidebar.file_uploader("3. Aşı Performansı (KKK.xlsx/csv)", type=["csv", "xlsx"])

# Türkçe Ay İsimleri Sözlüğü
aylar = {1: 'Ocak', 2: 'Şubat', 3: 'Mart', 4: 'Nisan', 5: 'Mayıs', 6: 'Haziran', 
         7: 'Temmuz', 8: 'Ağustos', 9: 'Eylül', 10: 'Ekim', 11: 'Kasım', 12: 'Aralık'}

# --- ANA İŞLEYİŞ VE SEKMELER (TABS) ---
if file_cases and file_pop and file_vax:
    with st.spinner('Yapay Zeka Uzamsal Algoritmaları ve Risk Motoru Çalıştırılıyor...'):
        try:
            # Verileri Oku
            df_cases = pd.read_csv(file_cases) if file_cases.name.endswith('.csv') else pd.read_excel(file_cases)
            df_pop = pd.read_csv(file_pop) if file_pop.name.endswith('.csv') else pd.read_excel(file_pop)
            df_vax = pd.read_csv(file_vax) if file_vax.name.endswith('.csv') else pd.read_excel(file_vax)

            # --- VERİ ÖN HAZIRLIĞI ---
            df_cases['Tarih'] = pd.to_datetime(df_cases['Tarih'], errors='coerce')
            latest_date = df_cases['Tarih'].max()
            
            # Koordinatları (Lat/Lon) sayısal değere çevir (Harita için)
            if 'Lat' in df_cases.columns and 'Lon' in df_cases.columns:
                df_cases['Lat'] = pd.to_numeric(df_cases['Lat'], errors='coerce')
                df_cases['Lon'] = pd.to_numeric(df_cases['Lon'], errors='coerce')

            # Sekmeleri Oluştur
            tab1, tab2 = st.tabs(["🚨 YZ ERKEN UYARI RADARI (Gelecek Ay Tahmini)", "📊 TARİHSEL ANALİZ (4 Yıllık Makro Görünüm)"])
            
            # ==========================================
            # TAB 1: ERKEN UYARI SİSTEMİ (Operasyonel)
            # ==========================================
            with tab1:
                # Zaman pencereleri
                six_months_ago = latest_date - pd.DateOffset(months=5) 
                target_date = latest_date + pd.DateOffset(months=1)
                
                start_str = f"{aylar[six_months_ago.month]} {six_months_ago.year}"
                end_str = f"{aylar[latest_date.month]} {latest_date.year}"
                target_str = f"{aylar[target_date.month]} {target_date.year}"

                # Son 6 ay ivmesi
                recent_cases = df_cases[df_cases['Tarih'] >= (latest_date - pd.DateOffset(months=6))].copy()
                recent_cases['İkamet adresi-İLÇE'] = recent_cases['İkamet adresi-İLÇE'].astype(str).str.strip().str.upper()
                district_momentum = recent_cases['İkamet adresi-İLÇE'].value_counts().reset_index()
                district_momentum.columns = ['İlçe', 'Aktif_Vaka_Son_6Ay']

                # Nüfus ve Aşı Verisi
                df_pop['Target_Pop'] = pd.to_numeric(df_pop['Bebek Sayısı'], errors='coerce').fillna(0) + pd.to_numeric(df_pop['Çocuk Sayısı'], errors='coerce').fillna(0)
                df_pop['İlçe'] = df_pop['İlçe'].astype(str).str.strip().str.upper()
                df_vax['Toplam Aşılama Hızı'] = pd.to_numeric(df_vax['Toplam Aşılama Hızı'], errors='coerce')
                
                # Birleştirme ve Hesaplama
                df_merged = pd.merge(df_pop[['Kurum Adı', 'İlçe', 'Target_Pop']], df_vax[['Kurum Adı', 'Toplam Aşılama Hızı']], on='Kurum Adı', how='inner')
                df_merged['Unvax_Rate'] = 100 - df_merged['Toplam Aşılama Hızı']
                df_merged['Korunmasız_Cocuk'] = (df_merged['Target_Pop'] * df_merged['Unvax_Rate'] / 100).fillna(0).astype(int)
                df_merged = pd.merge(df_merged, district_momentum, on='İlçe', how='left')
                df_merged['Aktif_Vaka_Son_6Ay'] = df_merged['Aktif_Vaka_Son_6Ay'].fillna(0)
                
                # Temizlik
                df_clean = df_merged[df_merged['İlçe'].notna()]
                df_clean = df_clean[(df_clean['İlçe'] != 'TUM') & (df_clean['İlçe'] != 'NAN')]
                
                # --- YENİ YZ RİSK SKORU (SÜRÜ BAĞIŞIKLIĞI CEZALI) ---
                max_vuln = df_clean['Korunmasız_Cocuk'].max()
                max_cases = df_clean['Aktif_Vaka_Son_6Ay'].max()
                
                df_clean['Vuln_Score'] = df_clean['Korunmasız_Cocuk'] / max_vuln if max_vuln > 0 else 0
                df_clean['Case_Score'] = df_clean['Aktif_Vaka_Son_6Ay'] / max_cases if max_cases > 0 else 0
                
                # 1. Ham Risk (%50 Aşısız Nüfus Yükü, %50 Aktif Bulaş)
                df_clean['Ham_Risk'] = ((df_clean['Vuln_Score'] * 0.5) + (df_clean['Case_Score'] * 0.5)) * 100
                
                # 2. Üstel Sürü Bağışıklığı Cezası (%95 Altı)
                # 95'in ne kadar altındaysa (Fark), o kadar katlanarak ceza yer (Fark^1.3)
                df_clean['Esik_Farki'] = 95 - df_clean['Toplam Aşılama Hızı']
                df_clean['Esik_Farki'] = df_clean['Esik_Farki'].apply(lambda x: x if x > 0 else 0)
                df_clean['Ceza_Puani'] = (df_clean['Esik_Farki'] ** 1.3) * 0.4 
                
                # 3. Final YZ Skoru (Ham Risk + Ceza)
                df_clean['Risk_Skoru'] = df_clean['Ham_Risk'] + df_clean['Ceza_Puani']
                df_clean['Risk_Skoru'] = df_clean['Risk_Skoru'].apply(lambda x: 100 if x > 100 else x).round(1) # Maksimum 100'e sabitle
                
                df_final = df_clean[df_clean['Target_Pop'] > 50].sort_values('Risk_Skoru', ascending=False)
                df_final = df_final[['İlçe', 'Kurum Adı', 'Target_Pop', 'Toplam Aşılama Hızı', 'Korunmasız_Cocuk', 'Aktif_Vaka_Son_6Ay', 'Risk_Skoru']]
                df_final.columns = ['İlçe', 'Aile Hekimliği Birimi', 'Hedef Nüfus', 'Aşı Hızı (%)', 'Korumasız Çocuk', 'Bölgedeki Aktif Vaka', 'YZ Risk Skoru']
                
                # Görselleştirme (Tab 1)
                st.info(f"🎯 **Sürveyans Hedefi:** Sistem, **{start_str} - {end_str}** ivmesini ve sürü bağışıklığı eşiklerini (DSÖ) kullanarak **{target_str}** ayı için acil müdahale noktalarını tespit etti.")
                
                col1, col2, col3 = st.columns(3)
                col1.metric(f"Aktif Vaka ({start_str}-{end_str})", int(district_momentum['Aktif_Vaka_Son_6Ay'].sum()))
                col2.metric("İl Geneli Korumasız Çocuk", f"{df_final['Korumasız Çocuk'].sum():,}")
                col3.metric(f"En Kritik İlçe ({target_str})", df_final.iloc[0]['İlçe'] if not df_final.empty else "Veri Yok")

                # --- YENİ EKLENEN: COĞRAFİ ISI HARİTASI ---
                st.markdown("---")
                st.subheader(f"🗺️ Aktif Vaka Kümelenme Radarı ({start_str} - {end_str})")
                st.markdown("Aşağıdaki harita, son 6 aydaki vakaların GPS koordinatlarını kullanarak **fiziksel bulaş çemberlerini (hotspots)** gösterir. Kırmızı alanlar virüsün fiziksel olarak dolaştığı merkezlerdir.")
                
                if 'Lat' in recent_cases.columns and 'Lon' in recent_cases.columns:
                    map_data = recent_cases.dropna(subset=['Lat', 'Lon'])
                    if not map_data.empty:
                        # İstanbul merkezli ısı haritası
                        fig_map = px.density_mapbox(map_data, lat='Lat', lon='Lon', radius=15,
                                                    center=dict(lat=41.05, lon=28.97), zoom=9.5,
                                                    mapbox_style="carto-positron",
                                                    color_continuous_scale="Inferno")
                        fig_map.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
                        st.plotly_chart(fig_map, use_container_width=True)
                    else:
                        st.warning("Son 6 ay vakaları için geçerli koordinat bulunamadı.")
                else:
                    st.warning("Yüklenen vaka dosyasında 'Lat' (Enlem) ve 'Lon' (Boylam) sütunları bulunamadı.")

                st.markdown("---")
                st.subheader(f"🔴 Acil Müdahale Listesi ({target_str} Ayı)")
                st.markdown("*Not: Aşı Hızı %95'in altındaki birimler sistem tarafından üstel olarak cezalandırılmış ve puanları artırılmıştır.*")
                def highlight_risk(val):
                    color = '#ff4b4b' if val > 80 else '#ffa500' if val > 60 else ''
                    return f'background-color: {color}'
                st.dataframe(df_final.head(20).style.applymap(highlight_risk, subset=['YZ Risk Skoru']).format({"Aşı Hızı (%)": "{:.1f}", "YZ Risk Skoru": "{:.1f}"}), use_container_width=True)

            # ==========================================
            # TAB 2: TARİHSEL ANALİZ (Retrospektif)
            # ==========================================
            with tab2:
                st.info("Bu sayfa, yüklediğiniz vaka listesindeki **tüm yılları (2022'den bugüne)** kapsayan makro epidemiyolojik trendleri gösterir.")
                
                # Temel KPI'lar
                total_cases_all = len(df_cases)
                first_date = df_cases['Tarih'].min().strftime('%Y-%m') if not pd.isna(df_cases['Tarih'].min()) else "Bilinmiyor"
                last_date = df_cases['Tarih'].max().strftime('%Y-%m') if not pd.isna(df_cases['Tarih'].max()) else "Bilinmiyor"
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Kümülatif Toplam Vaka", f"{total_cases_all:,}")
                c2.metric("İncelenen Periyot", f"{first_date} / {last_date}")
                c3.metric("Zirve Yapan Yıl", df_cases['Tarih'].dt.year.value_counts().idxmax() if not df_cases['Tarih'].empty else "-")
                
                st.markdown("---")
                
                st.subheader("📈 4 Yıllık Salgın Eğrisi (Epi-Curve)")
                df_cases['Yıl_Ay'] = df_cases['Tarih'].dt.to_period('M').astype(str)
                epi_data = df_cases.groupby('Yıl_Ay').size().reset_index(name='Vaka Sayısı')
                epi_data = epi_data[epi_data['Yıl_Ay'] != 'NaT']
                fig_epi = px.line(epi_data, x='Yıl_Ay', y='Vaka Sayısı', markers=True, color_discrete_sequence=['#d62728'])
                fig_epi.update_traces(line=dict(width=3), marker=dict(size=8))
                st.plotly_chart(fig_epi, use_container_width=True)
                
                col_hist1, col_hist2 = st.columns(2)
                
                with col_hist1:
                    st.subheader("📍 En Çok Vaka Çıkan 15 İlçe (Kümülatif)")
                    df_cases['İlçe_Temiz'] = df_cases['İkamet adresi-İLÇE'].astype(str).str.strip().str.upper()
                    dist_cum = df_cases[df_cases['İlçe_Temiz'] != 'NAN']['İlçe_Temiz'].value_counts().reset_index().head(15)
                    dist_cum.columns = ['İlçe', 'Toplam Vaka']
                    fig_dist = px.bar(dist_cum, x='İlçe', y='Toplam Vaka', color='Toplam Vaka', color_continuous_scale='Blues')
                    st.plotly_chart(fig_dist, use_container_width=True)
                    
                with col_hist2:
                    st.subheader("🛡️ Vakaların Aşılanma Durumu")
                    if 'Aşı Durumu' in df_cases.columns:
                        df_cases['Aşı_Temiz'] = df_cases['Aşı Durumu'].astype(str).str.strip().str.upper()
                        vax_counts = df_cases['Aşı_Temiz'].value_counts()
                        vax_data = vax_counts.reset_index()
                        vax_data.columns = ['Aşı Durumu', 'Vaka Sayısı']
                        
                        fig_vax = px.pie(vax_data.head(5), names='Aşı Durumu', values='Vaka Sayısı', hole=0.4, 
                                         color_discrete_sequence=px.colors.qualitative.Pastel)
                        st.plotly_chart(fig_vax, use_container_width=True)

        except Exception as e:
            st.error(f"Veri işlenirken bir hata oluştu. Hata Kodu: {e}")
else:
    st.info("👆 Lütfen analiz edilecek 3 dosyayı da sol menüden yükleyin.")
