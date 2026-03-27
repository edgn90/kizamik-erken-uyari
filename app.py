import streamlit as st
import pandas as pd
import plotly.express as px

# Sayfa Ayarları
st.set_page_config(page_title="Kızamık Erken Uyarı Sistemi", page_icon="🚨", layout="wide")

st.title("🚨 Kızamık Erken Uyarı ve Sürveyans Sistemi")
st.markdown("Bu sistem; geçmiş vaka ivmesi ve güncel aşı oranlarını kullanarak önümüzdeki ayın riskli bölgelerini tahmin eder.")

# --- 1. YÜKLEME MODÜLÜ (SIDEBAR) ---
st.sidebar.header("📂 Veri Yükleme Paneli")
st.sidebar.markdown("Lütfen güncel ayın dosyalarını yükleyin.")

file_cases = st.sidebar.file_uploader("1. Vaka Listesi (Kızamık.xlsx/csv)", type=["csv", "xlsx"])
file_pop = st.sidebar.file_uploader("2. Nüfus Verisi (Nüfus.xlsx/csv)", type=["csv", "xlsx"])
file_vax = st.sidebar.file_uploader("3. Aşı Performansı (KKK.xlsx/csv)", type=["csv", "xlsx"])

# --- 2. HESAPLAMA MOTORU (ETL) ---
if file_cases and file_pop and file_vax:
    with st.spinner('Veriler işleniyor ve Makine Öğrenmesi algoritması çalıştırılıyor...'):
        try:
            # Verileri Oku
            df_cases = pd.read_csv(file_cases) if file_cases.name.endswith('.csv') else pd.read_excel(file_cases)
            df_pop = pd.read_csv(file_pop) if file_pop.name.endswith('.csv') else pd.read_excel(file_pop)
            df_vax = pd.read_csv(file_vax) if file_vax.name.endswith('.csv') else pd.read_excel(file_vax)

            # Vaka Verisini Hazırla (Son 6 Ay İvmesi)
            df_cases['Tarih'] = pd.to_datetime(df_cases['Tarih'], errors='coerce')
            latest_date = df_cases['Tarih'].max()
            six_months_ago = latest_date - pd.DateOffset(months=6)
            recent_cases = df_cases[df_cases['Tarih'] >= six_months_ago].copy()
            
            # İlçe Bazlı Vaka İvmesi
            recent_cases['İkamet adresi-İLÇE'] = recent_cases['İkamet adresi-İLÇE'].astype(str).str.strip().str.upper()
            district_momentum = recent_cases['İkamet adresi-İLÇE'].value_counts().reset_index()
            district_momentum.columns = ['İlçe', 'Aktif_Vaka_Son_6Ay']

            # Nüfus ve Aşı Verisini Hazırla
            df_pop['Target_Pop'] = pd.to_numeric(df_pop['Bebek Sayısı'], errors='coerce').fillna(0) + pd.to_numeric(df_pop['Çocuk Sayısı'], errors='coerce').fillna(0)
            df_pop['İlçe'] = df_pop['İlçe'].astype(str).str.strip().str.upper()
            
            df_vax['Toplam Aşılama Hızı'] = pd.to_numeric(df_vax['Toplam Aşılama Hızı'], errors='coerce')
            
            # Verileri Birleştir (ASM Bazında)
            df_merged = pd.merge(df_pop[['Kurum Adı', 'İlçe', 'Target_Pop']], df_vax[['Kurum Adı', 'Toplam Aşılama Hızı']], on='Kurum Adı', how='inner')
            
            # Korunmasız Çocuk Sayısı Hesaplama
            df_merged['Unvax_Rate'] = 100 - df_merged['Toplam Aşılama Hızı']
            df_merged['Korunmasız_Cocuk'] = (df_merged['Target_Pop'] * df_merged['Unvax_Rate'] / 100).fillna(0).astype(int)
            
            # İlçe İvmesini ASM'lere Ata (Bölgesel Baskı)
            df_merged = pd.merge(df_merged, district_momentum, on='İlçe', how='left')
            df_merged['Aktif_Vaka_Son_6Ay'] = df_merged['Aktif_Vaka_Son_6Ay'].fillna(0)
            
            # "Tum" (Özet) satırını ve boş ilçeleri sistemden temizleme
            df_clean = df_merged[df_merged['İlçe'].notna()]
            df_clean = df_clean[(df_clean['İlçe'] != 'TUM') & (df_clean['İlçe'] != 'NAN') & (df_clean['İlçe'] != 'NAN')]
            
            # --- RİSK SKORU ALGORİTMASI ---
            max_vuln = df_clean['Korunmasız_Cocuk'].max()
            max_cases = df_clean['Aktif_Vaka_Son_6Ay'].max()
            
            df_clean['Vuln_Score'] = df_clean['Korunmasız_Cocuk'] / max_vuln if max_vuln > 0 else 0
            df_clean['Case_Score'] = df_clean['Aktif_Vaka_Son_6Ay'] / max_cases if max_cases > 0 else 0
            
            # %60 Aşısızlık Yükü + %40 Bulaş İvmesi
            df_clean['Risk_Skoru'] = ((df_clean['Vuln_Score'] * 0.6) + (df_clean['Case_Score'] * 0.4)) * 100
            df_clean['Risk_Skoru'] = df_clean['Risk_Skoru'].round(1)
            
            # Sıralama ve Gösterime Hazırlama
            df_final = df_clean[df_clean['Target_Pop'] > 50].sort_values('Risk_Skoru', ascending=False)
            df_final = df_final[['İlçe', 'Kurum Adı', 'Target_Pop', 'Toplam Aşılama Hızı', 'Korunmasız_Cocuk', 'Aktif_Vaka_Son_6Ay', 'Risk_Skoru']]
            df_final.columns = ['İlçe', 'Aile Hekimliği Birimi', 'Hedef Nüfus', 'Aşı Hızı (%)', 'Korumasız Çocuk', 'Bölgedeki Aktif Vaka', 'Risk Skoru']
            
            # --- 3. DASHBOARD GÖRSELLEŞTİRME ---
            st.success("Analiz başarıyla tamamlandı!")
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Toplam Aktif Vaka (Son 6 Ay)", int(district_momentum['Aktif_Vaka_Son_6Ay'].sum()))
            col2.metric("İl Geneli Korumasız Çocuk", f"{df_final['Korumasız Çocuk'].sum():,}")
            # Hata vermemesi için liste boş değilse ilk ilçeyi al
            en_riskli_ilce = df_final.iloc[0]['İlçe'] if not df_final.empty else "Veri Yok"
            col3.metric("En Riskli İlçe", en_riskli_ilce)

            st.markdown("---")
            st.subheader("🔴 Acil Müdahale Listesi (En Yüksek Riskli 20 Birim)")
            
            # Pandas tablosunu renklendirerek gösterme
            def highlight_risk(val):
                color = '#ff4b4b' if val > 80 else '#ffa500' if val > 60 else ''
                return f'background-color: {color}'
                
            st.dataframe(df_final.head(20).style.applymap(highlight_risk, subset=['Risk Skoru']).format({"Aşı Hızı (%)": "{:.1f}", "Risk Skoru": "{:.1f}"}), use_container_width=True)

            # Grafikler
            st.markdown("---")
            col_chart1, col_chart2 = st.columns(2)
            
            with col_chart1:
                st.subheader("🔥 İlçelere Göre Salgın İvmesi (Son 6 Ay)")
                # NaN ilçeleri grafikten de çıkaralım
                dist_mom_clean = district_momentum[(district_momentum['İlçe'] != 'TUM') & (district_momentum['İlçe'] != 'NAN')]
                fig1 = px.bar(dist_mom_clean.head(10), x='İlçe', y='Aktif_Vaka_Son_6Ay', color='Aktif_Vaka_Son_6Ay', color_continuous_scale='Reds')
                st.plotly_chart(fig1, use_container_width=True)
                
            with col_chart2:
                st.subheader("📉 Aşı Performansı En Düşük İlçeler")
                ilce_vax = df_clean.groupby('İlçe')['Toplam Aşılama Hızı'].mean().reset_index().sort_values('Toplam Aşılama Hızı').head(10)
                fig2 = px.bar(ilce_vax, x='İlçe', y='Toplam Aşılama Hızı', color='Toplam Aşılama Hızı', color_continuous_scale='RdYlGn')
                fig2.update_layout(yaxis=dict(range=[0, 100]))
                st.plotly_chart(fig2, use_container_width=True)

            # Excel Çıktısı Alma
            st.markdown("---")
            csv = df_final.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 Kırmızı Listeyi Excel (CSV) Olarak İndir",
                data=csv,
                file_name='Kizamik_Risk_Listesi.csv',
                mime='text/csv',
            )

        except Exception as e:
            st.error(f"Veri işlenirken bir hata oluştu. Lütfen dosyaların formatını kontrol edin. Hata Kodu: {e}")
else:
    st.info("👆 Lütfen sol menüden analiz edilecek 3 dosyayı da yükleyin.")
