import streamlit as st
import pandas as pd
from openai import OpenAI
import pypdf
from PIL import Image
import io
import base64
import json

# 1. Configuração da Página do Streamlit
st.set_page_config(page_title="Conversor Inteligente de Ficheiros", page_icon="📊", layout="wide")

st.title("📊 Conversor de Ficheiros para Template Excel")
st.subheader("Ferramenta de Automação para a Equipa de Agentes")

# Espaço seguro para o Agente colocar a Chave de API (ou podes fixar no código)
openai_api_key = st.sidebar.text_input("Insira a Chave de API da OpenAI (sk-...)", type="password")

if not openai_api_key:
    st.info("Por favor, introduza a sua chave de API da OpenAI na barra lateral para começar.", icon="🔑")
    st.stop()

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
    """
    for col in colunas_preco:
        if col in df.columns:
            # Converte para string, remove espaços e o símbolo €
            df[col] = df[col].astype(str).str.replace("€", "", regex=False).str.strip()
            # Substitui o ponto por vírgula se for o caso
            df[col] = df[col].str.replace(".", ",", regex=False)
    return df

# 3. Componente de Upload de Ficheiros
ficheiro_carregado = st.file_uploader(
    "Carregue o ficheiro do fornecedor/cliente (PDF, JPEG, PNG ou XLSX)", 
    type=["pdf", "jpg", "jpeg", "png", "xlsx"]
)

if ficheiro_carregado is not None:
    st.success("Ficheiro carregado com sucesso!")
    
    # Criar um botão para iniciar o processamento
    if st.button("🚀 Processar e Gerar Excel"):
        with st.spinner("A IA está a ler e a formatar os dados... Por favor, aguarde."):
            
            conteudo_para_ia = ""
            tipo_conteudo = "texto"
            
            # Processar dependendo do tipo de ficheiro
            if ficheiro_carregado.name.endswith('.pdf'):
                conteudo_para_ia = extrair_texto_pdf(ficheiro_carregado)
                
            elif ficheiro_carregado.name.endswith(('.jpg', '.jpeg', '.png')):
                conteudo_para_ia = converter_imagem_para_base64(ficheiro_carregado)
                tipo_conteudo = "imagem"
                
            elif ficheiro_carregado.name.endswith('.xlsx'):
                df_original = pd.read_excel(ficheiro_carregado)
                conteudo_para_ia = df_original.to_json(orient="records")

            # 4. Construção do Prompt com as tuas regras específicas
            prompt_sistema = """
            És um especialista em extração e saneamento de dados. O teu objetivo é extrair a informação do ficheiro e devolvê-la estritamente no formato JSON (uma lista de objetos), onde as chaves do JSON correspondem às colunas do template Excel pretendido.

            As colunas do template são:
            - "Data" (formato DD/MM/AAAA)
            - "Nome_Cliente"
            - "Morada"
            - "Produto"
            - "Quantidade"
            - "Preco_Unitario"

            Regras Obrigatórias de Negócio:
            1. Correção Ortográfica e Tradução: Corrige todos os erros ortográficos e traduz as descrições dos produtos para Português de Portugal.
            2. Capitalização: Garante que os campos "Nome_Cliente", "Morada" e "Produto" têm a primeira letra de cada palavra em maiúscula (Capital Case).
            3. Preços: Retira o símbolo €. Devolve o preço apenas como texto numérico.

            Responde APENAS com o JSON puro, sem formatação Markdown (não uses ```json).
            """

            try:
                # Chamada à API da OpenAI (Usando o modelo GPT-4o que lê imagens e texto)
                if tipo_conteudo == "imagem":
                    resposta = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": prompt_sistema},
                            {"role": "user", "content": [
                                {"type": "text", "text": "Extrai os dados desta imagem seguindo as regras."},
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
                            {"role": "user", "content": f"Aqui estão os dados do ficheiro:\n{conteudo_para_ia}"}
                        ],
                        temperature=0
                    )
                
                # 5. Processar a resposta e criar o Excel
                dados_json = json.loads(resposta.choices[0].message.content.strip())
                df_final = pd.DataFrame(dados_json)
                
                # Aplicar a regra de segurança dos preços via Python (garantia a 100%)
                df_final = formatar_precos_python(df_final, ["Preco_Unitario"])
                
                # Mostrar pré-visualização no ecrã para o agente
                st.subheader("👀 Pré-visualização dos Dados Formatados")
                st.dataframe(df_final, use_container_width=True)
                
                # Converter o DataFrame para um ficheiro Excel em memória
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_final.to_excel(writer, index=False, sheet_name='Dados Formatados')
                dados_excel = output.getvalue()
                
                # Botão de Download para o Agente
                st.download_button(
                    label="📥 Descarregar Ficheiro Excel Pronto",
                    data=dados_excel,
                    file_name="template_final_corrigido.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
            except Exception as e:
                st.error(f"Ocorreu um erro ao processar: {e}")