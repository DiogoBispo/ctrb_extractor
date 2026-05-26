#!/usr/bin/env python3
"""
CTRB PDF Extractor 
======================================
Extrai informações estruturadas de CTRBs e salva em JSON nomeado pelo IE do documento.

Uso:
    python ctrb_extractor.py arquivo1.pdf [arquivo2.pdf ...]

Saída:
    CTRB_<IE>_<SERIE>_<NUMERO>.json no mesmo diretório do script.
"""

import json
import re
import sys
import argparse
from pathlib import Path
from typing import Optional

import pdfplumber


# ---------------------------------------------------------------------------
# Constantes de layout — validadas em 4 CTRBs distintos 
# ---------------------------------------------------------------------------

# Linhas-âncora Y dos headers de seção (em pontos)
Y_HDR_CONTRATANTE = 113.3   # row: CONTRATANTE | CONTRATADO | SERVICO CONTRATADO
Y_HDR_VEICULO     = 215.4   # row: VEICULO | MOTORISTA 1 | MOTORISTA 2
Y_HDR_VALOR       = 291.9   # row: VALOR DOS SERVICOS | FORMA DE PAGAMENTO
Y_HDR_OBS         = 454.9   # OBSERVACOES (fixo em todos os docs)

# Thresholds X para separação de colunas (calibrados em coordenadas reais)
# Col1 (Contratante / Veículo)            : x < 195
# Col2 (Contratado / Motorista 1 / Forma) : 195 <= x < 375
# Col3 (Serviço / Motorista 2)            : x >= 375
X_COL1_MAX = 195.0
X_COL2_MAX = 375.0

# Split VALOR DOS SERVICOS (x < 232) vs FORMA DE PAGAMENTO (x >= 232)
X_VALOR_FORMA_SPLIT = 232.0

# Tolerância de agrupamento Y (palavras dentro de ±Y_BIN compartilham linha)
Y_BIN = 3


# ---------------------------------------------------------------------------
# Utilitários de layout
# ---------------------------------------------------------------------------

def words_to_lines(words: list) -> dict[int, list]:
    """Agrupa palavras em linhas lógicas por proximidade Y."""
    lines: dict[int, list] = {}
    for w in words:
        key = round(w["top"] / Y_BIN) * Y_BIN
        lines.setdefault(key, []).append(w)
    return {y: sorted(ws, key=lambda w: w["x0"]) for y, ws in sorted(lines.items())}


