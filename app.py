import streamlit as st
import pandas as pd
from openai import OpenAI
import pypdf
from PIL import Image
import io
import base64
import json

# 1. Configuração da Página do Streamlit
st.set_page_config(page_title="Conversor de Menus & Catálogos", page_icon="📊", layout="wide")

st.title("📊 Conversor Inteligente de Menus (Multi-Sheet)")
st.subheader("Ferramenta Avançada para a Equipa de Agentes")

# CONFIGURAÇÃO SEGURA: Vai buscar a chave de API diretamente aos Secrets do Streamlit Cloud
openai_api_key = st.secrets["OPENAI_API_KEY"]

# Inicializa o cliente da OpenAI
client = OpenAI(api_key=openai_api_key)

# 2. Funções de Suporte para Leitura de Ficheiros
def extrair_texto_pdf(file):
    leitor = pypdf.PdfReader(file)
    texto = ""
    for pagina in leitor.pages:
        texto += pagina.extract_text() + "\n"
    return texto

def converter_imagem_para_base64(file):
    return base64.b64encode(file.read()).decode('utf-8')

def formatar_precos_python(df, colunas_preco):
    """
    Garante a 100% que os preços não têm o € e usam a vírgula como separador decimal.
    Limpa também valores nulos ou fantasmas.
    """
    if df.empty:
        return df
    for col in colunas_preco:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace("€", "", regex=False).str.strip()
            df[col] = df[col].str.replace(".", ",", regex=False)
            df[col] = df[col].replace(["None", "nan", "NaN"], "")
    return df

# 3. Componente de Upload de Ficheiros
ficheiro_carregado = st.file_uploader(
    "Carregue o menu do parceiro (PDF, JPEG, PNG ou XLSX)", 
    type=["pdf", "jpg", "jpeg", "png", "xlsx"]
)

if ficheiro_carregado is not None:
    st.success("Ficheiro carregado com sucesso!")
    
    if st.button("🚀 Processar e Gerar Excel de 3 Páginas"):
        with st.spinner("A ler documento e a estruturar as 3 Sheets... Por favor, aguarde."):
            
            conteudo_para_ia = ""
            tipo_conteudo = "texto"
            
            if ficheiro_carregado.name.endswith('.pdf'):
                conteudo_para_ia = extrair_texto_pdf(ficheiro_carregado)
                
            elif ficheiro_carregado.name.endswith(('.jpg', '.jpeg', '.png')):
                conteudo_para_ia = converter_imagem_para_base64(ficheiro_carregado)
                tipo_conteudo = "imagem"
                
            elif ficheiro_carregado.name.endswith('.xlsx'):
                df_original = pd.read_excel(ficheiro_carregado)
                conteudo_para_ia = df_original.to_json(orient="records")

            # 4. Prompt estruturado para gerar as 3 tabelas no formato correto
            prompt_sistema = """
            És um especialista em estruturação de dados de menus para plataformas de delivery. O teu objetivo é extrair a informação do ficheiro e devolvê-la obrigatoriamente num único objeto JSON com 3 chaves ("Products", "Attribute Groups", "Attributes"). Cada chave deve conter uma lista de objetos representando as linhas da respetiva sheet.

            Segue rigorosamente os nomes das colunas para cada sheet:

            1. Sheet "Products" - Colunas:
            "External_ID", "Product_Name", "Collection", "Collection_Order", "Section", "Section_Order", "Price", "Image_1", "Description", "Is_Alcoholic", "Is_Tobacco", "Attribute_Groups"

            2. Sheet "Attribute Groups" - Colunas:
            "External_ID", "Name", "Min", "Max", "Multiple_Selection", "Collapse_by_Default", "Attributes"

            3. Sheet "Attributes" - Colunas:
            "External_ID", "Name", "Price", "Enabled", "Selected_by_Default"

            Regras Obrigatórias de Negócio:
            - Tradução e Ortografia: Traduz nomes de produtos, secções, descrições e nomes de atributos para Português de Portugal. Corrige erros ortográficos.
            - Capitalização: Garante que os campos de texto (Product_Name, Collection, Section, Name nas duas tabelas) têm a primeira letra de cada palavra em maiúscula (Capital Case).
            - Preços: Extrai o valor numérico para a coluna "Price" (tanto em Products como em Attributes). Remove o símbolo €.
            - IDs de Ligação: Garante que os IDs ou nomes usados para ligar os produtos aos grupos e aos atributos fazem sentido lógico com base no menu extraído.
            - Campos ausentes: Deixa como string vazia ("") caso não existam dados no documento.

            Responde APENAS com o JSON puro, sem blocos de código Markdown (não uses ```json).
            """

            try:
                # Chamada à API
                if tipo_conteudo == "imagem":
                    resposta = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": prompt_sistema},
                            {"role": "user", "content": [
                                {"type": "text", "text": "Extrai e organiza este menu nas 3 estruturas requeridas."},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{conteudo_para_ia}"}}
                            ]}
                        ],
                        temperature=0
                    )
                else:
                    resposta = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": prompt_sistema},
                            {"role": "user", "content": f"Aqui estão os dados do ficheiro de origem:\n{conteudo_para_ia}"}
                        ],
                        temperature=0
                    )
                
                # 5. Processar a resposta e separar pelas 3 tabelas
                dados_json = json.loads(resposta.choices[0].message.content.strip())
                
                colunas_products = ["External_ID", "Product_Name", "Collection", "Collection_Order", "Section", "Section_Order", "Price", "Image_1", "Description", "Is_Alcoholic", "Is_Tobacco", "Attribute_Groups"]
                colunas_groups = ["External_ID", "Name", "Min", "Max", "Multiple_Selection", "Collapse_by_Default", "Attributes"]
                colunas_attributes = ["External_ID", "Name", "Price", "Enabled", "Selected_by_Default"]
                
                df_products = pd.DataFrame(dados_json.get("Products", []), columns=colunas_products)
                df_groups = pd.DataFrame(dados_json.get("Attribute Groups", []), columns=colunas_groups)
                df_attributes = pd.DataFrame(dados_json.get("Attributes", []), columns=colunas_attributes)
                
                # Aplicar a regra estrita de preços nas tabelas que contêm preços
                df_products = formatar_precos_python(df_products, ["Price"])
                df_attributes = formatar_precos_python(df_attributes, ["Price"])
                
                # 6. Interface Visual: Mostrar as 3 tabelas em Separadores (Tabs) para o Agente validar
                st.subheader("👀 Pré-visualização das 3 Páginas do Template")
                tab1, tab2, tab3 = st.tabs(["📦 Products", "🗂️ Attribute Groups", "📌 Attributes"])
                
                with tab1:
                    st.dataframe(df_products, use_container_width=True)
                with tab2:
                    st.dataframe(df_groups, use_container_width=True)
                with tab3:
                    st.dataframe(df_attributes, use_container_width=True)
                
                # 7. Criar o ficheiro Excel em memória com as 3 Sheets
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_products.to_excel(writer, index=False, sheet_name='Products')
                    df_groups.to_excel(writer, index=False, sheet_name='Attribute Groups')
                    df_attributes.to_excel(writer, index=False, sheet_name='Attributes')
                dados_excel = output.getvalue()
                
                st.markdown("---")
                # Botão de Download único para o ficheiro completo
                st.download_button(
                    label="📥 Descarregar Excel Completo (Admin_Template)",
                    data=dados_excel,
                    file_name="Admin_Template_Processado.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
            except Exception as e:
                st.error(f"Ocorreu um erro no processamento: {e}")
