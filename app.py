import streamlit as st
import pandas as pd
import json
import uuid
import io
import base64
import urllib.parse
import time
import random
import pypdf
from bs4 import BeautifulSoup
from openai import OpenAI
from curl_cffi import requests

# 1. Configuração da Página do Streamlit
st.set_page_config(page_title="Menu Converter Suite Pro", page_icon="🍔", layout="wide")

st.title("🍔 Menu Converter Suite Pro")
st.markdown("Ferramenta centralizada para processamento e estruturação de menus em 3 Sheets.")
st.divider()

# CONFIGURAÇÃO SEGURA DA API KEY
openai_api_key = st.secrets["OPENAI_API_KEY"]
client = OpenAI(api_key=openai_api_key)

# 2. Função de Segurança para Forçar Preços com Vírgula (Critério Obrigatório)
def formatar_precos_portugal(df, coluna="Price"):
    if df.empty or coluna not in df.columns:
        return df
    # Garante que é string, remove símbolos e troca ponto por vírgula
    df[coluna] = df[coluna].astype(str).str.replace("€", "", regex=False).str.strip()
    df[coluna] = df[coluna].str.replace(".", ",", regex=False)
    df[coluna] = df[coluna].replace(["None", "nan", "NaN", "0,0", "0,00"], "0")
    return df

# 3. LÓGICA DO SCRAPER (UBER EATS)
def scrape_uber_eats(url, status_container):
    clean_url = url.strip()
    for char in ["'", '"', "<", ">", "[", "]"]:
        clean_url = clean_url.replace(char, "")
    if not clean_url.startswith("http"):
        clean_url = "https://" + clean_url

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
        "content-type": "application/json",
        "x-csrf-token": "x"
    }

    status_container.info(f"🚀 A conectar a: {clean_url}...")
    try:
        response = requests.get(clean_url, headers=headers, impersonate="chrome110")
        if response.status_code != 200:
            status_container.error(f"❌ Falha ao carregar página da Uber. Status: {response.status_code}")
            return None
    except Exception as e:
        status_container.error(f"❌ Erro de Ligação: {e}")
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    base_menu_items = []
    scripts = soup.find_all('script', {'type': 'application/ld+json'})

    for script in scripts:
        if script.string and 'hasMenu' in script.string:
            try:
                data = json.loads(script.string)
                for section in data.get('hasMenu', {}).get('hasMenuSection', []):
                    category = section.get('name', 'Geral')
                    for item in section.get('hasMenuItem', []):
                        offers = item.get('offers', {})
                        price = 0
                        if isinstance(offers, dict):
                            price = float(offers.get('price', 0))
                        elif isinstance(offers, list) and len(offers) > 0:
                            price = float(offers[0].get('price', 0))

                        base_menu_items.append({
                            'name': item.get('name'),
                            'description': item.get('description', ''),
                            'price': price,
                            'image': item.get('image', [])[0] if item.get('image') else '',
                            'category': category,
                            'customizations': []
                        })
                break
            except: continue

    status_container.success(f"✅ Encontrados {len(base_menu_items)} itens básicos. A extrair modificadores...")

    product_links = soup.find_all('a', href=True)
    uuid_map = {}
    for link in product_links:
        href = link['href']
        if 'modctx' in href:
            try:
                parsed_url = urllib.parse.urlparse(href)
                query_params = urllib.parse.parse_qs(parsed_url.query)
                if 'modctx' in query_params:
                    modctx_json = urllib.parse.unquote(urllib.parse.unquote(query_params['modctx'][0]))
                    modctx_data = json.loads(modctx_json)
                    item_uuid = modctx_data.get('itemUuid')
                    if item_uuid:
                        uuid_map[item_uuid] = {
                            'storeUuid': modctx_data.get('storeUuid'),
                            'sectionUuid': modctx_data.get('sectionUuid'),
                            'subsectionUuid': modctx_data.get('subsectionUuid'),
                            'menuItemUuid': item_uuid
                        }
            except: continue

    detailed_data_map = {}
    uuid_items = list(uuid_map.items())

    if uuid_items:
        progress_bar = status_container.progress(0)
        for i, (uuid_val, params) in enumerate(uuid_items):
            progress = (i + 1) / len(uuid_items)
            progress_bar.progress(progress, text=f"A ler modificadores do item {i+1} de {len(uuid_items)}...")

            payload = {
                "itemRequestType": "ITEM",
                "storeUuid": params['storeUuid'],
                "sectionUuid": params['sectionUuid'],
                "subsectionUuid": params['subsectionUuid'],
                "menuItemUuid": params['menuItemUuid'],
                "cbType": "EATER_ENDORSED",
                "includeCheaperAlternatives": False
            }

            try:
                api_url = "https://www.ubereats.com/_p/api/getMenuItemV1?localeCode=pt"
                api_response = requests.post(api_url, headers=headers, json=payload, impersonate="chrome110")

                if api_response.status_code == 200:
                    item_data = api_response.json().get('data', {})
                    item_name = item_data.get('title')

                    customizations = []
                    for group in item_data.get('customizationsList', []):
                        options = []
                        for opt in group.get('options', []):
                            price_val = opt.get('price', 0)
                            if isinstance(price_val, int): price_val = price_val / 100.0

                            options.append({
                                'name': opt.get('title'),
                                'price': price_val,
                                'suspended': opt.get('suspended', False)
                            })
                        customizations.append({
                            'group_name': group.get('title'),
                            'min_permitted': group.get('minPermitted'),
                            'max_permitted': group.get('maxPermitted'),
                            'options': options
                        })
                    detailed_data_map[item_name] = customizations
                time.sleep(random.uniform(1, 3)) # Evitar bloqueios rápidos
            except: continue

    final_menu = []
    for item in base_menu_items:
        name = item['name']
        if name in detailed_data_map:
            item['customizations'] = detailed_data_map[name]
        final_menu.append(item)

    return {'menu': final_menu}

