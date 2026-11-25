import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, date

import streamlit as st


# ============================================================
# CONFIGURAÇÃO
# ============================================================

st.set_page_config(
    page_title="Sistema Hospitalar",
    page_icon="🏥",
    layout="wide",
)

BANCO = "hospital.db"

STATUS_AGUARDANDO = "AGUARDANDO TRIAGEM"
STATUS_CLASSIFICADO = "CLASSIFICADO"
STATUS_FINALIZADO = "FINALIZADO"


# ============================================================
# NÍVEIS DE RISCO
# MENOR NÚMERO = MAIOR PRIORIDADE
# ============================================================

NIVEIS = {
    "VERMELHO": 0,
    "LARANJA": 1,
    "AMARELO": 2,
    "VERDE": 3,
    "AZUL": 4,
}

ICONES = {
    "VERMELHO": "🔴",
    "LARANJA": "🟠",
    "AMARELO": "🟡",
    "VERDE": "🟢",
    "AZUL": "🔵",
}


# ============================================================
# BANCO
# ============================================================

@contextmanager
def conectar():
    """Abre a conexão, faz commit no fim e SEMPRE fecha,
    mesmo se ocorrer erro (rollback em caso de falha)."""

    conn = sqlite3.connect(BANCO)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def criar_tabelas():

    with conectar() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pacientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cpf TEXT UNIQUE NOT NULL,
                nome TEXT NOT NULL,
                nascimento TEXT NOT NULL,
                sexo TEXT,
                telefone TEXT,
                criado_em TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS atendimentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paciente_id INTEGER NOT NULL,
                chegada TEXT NOT NULL,
                queixa_principal TEXT,
                descricao_queixa TEXT,
                status TEXT NOT NULL,
                FOREIGN KEY (paciente_id) REFERENCES pacientes(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS triagens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                atendimento_id INTEGER UNIQUE NOT NULL,
                nivel_consciencia TEXT,
                intensidade_dor INTEGER,
                pressao_sistolica REAL,
                pressao_diastolica REAL,
                frequencia_cardiaca REAL,
                frequencia_respiratoria REAL,
                temperatura REAL,
                saturacao REAL,
                dificuldade_respiratoria INTEGER,
                sangramento INTEGER,
                convulsao INTEGER,
                desmaio INTEGER,
                trauma INTEGER,
                gestante INTEGER,
                uso_anticoagulante INTEGER,
                imunossuprimido INTEGER,
                comorbidades TEXT,
                medicamentos TEXT,
                observacoes TEXT,
                classificacao TEXT,
                reavaliacao_imediata INTEGER DEFAULT 0,
                modificador_prioridade INTEGER DEFAULT 0,
                criterios_protocolo TEXT,
                profissional TEXT,
                data_triagem TEXT,
                FOREIGN KEY (atendimento_id) REFERENCES atendimentos(id)
            )
        """)

        # Colunas novas da prioridade legal. Adicionadas desta forma
        # para que um banco hospital.db já existente seja atualizado
        # sem perder dados.
        garantir_coluna(conn, "pacientes", "deficiencia", "INTEGER DEFAULT 0")
        garantir_coluna(conn, "pacientes", "tea", "INTEGER DEFAULT 0")
        garantir_coluna(conn, "atendimentos", "lactante_crianca_colo", "INTEGER DEFAULT 0")


def garantir_coluna(conn, tabela, coluna, tipo):

    colunas = [linha["name"] for linha in conn.execute(f"PRAGMA table_info({tabela})")]

    if coluna not in colunas:
        conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")


criar_tabelas()


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def calcular_idade(nascimento, hoje=None):

    hoje = hoje or date.today()

    return (
        hoje.year
        - nascimento.year
        - ((hoje.month, hoje.day) < (nascimento.month, nascimento.day))
    )


def calcular_espera(chegada, agora=None):

    agora = agora or datetime.now()
    diferenca = agora - datetime.fromisoformat(chegada)

    return max(0, int(diferenca.total_seconds() // 60))


def limpar_cpf(cpf):
    """Mantém só os dígitos (remove ponto, traço, espaço etc.)."""
    return re.sub(r"\D", "", cpf or "")


def cpf_valido(cpf):
    """Confere tamanho e dígitos verificadores do CPF."""

    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False

    for i in (9, 10):
        soma = sum(int(cpf[j]) * (i + 1 - j) for j in range(i))
        digito = (soma * 10) % 11 % 10
        if digito != int(cpf[i]):
            return False

    return True


def formatar_cpf(cpf):
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"


def hora(iso):
    return datetime.fromisoformat(iso).strftime("%H:%M")


# ============================================================
# PRIORIDADE LEGAL
# Lei 10.048/2000, Estatuto da Pessoa Idosa (Lei 10.741/2003),
# Lei 13.146/2015 (LBI) e Lei 12.764/2012 (TEA).
#
# Na urgência ela NÃO passa por cima da classificação de risco:
# só desempata pacientes da MESMA cor.
#
# 2 = prioridade especial (80 anos ou mais)
# 1 = prioridade legal (60+, PcD, TEA, gestante, lactante ou
#     acompanhado de criança de colo)
# 0 = nenhuma
# ============================================================

def prioridade_legal(nascimento, deficiencia=0, tea=0, gestante=0, lactante_colo=0):
    """Retorna (nível, lista de motivos)."""

    idade = calcular_idade(date.fromisoformat(nascimento))

    motivos = []

    if idade >= 80:
        motivos.append("80+")
    elif idade >= 60:
        motivos.append("Idoso")

    if deficiencia:
        motivos.append("PcD")

    if tea:
        motivos.append("TEA")

    if gestante:
        motivos.append("Gestante")

    if lactante_colo:
        motivos.append("Lactante / criança de colo")

    if idade >= 80:
        nivel = 2
    elif motivos:
        nivel = 1
    else:
        nivel = 0

    return nivel, motivos


def texto_prioridade(motivos):
    return "♿ Prioridade legal: " + ", ".join(motivos) if motivos else ""


# Mensagens que sobrevivem ao st.rerun()
# (antes, o st.success era apagado pelo rerun e nunca aparecia)

def avisar(mensagem, tipo="success"):
    st.session_state["aviso"] = (tipo, mensagem)


def mostrar_aviso():
    aviso = st.session_state.pop("aviso", None)
    if aviso:
        tipo, mensagem = aviso
        getattr(st, tipo)(mensagem)


# ============================================================
# PACIENTES
# ============================================================

def buscar_paciente(cpf):

    with conectar() as conn:
        return conn.execute(
            "SELECT * FROM pacientes WHERE cpf = ?",
            (cpf,),
        ).fetchone()


def cadastrar_paciente(cpf, nome, nascimento, sexo, telefone, deficiencia=False, tea=False):

    with conectar() as conn:
        cursor = conn.execute("""
            INSERT INTO pacientes (
                cpf, nome, nascimento, sexo, telefone, deficiencia, tea, criado_em
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cpf,
            nome.strip(),
            nascimento.isoformat(),
            sexo,
            telefone.strip(),
            int(deficiencia),
            int(tea),
            datetime.now().isoformat(),
        ))
        return cursor.lastrowid


