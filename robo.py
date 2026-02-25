import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import unicodedata
import time
import re
import sys
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

# Detecção inteligente de ambiente
IS_CODESPACE = os.getenv("CODESPACES", "false").lower() == "true"

# No Windows (local), o padrão agora é VER a tela (false)
# No Codespaces (nuvem), o padrão é OCULTO (true)
default_headless = "true" if IS_CODESPACE else "false"
HEADLESS = os.getenv("HEADLESS", default_headless).lower() == "true"

# ==============================
# CONFIGURAÇÃO E CREDENCIAIS
# ==============================

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file("credenciais.json", scopes=SCOPES)
client = gspread.authorize(creds)

SHEET_URL = "https://docs.google.com/spreadsheets/d/1ukIGDUSIobMlI-nLRjmBdLIt9ftWkncW4_Xl6u5SdpA"
sheet = client.open_by_url(SHEET_URL).worksheet("dados")

VALORES_FIXOS = {
    "melhor_horario": "Comercial (08h00 as 17h48)",
    "telefone": "84 997080020",
    "ambiente": "Fleury",
    "equipamento": "Equipamento Desktop",
    "tipo": "Configuração",
    "patrimonio": ".",
    "maquina": ".",
    "resolucao": "Atendimento realizado e serviço normalizado conforme solicitado.<br>Permanecemos à disposição para eventuais necessidades.<br><br>Atenciosamente,<br>Tecnologia da Informação",
    "agente": "PAULO RICARDO DA SILVA SOARES",
    "estado": "Resolvido",
    "cod_resolucao": "Resolvido Com Sucesso",
    "tipo_atendimento": "Unidade Base"
}

COL_CHAMADO = 6  # Coluna F
COL_STATUS = 7   # Coluna G

def normalizar(texto):
    if not texto: return ""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = texto.encode("ASCII", "ignore").decode("ASCII")
    return texto.strip().upper()

# ==============================
# BROWSER SETUP
# ==============================

options = webdriver.ChromeOptions()

if HEADLESS:
    print("🌐 Iniciando em modo Headless (Sem Janela)...")
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
else:
    print("🖥️ Iniciando em modo com Janela (Visual)...")
    if not IS_CODESPACE:
        options.add_argument(r"--user-data-dir=C:\robo\profile")
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

# Opções extras de estabilidade e Stealth (Esconder que é robô)
# Removida porta 9222 para evitar conflito de "SessionNotCreated" no Windows
options.add_argument("--disable-blink-features=AutomationControlled")

# User-Agent real de Windows para enganar a Microsoft
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)

# Desativa detecção de 'blink' e outras marcas de teste
options.add_argument("--disable-infobars")
options.add_argument("--disable-browser-side-navigation")

driver = webdriver.Chrome(options=options)

# Injeção de Script para remover o flag de WebDriver e forçar identidade de Windows
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
  "source": """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {} };
    Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
  """
})

wait = WebDriverWait(driver, 30)

# ==============================
# "BYPASS" HELPERS (Pula Selenium find_element que crasha)
# ==============================

def fazer_login():
    """Realiza o login automático no Freshservice."""
    if not FRESH_USER or not FRESH_PASS:
        print("⚠️ FRESH_USER ou FRESH_PASS não configurados nas variáveis de ambiente.")
        return False
        
    try:
        print(f"🔐 Tentando login automático para {FRESH_USER}...")
        driver.get("https://grupofleury.freshservice.com/login")
        time.sleep(5)
        
        # Tentativa 1: Campos padrão Freshservice
        try:
            driver.find_element(By.ID, "user_email").send_keys(FRESH_USER)
            p = driver.find_element(By.ID, "user_password")
            p.send_keys(FRESH_PASS)
            p.send_keys(Keys.ENTER)
            time.sleep(10)
            return "dashboard" in driver.current_url.lower() or "tickets" in driver.current_url.lower()
        except:
            # Tentativa 2: Clique no link de login se estiver na home
            driver.execute_script("document.querySelector('a[href*=\"login\"], .login-btn')?.click();")
            time.sleep(5)
            return False
    except Exception as e:
        print(f"❌ Erro login: {e}")
        return False

def salvar_cookies():
    """Salva os cookies atuais em um arquivo para reutilização."""
    try:
        with open("cookies.pkl", "wb") as f:
            import pickle
            pickle.dump(driver.get_cookies(), f)
        print("✅ Sessão salva em cookies.pkl!")
    except Exception as e:
        print(f"❌ Erro ao salvar cookies: {e}")