def filter_zone(
    lines: dict,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> dict[int, list]:
    """Retorna sub-dict de linhas dentro do retângulo X/Y especificado."""
    result = {}
    for y, words in lines.items():
        if not (y_min < y <= y_max):
            continue
        zone_words = [w for w in words if x_min <= w["x0"] < x_max]
        if zone_words:
            result[y] = zone_words
    return result


def normalize_key(raw: str) -> str:
    """Converte label do PDF em chave snake_case limpa."""
    key = raw.strip().lower()
    key = re.sub(r"[^a-z0-9\s]", " ", key)
    key = re.sub(r"\s+", "_", key).strip("_")
    return key


# ---------------------------------------------------------------------------
# Parser de chave:valor — lida com múltiplos KV por linha
# ---------------------------------------------------------------------------

def parse_kv_zone(lines: dict) -> dict:
    """
    Extrai pares chave:valor de um conjunto de linhas filtradas.

    Estratégia palavra-a-palavra com suporte a chaves compostas:
    - Palavra COM ':' inicia um novo par (KEY:VALUE ou KEY: separado).
    - Palavras SEM ':' antes de um par são acumuladas como prefixo da chave
      (ex: 'VALOR' + 'CTRB:' → chave 'valor_ctrb').
    - Palavras SEM ':' após um par são concatenadas ao valor corrente.
    - Uma mesma linha pode ter múltiplos pares (ex: MARCA:XX MODELO:YY).
    """
    result: dict[str, Optional[str]] = {}

    for y in sorted(lines):
        words = lines[y]
        current_key: Optional[str] = None
        value_parts: list[str] = []
        pending_prefix: list[str] = []   # palavras soltas antes do próximo ':'

        for w in words:
            token = w["text"]

            if ":" in token:
                # Persiste par anterior
                if current_key:
                    result[current_key] = _join_value(value_parts)

                k_raw, _, v_raw = token.partition(":")

                # Constrói chave completa: prefixo acumulado + token atual
                full_key = " ".join(pending_prefix + [k_raw]) if pending_prefix else k_raw
                current_key = normalize_key(full_key)
                value_parts = [v_raw] if v_raw else []
                pending_prefix = []
            else:
                if current_key is not None:
                    # Continua valor do par corrente
                    value_parts.append(token)
                else:
                    # Acumula como possível prefixo de chave composta
                    pending_prefix.append(token)

        # Persiste último par da linha
        if current_key:
            result[current_key] = _join_value(value_parts)

    return result


def _join_value(parts: list[str]) -> Optional[str]:
    """Junta partes do valor, limpa sufixos de desconto e R$."""
    val = " ".join(p for p in parts if p).strip()
    val = re.sub(r"\s*\(-\)\s*$", "", val).strip()
    return val if val else None


# ---------------------------------------------------------------------------
# Parsers por seção
# ---------------------------------------------------------------------------

def parse_cabecalho(lines: dict) -> dict:
    """
    Extrai campos do cabeçalho (acima de Y_HDR_CONTRATANTE).
    Usa lista ordenada por X para localizar valores ao lado dos labels,
    evitando confusão entre labels e valores em Y's ligeiramente diferentes.
    """
    cab: dict = {}

    # Empresa emitente — primeira linha do documento
    for y, words in lines.items():
        if y < 22:
            for w in words:
                if w["text"] == "MGBA":
                    cab["emitente_nome"] = " ".join(ww["text"] for ww in words
                                                     if ww["x0"] > 130)
                    break

    # CNPJ / IE / RNTRC / SERIE / NUMERO
    # Labels e valores ficam em Y's distintos (~58.8 vs ~56.3) mas próximos.
    # Solução: juntar todos os words do intervalo, ordenar por X, e pegar next.
    hdr_words = []
    for y, words in lines.items():
        if 50 <= y <= 65:
            hdr_words.extend(words)
    hdr_words.sort(key=lambda w: w["x0"])

    for i, w in enumerate(hdr_words):
        nxt = hdr_words[i + 1]["text"] if i + 1 < len(hdr_words) else ""
        if w["text"] == "CNPJ":
            cab["cnpj"] = nxt
        elif w["text"] == "IE":
            cab["ie"] = nxt
        elif w["text"] == "RNTRC":
            cab["rntrc"] = nxt
        elif w["text"] == "GYN" and nxt:
            cab["serie"] = "GYN"
            cab["numero"] = nxt

    # DATA/HORA EMISSAO (formato dd/mm/aa hh:mm), FOLHA (NN/NN)
    for y, words in lines.items():
        if y > 50:
            continue
        for w in words:
            if re.match(r"\d{2}/\d{2}/\d{2}$", w["text"]):
                # Próxima word é o horário
                idx = next((i for i, ww in enumerate(words) if ww is w), -1)
                hora = words[idx + 1]["text"] if idx + 1 < len(words) else ""
                cab["data_hora_emissao"] = f"{w['text']} {hora}".strip()
            if re.match(r"^\d{2}/\d{2}$", w["text"]) and "folha" not in cab:
                cab["folha"] = w["text"]

    # ORIGEM — valor à esquerda (x < 100), y ≈ 65–82
    for y, words in lines.items():
        if 65 <= y <= 82:
            origin_words = [w for w in words if w["x0"] < 100]
            val = " ".join(w["text"] for w in origin_words).strip()
            if val and val not in ("ORIGEM", "PLACAS", "BRASILIA/DF"[0:3]):
                cab["origem"] = val

    # PLACA DO VEÍCULO — linha y ≈ 88–108, valor à esquerda (x < 100)
    for y, words in lines.items():
        if 85 <= y <= 108:
            for w in words:
                if w["x0"] < 100 and re.match(r"^[A-Z]{3}\d", w["text"]):
                    cab["placa_resumo"] = w["text"]

    return cab


def parse_section_3col(
    lines: dict,
    y_start: float,
    y_end: float,
) -> tuple[dict, dict, dict]:
    """
    Divide um bloco de 3 colunas pelos thresholds X globais.
    Retorna (col1_kv, col2_kv, col3_kv).
    """
    col1 = filter_zone(lines, 0.0,       X_COL1_MAX, y_start, y_end)
    col2 = filter_zone(lines, X_COL1_MAX, X_COL2_MAX, y_start, y_end)
    col3 = filter_zone(lines, X_COL2_MAX, 9999.0,     y_start, y_end)
    return parse_kv_zone(col1), parse_kv_zone(col2), parse_kv_zone(col3)


def parse_valor_servicos(lines: dict, y_start: float, y_end: float) -> dict:
    """Extrai VALOR DOS SERVIÇOS (coluna esquerda do bloco VALOR/FORMA)."""
    zone = filter_zone(lines, 0.0, X_VALOR_FORMA_SPLIT, y_start, y_end)
    raw  = parse_kv_zone(zone)

    # Mantém apenas campos financeiros reconhecidos e limpa R$
    result = {}
    for k, v in raw.items():
        if any(t in k for t in ("valor", "inss", "irrf", "prev", "sest")):
            if v:
                v = re.sub(r"R\$\s*", "", v).strip()
                v = re.sub(r"\(-\)", "", v).strip()
            result[k] = v
    return result


def parse_forma_pagamento(lines: dict, y_start: float, y_end: float) -> dict:
    """
    Extrai FORMA DE PAGAMENTO do bloco compartilhado VALOR/FORMA.
    Processa linha a linha por padrão de label, não por zona X,
    pois o adiantamento tem label à esquerda e referência à direita.
    """
    result: dict = {
        "saldo": "",
        "saldo_referencia": "",
        "adiantamento": {
            "valor": "",
            "referencia": "",
            "condicao": "",
        },
        "adiantamento_ccf_os": "",
        "por_conta_transportadora": {},
    }

    pct_map = {
        "PEDAGIO":       "pedagio",
        "COMBUSTIVEL":   "combustivel",
        "OUTROS":        "outros",
        "FORNECEDOR":    "fornecedor",
        "VALE-PEDAGIO":  "vale_pedagio",
        "TARIFA":        "tarifa_saque_transf",   # TARIFA SAQUE/TRANSF
    }

    for y, words in lines.items():
        if not (y_start < y <= y_end):
            continue

        text = " ".join(w["text"] for w in words)

        # ADIANTAMENTO principal (não CCF)
        if re.match(r"ADIANTAMENTO:", text) and "CCF" not in text:
            m_val  = re.search(r"R\$\s*([\d.,]+)", text)
            m_ref  = re.search(r"(CPG\s+NL\s+\S+)", text)
            m_cond = re.search(r"\b(PAGAR\s+\S+|PAGO)\b", text)
            if m_val:
                result["adiantamento"]["valor"] = m_val.group(1).rstrip("(-)")
            if m_ref:
                result["adiantamento"]["referencia"] = m_ref.group(1)
            if m_cond:
                result["adiantamento"]["condicao"] = m_cond.group(1)

        # ADIANTAMENTO CCF/OS
        elif "CCF" in text and "ADIANTAMENTO" in text:
            m = re.search(r"R\$\s*([\d.,]+)", text)
            result["adiantamento_ccf_os"] = m.group(1).rstrip("(-)") if m else "0,00"

        # SALDO
        elif re.match(r"SALDO:", text):
            m_val = re.search(r"R\$\s*([\d.,]+)", text)
            m_ref = re.search(r"(CPG\s+NL\s+\S+)", text)
            if m_val:
                result["saldo"] = m_val.group(1)
            if m_ref:
                result["saldo_referencia"] = m_ref.group(1)

        # POR CONTA TRANSPORTADORA — sub-campos
        else:
            for pct_text, pct_key in pct_map.items():
                if pct_text in text:
                    m = re.search(r"R\$\s*([\d.,]+)", text)
                    result["por_conta_transportadora"][pct_key] = (
                        m.group(1) if m else "0,00"
                    )

    return result


def parse_observacoes(lines: dict, y_start: float, y_end: float) -> list[str]:
    """Extrai observações como lista, removendo o label e bullets."""
    obs = []
    for y, words in lines.items():
        if not (y_start < y < y_end):
            continue
        text = " ".join(w["text"] for w in words).strip()
        if not text or text == "OBSERVACOES":
            continue
        text = re.sub(r"^[-–]\s*", "", text)
        if text:
            obs.append(text)
    return obs


def parse_rodape(lines: dict, y_emitente: float) -> dict:
    """Extrai rodapé de assinaturas separando por coluna X."""
    labels = {"EMITENTE", "CONTRATANTE"}
    rodape: dict = {"emitente": [], "contratante_assinatura": None, "contratado_assinatura": None}

    for y, words in lines.items():
        if y < y_emitente + 3:
            continue

        col1 = [w for w in words if w["x0"] < X_COL1_MAX]
        col2 = [w for w in words if X_COL1_MAX <= w["x0"] < X_COL2_MAX]
        col3 = [w for w in words if w["x0"] >= X_COL2_MAX]

        t1 = " ".join(w["text"] for w in col1).strip()
        t2 = " ".join(w["text"] for w in col2).strip()
        t3 = " ".join(w["text"] for w in col3).strip()

        # Remove linhas de puro label
        if t1 and t1 not in labels and "CONTRATADO" not in t1:
            rodape["emitente"].append(t1)
        if t2 and t2 not in labels and "CONTRATADO" not in t2:
            rodape["contratante_assinatura"] = t2
        if t3 and "MOTORISTA" not in t3 and "CONTRATADO" not in t3:
            rodape["contratado_assinatura"] = t3

    rodape["emitente"] = " | ".join(rodape["emitente"]) or None
    return rodape


# ---------------------------------------------------------------------------
# Parser da página RPA (Recibo de Pagamento Autônomo)
# ---------------------------------------------------------------------------

def parse_rpa(page) -> dict:
    """Extrai dados da página RPA (página 2 do CTRB quando presente)."""
    words = page.extract_words()
    lines = words_to_lines(words)
    rpa: dict = {}

    # --- Colunas do RPA ---
    # Coluna esquerda (x < 380): dados do prestador e cálculos INSS
    # Coluna direita (x >= 380): cabeçalho, empresa, valor recebido, demonstrativo

    for y, wds in lines.items():
        text = " ".join(w["text"] for w in wds).strip()

        # Número do recibo (canto superior direito, y < 40)
        if y < 40:
            m = re.search(r"(GYN\s+[\d-]+)", text)
            if m:
                rpa["recibo_numero"] = m.group(1)

        # Empresa e CNPJ
        if "MGBA TRANSPORTES" in text and y < 80:
            rpa["empresa"] = "MGBA TRANSPORTES LTDA"
        m_cnpj = re.search(r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", text)
        if m_cnpj and y < 80:
            rpa["empresa_cnpj"] = m_cnpj.group(1)

        # Valor líquido recebido (à direita, "R$ XXXXX")
        if "IMPORTANCIA" in text or ("R$" in text and "CARGAS" in text):
            m = re.search(r"R\$\s*([\d.,]+)", text)
            if m:
                rpa["valor_recebido"] = m.group(1)

        # Valor por extenso
        if re.search(r"\(.*REAIS", text, re.IGNORECASE):
            rpa["valor_por_extenso"] = re.sub(r"[().]", "", text).strip()

        # Dados do prestador (coluna esquerda, y > 120)
        if y > 120:
            left_words = [w for w in wds if w["x0"] < 380]
            left_text  = " ".join(w["text"] for w in left_words).strip()

            prestador = rpa.setdefault("prestador", {})
            if "NOME:" in left_text and "EMPRESA" not in left_text and "RECEBI" not in left_text:
                v = left_text.split("NOME:", 1)[-1].strip()
                if v:
                    prestador["nome"] = v
            elif "ENDERECO:" in left_text:
                prestador["endereco"] = left_text.split("ENDERECO:", 1)[-1].strip()
            elif left_text.startswith("CPF:") and "RG:" not in left_text:
                prestador["cpf"] = left_text.split("CPF:", 1)[-1].strip().split()[0]
            elif "RG:" in left_text and "CPF:" not in left_text:
                prestador["rg"] = left_text.split("RG:", 1)[-1].strip().split()[0]
            elif "PIS/NIT:" in left_text:
                prestador["pis_nit"] = left_text.split("PIS/NIT:", 1)[-1].strip()
            elif re.match(r"^[A-Z]{4,}\s+[A-Z]{2}$", left_text):
                parts = left_text.split()
                prestador["municipio"] = parts[0]
                prestador["uf"]        = parts[1]

    # --- Demonstrativo financeiro (coluna direita x >= 380, y 120–220) ---
    demo_lines = filter_zone(lines, x_min=380.0, x_max=9999.0, y_min=120.0, y_max=220.0)
    demo_raw   = parse_kv_zone(demo_lines)

    # Normaliza chaves esperadas
    key_map = {
        "total_ctrb":        ("total_ctrb",),
        "irrf":              ("irrf",),
        "inss":              ("inss",),
        "prev_social":       ("previdencia_social", "prev_social"),
        "sest_senat":        ("sest_senat",),
        "total_descontos":   ("total_descontos",),
        "valor_liquido":     ("valor_liquido",),
    }

    demo_result: dict = {}
    for out_key, candidates in key_map.items():
        for cand in candidates:
            if cand in demo_raw:
                val = demo_raw[cand]
                if val:
                    val = re.sub(r"R\$\s*", "", val).strip()
                demo_result[out_key] = val
                break

    if demo_result:
        rpa["demonstrativo"] = demo_result

    return rpa


# ---------------------------------------------------------------------------
# Extrator principal
# ---------------------------------------------------------------------------

def extract_ctrb(pdf_path: str) -> dict:
    """Extrai todos os blocos de um CTRB e retorna dict estruturado."""
    with pdfplumber.open(pdf_path) as pdf:
        page  = pdf.pages[0]
        words = page.extract_words()
        lines = words_to_lines(words)

        # Detecta Y dinâmico do EMITENTE (varia 557–574 entre documentos)
        y_emitente = next(
            (y for y, wds in lines.items()
             if any(w["text"] == "EMITENTE" for w in wds)),
            557.0,
        )

        return {
            "cabecalho": parse_cabecalho(lines),

            **dict(zip(
                ["contratante", "contratado", "servico_contratado"],
                parse_section_3col(lines,
                                   y_start=Y_HDR_CONTRATANTE + 4,
                                   y_end=Y_HDR_VEICULO),
            )),

            **dict(zip(
                ["veiculo", "motorista_1", "motorista_2"],
                parse_section_3col(lines,
                                   y_start=Y_HDR_VEICULO + 4,
                                   y_end=Y_HDR_VALOR),
            )),

            "valor_dos_servicos": parse_valor_servicos(
                lines, y_start=Y_HDR_VALOR + 4, y_end=Y_HDR_OBS),

            "forma_de_pagamento": parse_forma_pagamento(
                lines, y_start=Y_HDR_VALOR + 4, y_end=Y_HDR_OBS),

            "observacoes": parse_observacoes(
                lines, y_start=Y_HDR_OBS, y_end=y_emitente),

            "rodape": parse_rodape(lines, y_emitente),

            "rpa": parse_rpa(pdf.pages[1]) if len(pdf.pages) > 1 else None,
        }


# ---------------------------------------------------------------------------
# Nomenclatura do arquivo de saída
# ---------------------------------------------------------------------------

def build_output_name(data: dict) -> str:
    """
    Gera nome do arquivo JSON com base no IE extraído do cabeçalho.
    Formato: CTRB_<IE>_<SERIE>_<NUMERO>.json
    """
    cab    = data.get("cabecalho", {})
    ie     = (cab.get("ie") or "SEM_IE").strip()
    serie  = (cab.get("serie") or "").strip()
    numero = (cab.get("numero") or "").strip().replace("/", "-")
    parts  = ["CTRB", ie]
    if serie:
        parts.append(serie)
    if numero:
        parts.append(numero)
    return "_".join(parts) + ".json"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _looks_like_split_path_token(token: str) -> bool:
    """Heurística para detectar token quebrado por falta de aspas no shell."""
    if "/" in token or token.endswith(".pdf"):
        return False
    if token in {"-", "_"}:
        return True
    if re.fullmatch(r"[A-Za-z0-9À-ÿ.-]+", token) and len(token) >= 2:
        return True
    return False


def _collect_input_pdfs(inputs: list[str], input_dir: Optional[str], pattern: str) -> list[Path]:
    """Coleta PDFs a partir de caminhos, globs e/ou diretório."""
    files: list[Path] = []

    for raw in inputs:
        p = Path(raw)

        # Caminho existente (absoluto ou relativo)
        if p.exists():
            if p.is_file() and p.suffix.lower() == ".pdf":
                files.append(p)
            continue

        # Permite glob explícito no argumento (ex.: pasta/*.pdf)
        has_glob = any(ch in raw for ch in "*?[]")
        if has_glob:
            files.extend(sorted(Path().glob(raw)))

    if input_dir:
        base = Path(input_dir)
        if base.exists() and base.is_dir():
            files.extend(sorted(base.glob(pattern)))

    # Remove duplicados preservando ordem
    unique: list[Path] = []
    seen: set[Path] = set()
    for p in files:
        rp = p.resolve()
        if rp not in seen and p.is_file() and p.suffix.lower() == ".pdf":
            unique.append(p)
            seen.add(rp)
    return unique


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extrai dados estruturados de CTRBs em PDF para JSON."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Arquivos PDF e/ou padrões glob (ex.: pasta/*.pdf).",
    )
    parser.add_argument(
        "--input-dir",
        dest="input_dir",
        help="Diretório para buscar PDFs automaticamente.",
    )
    parser.add_argument(
        "--pattern",
        default="*.pdf",
        help="Padrão de busca usado com --input-dir (default: *.pdf).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Somente lista os PDFs que seriam processados, sem extrair.",
    )
    args = parser.parse_args()

    if not args.inputs and not args.input_dir:
        parser.print_help()
        sys.exit(1)

    output_dir = Path(__file__).parent
    results    = []
    pdfs = _collect_input_pdfs(args.inputs, args.input_dir, args.pattern)

    if not pdfs:
        print("[ERRO] Nenhum PDF válido encontrado para processar.")
        sys.exit(1)

    if args.dry_run:
        print(f"{len(pdfs)} PDF(s) encontrado(s):")
        for p in pdfs:
            print(f"  - {p}")
        return

    # Aviso amigável para erro comum: path com espaços sem aspas.
    missing_inputs = [raw for raw in args.inputs if not Path(raw).exists() and not any(ch in raw for ch in "*?[]")]
    split_like = [tok for tok in missing_inputs if _looks_like_split_path_token(tok)]
    if missing_inputs and split_like:
        print(
            "[DICA] Detectei argumentos inválidos que parecem nomes de arquivo quebrados por espaço.\n"
            "       Se o caminho tiver espaços, use aspas.\n"
            "       Ex: python extrator/ctrb_extractor.py \"pasta/ARQUIVO COM ESPACO.pdf\""
        )

    for p in pdfs:
        print(f"\nProcessando: {p.name}")
        try:
            data = extract_ctrb(str(p))
        except Exception as exc:
            print(f"  [ERRO] {exc}")
            continue

        output_name = build_output_name(data)
        output_path = output_dir / output_name

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        cab    = data["cabecalho"]
        ie     = cab.get("ie", "?")
        serie  = cab.get("serie", "")
        numero = cab.get("numero", "")
        print(f"  IE: {ie} | Doc: {serie} {numero}")
        print(f"  → {output_path}")
        results.append(str(output_path))

    print(f"\n✓ {len(results)} arquivo(s) gerado(s).")


if __name__ == "__main__":
    main()
 