def atualizar_condicoes(paciente_id, deficiencia, tea):

    with conectar() as conn:
        conn.execute(
            "UPDATE pacientes SET deficiencia = ?, tea = ? WHERE id = ?",
            (int(deficiencia), int(tea), paciente_id),
        )


# ============================================================
# ATENDIMENTO
# ============================================================

def atendimento_em_aberto(paciente_id):
    """Evita abrir dois atendimentos simultâneos para o mesmo paciente."""

    with conectar() as conn:
        return conn.execute("""
            SELECT id, status
            FROM atendimentos
            WHERE paciente_id = ? AND status != ?
            ORDER BY chegada DESC
            LIMIT 1
        """, (paciente_id, STATUS_FINALIZADO)).fetchone()


def criar_atendimento(paciente_id, queixa, descricao, lactante_colo=False):

    with conectar() as conn:
        cursor = conn.execute("""
            INSERT INTO atendimentos (
                paciente_id, chegada, queixa_principal, descricao_queixa,
                lactante_crianca_colo, status
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            paciente_id,
            datetime.now().isoformat(),
            queixa,
            descricao.strip(),
            int(lactante_colo),
            STATUS_AGUARDANDO,
        ))
        return cursor.lastrowid


def buscar_atendimento(atendimento_id):

    with conectar() as conn:
        return conn.execute("""
            SELECT a.*, p.nome, p.cpf, p.nascimento, p.sexo, p.deficiencia, p.tea
            FROM atendimentos a
            JOIN pacientes p ON p.id = a.paciente_id
            WHERE a.id = ?
        """, (atendimento_id,)).fetchone()


def listar_aguardando_triagem():

    with conectar() as conn:
        return conn.execute("""
            SELECT
                a.id, a.chegada, a.queixa_principal, a.lactante_crianca_colo,
                p.nome, p.nascimento, p.deficiencia, p.tea
            FROM atendimentos a
            JOIN pacientes p ON p.id = a.paciente_id
            WHERE a.status = ?
            ORDER BY a.chegada
        """, (STATUS_AGUARDANDO,)).fetchall()


# ============================================================
# TRIAGEM
# ============================================================

COLUNAS_TRIAGEM = [
    "nivel_consciencia",
    "intensidade_dor",
    "pressao_sistolica",
    "pressao_diastolica",
    "frequencia_cardiaca",
    "frequencia_respiratoria",
    "temperatura",
    "saturacao",
    "dificuldade_respiratoria",
    "sangramento",
    "convulsao",
    "desmaio",
    "trauma",
    "gestante",
    "uso_anticoagulante",
    "imunossuprimido",
    "comorbidades",
    "medicamentos",
    "observacoes",
    "classificacao",
    "reavaliacao_imediata",
    "modificador_prioridade",
    "criterios_protocolo",
    "profissional",
]


def salvar_triagem(atendimento_id, dados):
    """Grava a triagem e muda o status numa única transação.

    Retorna False se o atendimento já não estava aguardando triagem
    (ex.: outro profissional classificou ao mesmo tempo). Antes, o
    INSERT OR REPLACE sobrescrevia a triagem anterior sem avisar.
    """

    with conectar() as conn:

        cursor = conn.execute("""
            UPDATE atendimentos
            SET status = ?
            WHERE id = ? AND status = ?
        """, (STATUS_CLASSIFICADO, atendimento_id, STATUS_AGUARDANDO))

        if cursor.rowcount == 0:
            return False

        colunas = ["atendimento_id"] + COLUNAS_TRIAGEM + ["data_triagem"]
        valores = (
            [atendimento_id]
            + [dados[c] for c in COLUNAS_TRIAGEM]
            + [datetime.now().isoformat()]
        )

        conn.execute(
            f"INSERT INTO triagens ({', '.join(colunas)}) "
            f"VALUES ({', '.join('?' * len(colunas))})",
            valores,
        )

    return True


# ============================================================
# MOTOR DE PRIORIDADE
# ============================================================

def chave_prioridade(item):
    """Python ordena do menor para o maior.

    Ordem dos critérios:
    1 - risco (menor número = mais grave)
    2 - reavaliação prioritária (1 passa à frente de 0)
    3 - prioridade legal (80+ > idoso/PcD/TEA/gestante/lactante > nenhuma)
    4 - modificador institucional (maior passa à frente)
    5 - chegada (quem chegou antes passa à frente)

    O critério "tempo de espera" era redundante com a chegada
    (quem chegou antes sempre espera mais), por isso foi unificado.
    """

    nivel = NIVEIS.get(item["classificacao"], len(NIVEIS))
    reavaliacao = item["reavaliacao_imediata"] or 0
    prioridade = item.get("prioridade_legal") or 0
    modificador = item["modificador_prioridade"] or 0

    return (
        nivel,
        -reavaliacao,
        -prioridade,
        -modificador,
        item["chegada"],
    )


# ============================================================
# FILA
# ============================================================

def buscar_fila():
    """Retorna apenas os pacientes JÁ classificados, ordenados por prioridade.

    Pacientes ainda não triados não entram na fila de prioridade:
    antes eles apareciam no fim, atrás até dos AZUIS, como se fossem
    os menos graves — o que não é verdade (ainda não foram avaliados).
    """

    with conectar() as conn:
        dados = conn.execute("""
            SELECT
                a.id AS atendimento_id,
                a.chegada,
                a.queixa_principal,
                a.status,
                a.lactante_crianca_colo,
                p.nome,
                p.nascimento,
                p.deficiencia,
                p.tea,
                t.gestante,
                t.classificacao,
                t.reavaliacao_imediata,
                t.modificador_prioridade,
                t.criterios_protocolo
            FROM atendimentos a
            JOIN pacientes p ON p.id = a.paciente_id
            JOIN triagens t ON t.atendimento_id = a.id
            WHERE a.status = ?
        """, (STATUS_CLASSIFICADO,)).fetchall()

    lista = []

    for linha in dados:

        item = dict(linha)

        item["prioridade_legal"], item["motivos_prioridade"] = prioridade_legal(
            item["nascimento"],
            item["deficiencia"],
            item["tea"],
            item["gestante"],
            item["lactante_crianca_colo"],
        )

        lista.append(item)

    lista.sort(key=chave_prioridade)

    return lista


# ============================================================
# FINALIZAR
# ============================================================

def finalizar_atendimento(atendimento_id):

    with conectar() as conn:
        cursor = conn.execute("""
            UPDATE atendimentos
            SET status = ?
            WHERE id = ? AND status = ?
        """, (STATUS_FINALIZADO, atendimento_id, STATUS_CLASSIFICADO))

        return cursor.rowcount > 0


# ============================================================
# INTERFACE
# ============================================================

st.title("🏥 Sistema de Atendimento Hospitalar")
st.caption("Protótipo de recepção, triagem e priorização de fila.")

menu = st.sidebar.radio(
    "Menu",
    ["Novo atendimento", "Realizar triagem", "Fila de atendimento"],
)

mostrar_aviso()


# ============================================================
# NOVO ATENDIMENTO
# ============================================================

if menu == "Novo atendimento":

    st.header("👤 Novo atendimento")

    cpf_digitado = st.text_input("CPF do paciente", max_chars=14)
    cpf = limpar_cpf(cpf_digitado)

    paciente = None

    if cpf_digitado:

        if not cpf_valido(cpf):

            st.error("CPF inválido. Confira os 11 dígitos.")

        else:

            paciente = buscar_paciente(cpf)

            if paciente:

                st.success("Paciente encontrado.")

                idade = calcular_idade(date.fromisoformat(paciente["nascimento"]))

                col1, col2 = st.columns(2)

                with col1:
                    st.write(f"**Nome:** {paciente['nome']}")
                    st.write(f"**CPF:** {formatar_cpf(paciente['cpf'])}")

                with col2:
                    st.write(f"**Idade:** {idade} anos")
                    st.write(f"**Sexo:** {paciente['sexo']}")

                _, motivos = prioridade_legal(
                    paciente["nascimento"], paciente["deficiencia"], paciente["tea"]
                )

                if motivos:
                    st.info(texto_prioridade(motivos))

                with st.expander("Atualizar condições de prioridade legal"):

                    with st.form("condicoes_paciente"):

                        nova_deficiencia = st.checkbox(
                            "Pessoa com deficiência",
                            value=bool(paciente["deficiencia"]),
                        )

                        novo_tea = st.checkbox(
                            "Transtorno do espectro autista (TEA)",
                            value=bool(paciente["tea"]),
                        )

                        atualizar = st.form_submit_button("Salvar condições")

                    if atualizar:
                        atualizar_condicoes(paciente["id"], nova_deficiencia, novo_tea)
                        avisar("Condições do paciente atualizadas.")
                        st.rerun()

            else:

                st.warning("Paciente ainda não cadastrado.")

                with st.form("cadastro_paciente"):

                    nome = st.text_input("Nome completo")

                    nascimento = st.date_input(
                        "Nascimento",
                        value=None,
                        min_value=date(1900, 1, 1),
                        max_value=date.today(),
                        format="DD/MM/YYYY",
                    )

                    sexo = st.selectbox(
                        "Sexo",
                        ["Masculino", "Feminino", "Outro", "Não informado"],
                    )

                    telefone = st.text_input("Telefone")

                    st.caption(
                        "Prioridade legal (idade 60+ e 80+ é calculada "
                        "automaticamente pela data de nascimento)"
                    )

                    deficiencia = st.checkbox("Pessoa com deficiência")
                    tea = st.checkbox("Transtorno do espectro autista (TEA)")

                    cadastrar = st.form_submit_button("Cadastrar paciente")

                if cadastrar:

                    if not nome.strip():
                        st.error("Informe o nome.")

                    elif nascimento is None:
                        st.error("Informe a data de nascimento.")

                    else:
                        try:
                            cadastrar_paciente(
                                cpf, nome, nascimento, sexo, telefone, deficiencia, tea
                            )
                            avisar("Paciente cadastrado.")
                            st.rerun()

                        except sqlite3.IntegrityError:
                            st.error("CPF já cadastrado.")

    # --------------------------------------------------------
    # ABERTURA DO ATENDIMENTO
    # --------------------------------------------------------

    if paciente:

        st.divider()
        st.subheader("📝 Abertura do atendimento")

        aberto = atendimento_em_aberto(paciente["id"])

        if aberto:

            st.warning(
                f"Este paciente já possui o atendimento #{aberto['id']} "
                f"em aberto ({aberto['status']}). Finalize-o antes de abrir outro."
            )

        else:

            with st.form("novo_atendimento"):

                queixa = st.selectbox(
                    "Queixa principal",
                    [
                        "Dor",
                        "Febre",
                        "Trauma",
                        "Problema respiratório",
                        "Sangramento",
                        "Mal-estar",
                        "Sintoma neurológico",
                        "Problema gastrointestinal",
                        "Problema urinário",
                        "Problema obstétrico",
                        "Outro",
                    ],
                )

                descricao = st.text_area("Descrição inicial")

                lactante_colo = st.checkbox(
                    "Lactante ou acompanhado(a) de criança de colo"
                )

                enviar = st.form_submit_button("Gerar atendimento")

            if enviar:

                atendimento_id = criar_atendimento(
                    paciente["id"], queixa, descricao, lactante_colo
                )

                avisar(
                    f"Atendimento #{atendimento_id} criado. "
                    "Paciente encaminhado para triagem."
                )
                st.rerun()


# ============================================================
# TRIAGEM
# ============================================================

elif menu == "Realizar triagem":

    st.header("🩺 Triagem")

    aguardando = listar_aguardando_triagem()

    if not aguardando:

        st.info("Nenhum paciente aguardando triagem.")

    else:

        por_id = {item["id"]: item for item in aguardando}

        # As opções são os IDs (estáveis). Antes, o texto da opção
        # incluía os minutos de espera, que mudavam a cada minuto:
        # o Streamlit "perdia" a seleção e podia trocar o paciente
        # no meio da triagem.
        atendimento_id = st.selectbox(
            "Paciente",
            options=list(por_id),
            format_func=lambda i: (
                f"#{i} - {por_id[i]['nome']} "
                f"(chegada {hora(por_id[i]['chegada'])})"
            ),
        )

        atendimento = buscar_atendimento(atendimento_id)

        idade = calcular_idade(date.fromisoformat(atendimento["nascimento"]))
        espera = calcular_espera(atendimento["chegada"])

        st.write(f"### {atendimento['nome']}")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.write(f"**Idade:** {idade}")

        with col2:
            st.write(f"**Sexo:** {atendimento['sexo']}")

        with col3:
            st.write(f"**Queixa:** {atendimento['queixa_principal']}")

        with col4:
            st.write(f"**Espera:** {espera} min")

        st.write(f"**Descrição:** {atendimento['descricao_queixa'] or '—'}")

        _, motivos = prioridade_legal(
            atendimento["nascimento"],
            atendimento["deficiencia"],
            atendimento["tea"],
            0,
            atendimento["lactante_crianca_colo"],
        )

        if motivos:
            st.info(
                texto_prioridade(motivos)
                + " — desempata apenas dentro da mesma cor de risco."
            )

        st.divider()
        st.subheader("Parâmetros da triagem")

        # O formulário tem uma chave por atendimento: se a seleção
        # mudar por qualquer motivo, o envio não é gravado no
        # paciente errado.
        with st.form(f"form_triagem_{atendimento_id}"):

            # =================================================
            # ESTADO GERAL
            # =================================================

            st.markdown("### Estado geral")

            nivel_consciencia = st.selectbox(
                "Nível de consciência",
                [
                    "Não informado",
                    "Alerta",
                    "Alterado",
                    "Sonolento",
                    "Responsivo a estímulo",
                    "Inconsciente",
                ],
            )

            intensidade_dor = st.slider(
                "Intensidade informada da dor",
                min_value=0,
                max_value=10,
                value=0,
            )

            # =================================================
            # SINAIS VITAIS
            # Campo vazio = não aferido (gravado como NULL).
            # Antes o padrão era 0, e "saturação 0" ficava
            # registrado como se tivesse sido medido.
            # =================================================

            st.markdown("### Sinais vitais")
            st.caption("Deixe em branco o que não foi aferido.")

            col1, col2 = st.columns(2)

            with col1:

                pressao_sistolica = st.number_input(
                    "Pressão sistólica (mmHg)",
                    min_value=0.0, max_value=300.0, value=None, step=1.0,
                )

                frequencia_cardiaca = st.number_input(
                    "Frequência cardíaca (bpm)",
                    min_value=0.0, max_value=300.0, value=None, step=1.0,
                )

                temperatura = st.number_input(
                    "Temperatura (°C)",
                    min_value=25.0, max_value=45.0, value=None, step=0.1,
                )

            with col2:

                pressao_diastolica = st.number_input(
                    "Pressão diastólica (mmHg)",
                    min_value=0.0, max_value=250.0, value=None, step=1.0,
                )

                frequencia_respiratoria = st.number_input(
                    "Frequência respiratória (irpm)",
                    min_value=0.0, max_value=100.0, value=None, step=1.0,
                )

                saturacao = st.number_input(
                    "Saturação (%)",
                    min_value=0.0, max_value=100.0, value=None, step=1.0,
                )

            # =================================================
            # SINAIS / CONTEXTO
            # =================================================

            st.markdown("### Outros parâmetros")

            col1, col2 = st.columns(2)

            with col1:
                dificuldade_respiratoria = st.checkbox("Dificuldade respiratória")
                sangramento = st.checkbox("Sangramento")
                convulsao = st.checkbox("Convulsão")
                desmaio = st.checkbox("Desmaio")

            with col2:
                trauma = st.checkbox("Trauma")
                gestante = st.checkbox("Gestante")
                uso_anticoagulante = st.checkbox("Uso de anticoagulante")
                imunossuprimido = st.checkbox("Imunossuprimido")

            comorbidades = st.text_area("Comorbidades")
            medicamentos = st.text_area("Medicamentos em uso")
            observacoes = st.text_area("Observações clínicas")

            st.divider()

            # =================================================
            # CLASSIFICAÇÃO
            # =================================================

            st.markdown("### Classificação pelo profissional")

            st.warning(
                "A classificação deve seguir o protocolo "
                "oficial adotado pela instituição."
            )

            classificacao = st.selectbox(
                "Nível de risco",
                list(NIVEIS),
                index=None,
                placeholder="Selecione a classificação",
                format_func=lambda n: f"{ICONES[n]} {n}",
            )

            reavaliacao_imediata = st.checkbox(
                "Reavaliação prioritária indicada pelo profissional"
            )

            modificador_prioridade = st.select_slider(
                "Modificador institucional de prioridade",
                options=[0, 1, 2, 3],
                value=0,
            )

            st.caption("0 = nenhum | 1 = baixo | 2 = médio | 3 = alto")

            criterios_protocolo = st.text_area(
                "Critérios do protocolo acionados",
                placeholder=(
                    "Ex.: CR-01, CR-04, "
                    "ou descrição conforme protocolo institucional"
                ),
            )

            profissional = st.text_input("Profissional responsável")

            salvar = st.form_submit_button(
                f"Salvar classificação de {atendimento['nome']}",
                type="primary",
            )

        if salvar:

            erros = []

            if classificacao is None:
                erros.append("Informe a classificação.")

            if not profissional.strip():
                erros.append("Informe o profissional responsável.")

            if (
                pressao_sistolica is not None
                and pressao_diastolica is not None
                and pressao_diastolica >= pressao_sistolica
            ):
                erros.append(
                    "A pressão diastólica deve ser menor que a sistólica."
                )

            if erros:

                for erro in erros:
                    st.error(erro)

            else:

                dados = {
                    "nivel_consciencia": nivel_consciencia,
                    "intensidade_dor": intensidade_dor,
                    "pressao_sistolica": pressao_sistolica,
                    "pressao_diastolica": pressao_diastolica,
                    "frequencia_cardiaca": frequencia_cardiaca,
                    "frequencia_respiratoria": frequencia_respiratoria,
                    "temperatura": temperatura,
                    "saturacao": saturacao,
                    "dificuldade_respiratoria": int(dificuldade_respiratoria),
                    "sangramento": int(sangramento),
                    "convulsao": int(convulsao),
                    "desmaio": int(desmaio),
                    "trauma": int(trauma),
                    "gestante": int(gestante),
                    "uso_anticoagulante": int(uso_anticoagulante),
                    "imunossuprimido": int(imunossuprimido),
                    "comorbidades": comorbidades.strip(),
                    "medicamentos": medicamentos.strip(),
                    "observacoes": observacoes.strip(),
                    "classificacao": classificacao,
                    "reavaliacao_imediata": int(reavaliacao_imediata),
                    "modificador_prioridade": modificador_prioridade,
                    "criterios_protocolo": criterios_protocolo.strip(),
                    "profissional": profissional.strip(),
                }

                if salvar_triagem(atendimento_id, dados):
                    avisar(f"Triagem de {atendimento['nome']} registrada.")
                else:
                    avisar(
                        "Este atendimento já havia sido triado por outro "
                        "profissional. Nada foi alterado.",
                        "warning",
                    )

                st.rerun()


# ============================================================
# FILA
# ============================================================

elif menu == "Fila de atendimento":

    st.header("🚨 Fila por prioridade")

    if st.button("🔄 Atualizar fila"):
        st.rerun()

    fila = buscar_fila()
    aguardando = listar_aguardando_triagem()
    agora = datetime.now()

    if not fila:

        st.info("Nenhum paciente classificado na fila.")

    for posicao, paciente in enumerate(fila, start=1):

        idade = calcular_idade(date.fromisoformat(paciente["nascimento"]))
        espera = calcular_espera(paciente["chegada"], agora)
        classificacao = paciente["classificacao"]

        with st.container(border=True):

            col1, col2, col3, col4 = st.columns([0.5, 2, 1.5, 1.5])

            with col1:
                st.markdown(f"# {posicao}º")

            with col2:
                st.markdown(f"### {paciente['nome']}")
                st.write(f"Idade: {idade}")
                st.write(f"Queixa: {paciente['queixa_principal']}")

            with col3:
                st.write("**Classificação**")
                st.write(f"{ICONES.get(classificacao, '')} {classificacao}")
                st.write(f"Espera: {espera} min")

            with col4:

                if paciente["reavaliacao_imediata"]:
                    st.error("REAVALIAÇÃO PRIORITÁRIA")

                if paciente["motivos_prioridade"]:
                    st.info(texto_prioridade(paciente["motivos_prioridade"]))

                st.write(f"Modificador: {paciente['modificador_prioridade'] or 0}")

                if paciente["criterios_protocolo"]:
                    st.caption(paciente["criterios_protocolo"])

            if st.button(
                "Chamar / finalizar",
                key=f"finalizar_{paciente['atendimento_id']}",
            ):

                if finalizar_atendimento(paciente["atendimento_id"]):
                    avisar(f"Atendimento de {paciente['nome']} finalizado.")
                else:
                    avisar("Este atendimento já havia sido finalizado.", "warning")

                st.rerun()

    # --------------------------------------------------------
    # AINDA NÃO TRIADOS (fora da ordenação por risco)
    # --------------------------------------------------------

    if aguardando:

        st.divider()
        st.subheader(f"⏳ Aguardando triagem ({len(aguardando)})")
        st.caption("Ainda sem classificação de risco — não entram na fila acima.")

        for item in aguardando:

            _, motivos = prioridade_legal(
                item["nascimento"],
                item["deficiencia"],
                item["tea"],
                0,
                item["lactante_crianca_colo"],
            )

            selo = f" · ♿ {', '.join(motivos)}" if motivos else ""

            st.write(
                f"#{item['id']} - **{item['nome']}** · "
                f"{item['queixa_principal']} · "
                f"espera {calcular_espera(item['chegada'], agora)} min"
                f"{selo}"
            )