def carregar_cookies():
    """Tenta carregar cookies salvos para pular o login."""
    if not os.path.exists("cookies.pkl"):
        return False
    try:
        driver.get("https://grupofleury.freshservice.com/")
        with open("cookies.pkl", "rb") as f:
            import pickle
            cookies = pickle.load(f)
            for cookie in cookies:
                driver.add_cookie(cookie)
        driver.refresh()
        time.sleep(5)
        return "dashboard" in driver.current_url.lower() or "tickets" in driver.current_url.lower()
    except Exception as e:
        print(f"⚠️ Erro ao carregar cookies: {e}")
        return False

def js_find(css_selector, timeout=30):
    """Busca elemento no contexto atual, default e em iframes recursivamente."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        # Tenta no contexto atual
        try:
            el = driver.execute_script(f'return document.querySelector("{css_selector}");')
            if el: return el
        except: pass
        
        # Tenta no default
        driver.switch_to.default_content()
        try:
            el = driver.execute_script(f'return document.querySelector("{css_selector}");')
            if el: return el
        except: pass
        
        # Tenta em iframes
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.frame(frame)
                el = driver.execute_script(f'return document.querySelector("{css_selector}");')
                if el: return el
            except: pass
            driver.switch_to.default_content()
            
        time.sleep(1)
    raise Exception(f"Elemento não encontrado via JS: {css_selector}")

def safe_click_js(css_selector):
    """Clica usando JS puro."""
    el = js_find(css_selector)
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(1.0 if not IS_CODESPACE else 2.5) # Mais tempo na nuvem
    driver.execute_script("arguments[0].click();", el)

def preencher_por_id(field_id, value):
    """By.ID é o único seletor estável nativo."""
    try:
        el = wait.until(EC.presence_of_element_located((By.ID, field_id)))
        driver.execute_script("arguments[0].value = '';", el)
        el.send_keys(str(value))
        print(f"    ✓ ID {field_id} preenchido.")
    except Exception as e:
        print(f"    ❌ Erro ID {field_id}: {e}")

def preencher_dropdown_js(css_selector, value):
    """Preenche dropdowns usando JS e eventos de mouse para máxima compatibilidade."""
    try:
        print(f"      -> Campo: {css_selector} | Valor: {value}")
        
        # 1. Limpa qualquer foco anterior e garante que o elemento existe
        driver.execute_script("if(document.activeElement) document.activeElement.blur();")
        time.sleep(1)
        el = js_find(css_selector)
        
        # 2. Abre o dropdown usando sequência de eventos de mouse (mais robusto que .click())
        driver.execute_script("""
            var el = arguments[0];
            el.scrollIntoView({block:'center'});
            
            function trigger(type) {
                var ev = new MouseEvent(type, {bubbles: true, cancelable: true, view: window});
                el.dispatchEvent(ev);
            }
            trigger('mousedown');
            trigger('mouseup');
            trigger('click');
            el.focus();
        """, el)
        time.sleep(1.5) 
        
        # 3. Localiza o input de busca (Freshservice costuma colocar no portal ou dentro do container)
        try:
            search_input = driver.execute_script("""
                var el = arguments[0];
                // Se o elemento clicado já for o input (Agente/Estado), usamos ele.
                if (el.tagName === 'INPUT') return el;
                
                // Busca em ordem de probabilidade
                var selectors = [
                    '.ember-power-select-search-input', 
                    '.ember-power-select-trigger input',
                    'input.ember-power-select-search-input',
                    'input:focus'
                ];
                for (var s of selectors) {
                    var found = document.querySelector(s);
                    if (found && found.id !== el.id) return found; 
                }
                return el; // Fallback
            """, el)
            
            if search_input:
                driver.execute_script("arguments[0].focus();", search_input)
                # Limpeza garantida
                search_input.send_keys(Keys.CONTROL + "a")
                search_input.send_keys(Keys.BACKSPACE)
                search_input.send_keys(str(value))
                time.sleep(1.5) # Espera carregar
            else:
                print("      ⚠️ Input não detectado.")
        except Exception as e:
            print(f"      ⚠️ Falha ao digitar: {e}")

        # 4. Seleciona a opção
        res = driver.execute_script("""
            var valNorm = arguments[0].normalize("NFKD").replace(/[\\u0300-\\u036f]/g, "").toUpperCase().trim();
            var options = document.querySelectorAll('.ember-power-select-option, li[role="option"]');
            
            if (options.length === 0) return "ERRO: Nenhuma opção encontrada no menu!";

            function clickOpt(opt) {
                opt.scrollIntoView({block:'center'});
                opt.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
                opt.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                opt.click();
                return true;
            }

            // Exato
            for (var opt of options) {
                var textNorm = opt.innerText.normalize("NFKD").replace(/[\\u0300-\\u036f]/g, "").toUpperCase().trim();
                if (textNorm === valNorm) {
                    if (clickOpt(opt)) return "Selecionado Exato: " + opt.innerText.trim();
                }
            }
            
            // Aproximação
            for (var opt of options) {
                var textNorm = opt.innerText.normalize("NFKD").replace(/[\\u0300-\\u036f]/g, "").toUpperCase().trim();
                if (textNorm.includes(valNorm)) {
                    if (valNorm === "RESOLVIDO" && textNorm.includes("FALSO")) continue;
                    if (clickOpt(opt)) return "Selecionado Por Aproximação: " + opt.innerText.trim();
                }
            }
            
            return "Opção '" + arguments[0] + "' não encontrada em " + options.length + " itens.";
        """, str(value))
        
        print(f"    ✓ {res}")
        driver.execute_script("if(document.activeElement) document.activeElement.blur();")
        time.sleep(0.5)
        return "Selecionado" in res
    except Exception as e:
        print(f"    ❌ Erro dropdown {css_selector}: {e}")
        return False

# ==============================
# FLUXOS DE NEGÓCIO
# ==============================

def capture_id():
    """Captura o ID do chamado criado."""
    time.sleep(5)
    match = re.search(r"/tickets/(\d+)", driver.current_url)
    if match: return f"SR-{match.group(1)}"
    try:
        el = driver.find_element(By.CSS_SELECTOR, "[data-test-id='ticket-human-display-id']")
        return el.text.strip()
    except: return None

def resolver_chamado(ticket_id, agente_nome):
    """Fase de fechamento do chamado via URL direta."""
    try:
        driver.switch_to.default_content()
        numeric_id = "".join(re.findall(r"\d+", str(ticket_id)))
        url_direta = f"https://grupofleury.freshservice.com/a/tickets/{numeric_id}?current_tab=details"
        
        print(f"  [FASE B] Aguardando 20s para estabilização antes de navegar...")
        time.sleep(20)
        
        print(f"  [FASE B] Navegando para {url_direta}...")
        driver.get(url_direta)
        time.sleep(20) 
        
        # 1. Clique na aba Resolução
        print("    └─ Abrindo aba Resolução...")
        driver.execute_script("""
            var tabs = document.querySelectorAll('.tab-title, span');
            for (var t of tabs) {
                if (t.innerText.trim() === 'Resolução') {
                    t.scrollIntoView({block:'center'});
                    t.click();
                    return "Aba Resolução clicada";
                }
            }
        """)
        time.sleep(2)

        # 2. Adicionar nota de resolução
        print("    └─ Abrindo campo de nota...")
        safe_click_js("button.resolution-summary-button")
        time.sleep(3) 
        
        print("    └─ Escrevendo nota...")
        try:
            sel_editor = "[contenteditable='true'].fr-element, .redactor-editor, [contenteditable='true']"
            editor = js_find(sel_editor, timeout=10)
            driver.execute_script("""
                arguments[0].focus();
                arguments[0].innerHTML = '<div>' + arguments[1] + '</div>';
                arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
            """, editor, VALORES_FIXOS["resolucao"])
            editor.send_keys(Keys.SPACE)
            time.sleep(1)
            
            print("    └─ Salvando nota (Guardar)...")
            driver.execute_script("""
                var buttons = document.querySelectorAll('button');
                for (var b of buttons) {
                    if (b.innerText.trim().includes('Guardar')) {
                        b.click();
                        break;
                    }
                }
            """)
            time.sleep(2)
        except Exception as e:
            print(f"      ⚠️ Falha nota: {e}")

        # 3. Propriedades (Lado Direito)
        print("    └─ Preenchendo propriedades cirurgicamente...")
        driver.execute_script("window.scrollTo(0,0); document.activeElement.blur();")
        time.sleep(3)

        # 3.1 AGENTE (Dinâmico)
        print(f"      └─ Campo Agente ({agente_nome})...")
        preencher_dropdown_js("input[id*='_responderId']", agente_nome)
        time.sleep(0.5)

        # 3.2 CÓDIGO DA RESOLUÇÃO
        print("      └─ Campo Código da Resolução...")
        preencher_dropdown_js("[aria-labelledby*='resolution_code'], [id*='resolution_code'] .ember-power-select-trigger", VALORES_FIXOS["cod_resolucao"])
        time.sleep(0.5)

        # 3.3 TIPO DE ATENDIMENTO
        print("      └─ Campo Tipo de Atendimento...")
        preencher_dropdown_js("[aria-labelledby*='tipo_de_atendimento'], [id*='tipo_de_atendimento'] .ember-power-select-trigger", VALORES_FIXOS["tipo_atendimento"])
        time.sleep(0.5)
        
        # 4. Botão Atualizar (Fase B parcial)
        print("    └─ Clicando em Atualizar (Agente/Códigos)...")
        time.sleep(0.5)
        driver.execute_script("""
            var btn = document.querySelector('button[data-test-id="ticket-property-form-submit"], #form-submit');
            if (btn) {
                btn.scrollIntoView({block:'center'});
                btn.click();
                return "Atualizado";
            }
        """)
        time.sleep(10) 
        return True
    except Exception as e:
        print(f"    ❌ Falha na resolução: {e}")
        return False

def fase_c_reforco(ticket_id):
    """Fase C: Reforço do Status Resolvido após espera."""
    try:
        print(f"  [FASE C] Aguardando 5s para reforço de status...")
        time.sleep(5)
        
        numeric_id = "".join(re.findall(r"\d+", str(ticket_id)))
        url_direta = f"https://grupofleury.freshservice.com/a/tickets/{numeric_id}?current_tab=details"
        
        print(f"  [FASE C] Recarregando chamado {ticket_id}...")
        driver.get(url_direta)
        time.sleep(8) # Espera carregar os detalhes
        
        print("      └─ Aplicando Status RESOLVIDO (Reforço)...")
        driver.execute_script("window.scrollTo(0,0); document.activeElement.blur();")
        time.sleep(1)
        
        # Preenche apenas o Estado agora
        preencher_dropdown_js(".ember-power-select-trigger:has([id*='_status']), [id*='_status'].ember-power-select-trigger, div[id*='status']", VALORES_FIXOS["estado"])
        time.sleep(2)
        
        print("    └─ Clicando em Atualizar Final...")
        driver.execute_script("""
            var btn = document.querySelector('button[data-test-id="ticket-property-form-submit"], #form-submit');
            if (btn) { btn.click(); return "Resolvido via Reforço"; }
        """)
        
        time.sleep(5)
        return True
    except Exception as e:
        print(f"    ❌ Falha na Fase C: {e}")
        return False

# ==============================
# LOOP PRINCIPAL
# ==============================

def main():
    print("🚀 Iniciando processamento...")

    # Tenta usar sessão anterior (cookies)
    if carregar_cookies():
        print("✨ Sessão restaurada com sucesso!")
    else:
        print("🔑 Login manual ou automático necessário...")
        if not fazer_login():
            if HEADLESS:
                print("❌ Falha no login automático e impossível interagir (Modo Headless).")
                return
            else:
                print("👋 Aguardando você fazer o login manualmente no navegador...")
                input("👉 Após logar e estiver na tela de chamados, aperte ENTER aqui para continuar...")
                salvar_cookies()
    
    # --- DIAGNÓSTICO DE IFRAME ---
    print("\n🔍 Detectando iframes...")
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    print(f"    Total de iframes: {len(iframes)}")
    
    for i, frame in enumerate(iframes):
        try:
            driver.switch_to.frame(frame)
            # Tenta achar o Melhor Horário pelo ID passado no HTML
            test_id = "requested_item_values_42_requested_item_value_attributes_cf_melhor_horario_para_contato_656425"
            el = driver.find_elements(By.ID, test_id)
            if el:
                print(f"    ✨ Elemento encontrado no iframe {i}! Nome: {frame.get_attribute('name')} ID: {frame.get_attribute('id')}")
                # Mantém no iframe se achou
                # break # Removido para continuar logando todos
            else:
                driver.switch_to.default_content()
        except:
            driver.switch_to.default_content()
    # -----------------------------

    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    df.columns = [normalizar(c) for c in df.columns]
    
    total = len(df)
    for i, row in df.iterrows():
        status_atual = str(row.get("STATUS DO CHAMADO", "")).strip().lower()
        agente_nome = str(row.get("AGENTE", VALORES_FIXOS["agente"])).strip()
        
        if "resolvido" in status_atual: continue
            
        print(f"\n🚀 Processando {i+1}/{total} - {row['LOCALIDADE']} (Agente: {agente_nome})...")
        
        try:
            # -----------------------------
            # FASE A: ABERTURA
            # -----------------------------
            driver.get("https://grupofleury.freshservice.com/support/catalog/items/42")
            time.sleep(3)
            
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for frame in iframes:
                try:
                    driver.switch_to.frame(frame)
                    if driver.find_elements(By.ID, "requested_item_values_42_requested_item_value_attributes_cf_melhor_horario_para_contato_656425"):
                        break
                    driver.switch_to.default_content()
                except: driver.switch_to.default_content()

            preencher_dropdown_js("#requested_item_values_42_requested_item_value_attributes_cf_melhor_horario_para_contato_656425", VALORES_FIXOS["melhor_horario"])
            preencher_por_id("42_c6df222f-d82c-443e-90f9-a22d163d6c1c", VALORES_FIXOS["telefone"])
            
            print("  └─ Localidade...")
            preencher_dropdown_js("input[aria-label*='Localidade']", str(row["LOCALIDADE"]))
            
            print("  └─ Ambiente...")
            preencher_dropdown_js("input[aria-label*='Ambiente']", VALORES_FIXOS["ambiente"])
            
            print("  └─ Equipamento...")
            preencher_dropdown_js("input[aria-label*='Equipamento']", VALORES_FIXOS["equipamento"])
            
            print("  └─ Tipo...")
            preencher_dropdown_js("input[aria-label*='Tipo de Solicitacao'], input[aria-label*='Tipo de Solicitacão']", VALORES_FIXOS["tipo"])
            
            preencher_por_id("42_32ce8dec-c1de-444d-9f01-aa93aa6bfd72", VALORES_FIXOS["patrimonio"])
            preencher_por_id("42_e4713da8-6469-46d2-ae18-91196e91d1f8", VALORES_FIXOS["maquina"])
            preencher_por_id("42_d6aef9f4-4a55-4380-a693-551a5f03ebc3", str(row["DESCRICAO"]))
            
            print("  └─ Clicando em Fazer Pedido...")
            time.sleep(0.5)
            safe_click_js("input.place-request-btn, .place-request-btn")
            time.sleep(1.5) 
            
            print("  └─ Solicitante...")
            sel_solicitante = "#requester_email, [name='requester_email'], input[placeholder='E-mail']"
            preencher_dropdown_js(sel_solicitante, str(row["SOLICITANTE"]))
            time.sleep(1) 
            
            # Verificação do Solicitante
            try:
                val_check = driver.execute_script(f"return document.querySelector(\"{sel_solicitante}\")?.value;")
                if not val_check or "@" not in val_check:
                    print("    ⚠️ Re-tentando Solicitante...")
                    el = js_find(sel_solicitante)
                    el.click()
                    el.send_keys(Keys.CONTROL + "a")
                    el.send_keys(Keys.BACKSPACE)
                    el.send_keys(str(row["SOLICITANTE"]))
                    time.sleep(1.5)
                    driver.execute_script("document.querySelector('li.ember-power-select-option')?.click();")
            except: pass

            print("  └─ Confirmando abertura...")
            try: 
                time.sleep(0.5)
                safe_click_js("button#confirm-request, #confirm-request")
            except: pass
            
            # -----------------------------
            # CAPTURA E FASE B: RESOLUÇÃO
            # -----------------------------
            ticket_id = capture_id()
            if ticket_id:
                print(f"    ✓ Criado: {ticket_id}")
                sheet.update_cell(i + 2, COL_CHAMADO, ticket_id)
                
                # Resolve usando o agente lido da planilha (Fase B)
                if resolver_chamado(ticket_id, agente_nome):
                    # Fase C: Reforço após 10s e refresh
                    if fase_c_reforco(ticket_id):
                        print(f"    ✓ Resolvido com Sucesso (Fase A+B+C): {ticket_id}")
                        sheet.update_cell(i + 2, COL_STATUS, "Chamado Resolvido")
                    else:
                        print(f"    ⚠️ Falha no reforço (Fase C).")
                else:
                    print("    ⚠️ Falha na resolução parcial (Fase B).")
            else:
                print("    ⚠️ Falha capturar ID.")
                    
        except Exception as ex:
            print(f"    ⚠️ Erro linha {i+1}: {ex}")

if __name__ == "__main__":
    main()