# 4. LÓGICA DE EXTRAÇÃO COM IA (Ficheiros/Imagens)
def extrair_texto_pdf(file):
    leitor = pypdf.PdfReader(file)
    texto = ""
    for pagina in leitor.pages:
        texto += pagina.extract_text() + "\n"
    return texto

def extract_menu_with_ai(uploaded_file, file_extension, status_container):
    prompt = '''
    You are a professional restaurant menu data extractor.
    Format the output STRICTLY matching this JSON structure:
    {"menu": [{"name": "Item Name", "description": "Clean description", "price": 8.0, "category": "Section Name", "customizations": [{"group_name": "Size", "min_permitted": 1, "max_permitted": 1, "options": [{"name": "Small", "price": 0.0}]}]}]}

    CRITICAL RULES FOR PORTUGAL:
    1. TRANSLATION: Translate all names, categories, descriptions, and options into clean Portuguese (Portugal).
    2. CAPITALIZATION: Ensure Product Names, Categories, Sections and Options are in Capital Case (e.g. "Prego No Pão").
    3. FOOD CONSOLIDATION (MERGING): Merge items with sizes in parentheses like "Batata (Média)" and "Batata (Grande)" into ONE product "Batata". The sizes become options. Base price is the cheapest. Option prices are the DIFFERENCE.
    4. BEVERAGE SEPARATION (SPLITTING): Slashes in drinks mean different products. "Ice Tea Limão/Pêssego" at 2.0 MUST be split into TWO separate products: "Ice Tea Limão" (2.0) and "Ice Tea Pêssego" (2.0). Drinks never use customizations.
    '''
    try:
        messages = [{"role": "system", "content": prompt}]
        if file_extension in ['csv', 'xlsx', 'txt']:
            if file_extension == 'xlsx': df = pd.read_excel(uploaded_file)
            else: df = pd.read_csv(uploaded_file)
            messages.append({"role": "user", "content": f"Data:\n{df.to_csv(index=False)[:40000]}"})
        elif file_extension == 'pdf':
            raw_text = extrair_texto_pdf(uploaded_file)
            messages.append({"role": "user", "content": f"Text:\n{raw_text[:40000]}"})
        else:
            b64 = base64.b64encode(uploaded_file.getvalue()).decode('utf-8')
            messages.append({"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]})

        response = client.chat.completions.create(
            model="gpt-4o", messages=messages, response_format={"type": "json_object"}, temperature=0.1
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        status_container.error(f"❌ Falha na IA: {e}")
        return None

# 5. MOTOR DE CONVERSÃO EM EXCEL (COM CRIAÇÃO DE UUIDs)
def convert_to_excel(json_data):
    menu_items = json_data.get('menu', [])
    rows_products, rows_attr_groups, rows_attributes = [], [], []
    attributes_cache, attr_groups_cache, section_order_map = {}, {}, {}
    current_section_counter = 1

    for item in menu_items:
        price = float(item.get('price', 0))
        product_name = item.get('name', 'Sem Nome')
        if price <= 0: continue # Descarta preço 0

        product_attr_group_ids = []

        # Processar Modificadores (UUIDs Automatizados)
        for group in item.get('customizations', []):
            group_attr_ids = []
            for option in group.get('options', []):
                attr_name = option.get('name', '').strip()
                attr_price = float(option.get('price', 0))
                attr_key = (attr_name, attr_price)

                if attr_key in attributes_cache:
                    attr_uuid = attributes_cache[attr_key]
                else:
                    attr_uuid = str(uuid.uuid4())
                    attributes_cache[attr_key] = attr_uuid
                    rows_attributes.append({
                        'External_ID': attr_uuid, 'Name': attr_name, 'Price': attr_price,
                        'Enabled': 'YES', 'Selected_by_Default': 'NO'
                    })
                group_attr_ids.append(attr_uuid)

            group_name = group.get('group_name', '').strip()
            min_perm = int(group.get('min_permitted', 0))
            max_perm = int(group.get('max_permitted', 1))
            group_key = (group_name, min_perm, max_perm, tuple(sorted(group_attr_ids)))

            if group_key in attr_groups_cache:
                group_uuid = attr_groups_cache[group_key]
            else:
                group_uuid = str(uuid.uuid4())
                attr_groups_cache[group_key] = group_uuid
                rows_attr_groups.append({
                    'External_ID': group_uuid, 'Max': max_perm, 'Min': min_perm,
                    'Name': group_name, 'Multiple_Selection': 'YES' if max_perm > 1 else 'NO',
                    'Collapse_by_Default': 'NO', 'Attributes': ', '.join(group_attr_ids)
                })
            product_attr_group_ids.append(group_uuid)

        # Processar Produto Principal
        raw_section = item.get('category', 'Geral').strip()
        if raw_section not in section_order_map:
            section_order_map[raw_section] = current_section_counter
            current_section_counter += 1

        product_uuid = str(uuid.uuid4())
        rows_products.append({
            'External_ID': product_uuid, 'Product_Name': product_name,
            'Collection': 'Menu', 'Collection_Image': '', 'Collection_Order': 1,
            'Section': raw_section, 'Section_Order': section_order_map[raw_section],
            'Price': price, 'Image_1': '', 'Description': item.get('description', '').strip(),
            'Is_Alcoholic': 'NO', 'Is_Tobacco': 'NO',
            'Attribute_Groups': ', '.join(product_attr_group_ids), 'Dietary': ''
        })

    df_p = pd.DataFrame(rows_products)
    df_g = pd.DataFrame(rows_attr_groups)
    df_a = pd.DataFrame(rows_attributes)

    # Reordenar colunas de acordo com o teu template estrito
    cols_p = ['External_ID', 'Product_Name', 'Collection', 'Collection_Order', 'Section', 'Section_Order', 'Price', 'Image_1', 'Description', 'Is_Alcoholic', 'Is_Tobacco', 'Attribute_Groups']
    cols_g = ['External_ID', 'Name', 'Min', 'Max', 'Multiple_Selection', 'Collapse_by_Default', 'Attributes']
    cols_a = ['External_ID', 'Name', 'Price', 'Enabled', 'Selected_by_Default']

    df_products = df_p.reindex(columns=cols_p).fillna("")
    df_groups = df_g.reindex(columns=cols_g).fillna("")
    df_attrs = df_a.reindex(columns=cols_a).fillna("")

    # APLICAÇÃO DA REGRA DE PORTUGAL (VÍRGULAS NOS PREÇOS)
    df_products = formatar_precos_portugal(df_products, "Price")
    df_attrs = formatar_precos_portugal(df_attrs, "Price")

    return df_products, df_groups, df_attrs

# 6. INTERFACE SIDE-BY-SIDE (IGUAL AO COLAB)
col_scraper, col_ai = st.columns(2, gap="large")

with col_scraper:
    st.header("🌐 Uber Eats Scraper")
    st.markdown("Cole um URL de restaurante para extrair a estrutura completa.")
    url_input = st.text_input("URL do Restaurante", placeholder="https://www.ubereats.com/pt/store/...")
    
    if st.button("Iniciar Raspagem Uber", type="primary"):
        if url_input:
            status_scr = st.empty()
            with st.spinner('A raspar dados... pode demorar 1-2 minutos...'):
                scraped = scrape_uber_eats(url_input, status_scr)
            if scraped:
                df_p, df_g, df_a = convert_to_excel(scraped)
                
                # Mostrar Pré-visualização
                st.tabs(["Products", "Groups", "Attributes"])[0].dataframe(df_p)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_p.to_excel(writer, sheet_name='Products', index=False)
                    df_g.to_excel(writer, sheet_name='Attribute Groups', index=False)
                    df_a.to_excel(writer, sheet_name='Attributes', index=False)
                
                st.download_button("⬇️ Baixar Excel (Scraper)", data=output.getvalue(), file_name="uber_menu.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else: st.warning("Introduza um link.")

with col_ai:
    st.header("🪄 Importador de Ficheiros com IA")
    st.markdown("Faça upload de PDF, Imagens (JPEG/PNG) ou tabelas desformatadas.")
    uploaded_file = st.file_uploader("Carregar Documento", type=["pdf", "png", "jpg", "jpeg", "csv", "xlsx", "txt"])
    
    if st.button("Processar com IA", type="primary"):
        if uploaded_file:
            status_ai = st.empty()
            file_ext = uploaded_file.name.split('.')[-1].lower()
            with st.spinner('A IA está a ler e a estruturar o menu...'):
                extracted = extract_menu_with_ai(uploaded_file, file_ext, status_ai)
            if extracted:
                df_p, df_g, df_a = convert_to_excel(extracted)
                
                # Mostrar Pré-visualização
                st.tabs(["Products", "Groups", "Attributes"])[0].dataframe(df_p)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_p.to_excel(writer, sheet_name='Products', index=False)
                    df_g.to_excel(writer, sheet_name='Attribute Groups', index=False)
                    df_a.to_excel(writer, sheet_name='Attributes', index=False)
                
                st.download_button("⬇️ Baixar Excel (IA)", data=output.getvalue(), file_name="ai_menu.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else: st.warning("Faça upload de um ficheiro.")
