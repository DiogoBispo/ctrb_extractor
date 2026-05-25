# OCR - CTRB Extractor

Extrator de dados estruturados de documentos CTRB em PDF para JSON.

## Visão geral

<<<<<<< HEAD
O script [`ctrb_extractor.py`] processa CTRBs usando `pdfplumber` e organiza os dados em blocos:
=======
O script [`extrator/ctrb_extractor.py`] processa CTRBs usando `pdfplumber` e organiza os dados em blocos:
>>>>>>> 3464ffc (Adiciona suporte a argumentos de linha de comando e documentação ao README)

- `cabecalho`
- `contratante`
- `contratado`
- `servico_contratado`
- `veiculo`
- `motorista_1`
- `motorista_2`
- `valor_dos_servicos`
- `forma_de_pagamento`
- `observacoes`
- `rodape`
- `rpa` (quando existe 2ª página)

A saída é salva em arquivo JSON no mesmo diretório do script, no formato:

`CTRB_<IE>_<SERIE>_<NUMERO>.json`

## Requisitos

- Python 3.10+
- Dependências Python:
  - `pdfplumber`

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install pdfplumber
```

## Como executar

Na raiz do projeto:

```bash
<<<<<<< HEAD
python ctrb_extractor.py "caminho/arquivo1.pdf" "caminho/arquivo2.pdf"
=======
python extrator/ctrb_extractor.py "caminho/arquivo1.pdf" "caminho/arquivo2.pdf"
>>>>>>> 3464ffc (Adiciona suporte a argumentos de linha de comando e documentação ao README)
```

Exemplo real com os arquivos deste repositório:

```bash
<<<<<<< HEAD
python ctrb_extractor.py caminho/*.pdf
=======
python extrator/ctrb_extractor.py "caminho/*.pdf"
```

Processar todos os PDFs de um diretório (sem informar cada arquivo):

```bash
python extrator/ctrb_extractor.py --input-dir caminho/
```

Somente listar os arquivos que seriam processados:

```bash
python extrator/ctrb_extractor.py --input-dir caminho/ --dry-run
>>>>>>> 3464ffc (Adiciona suporte a argumentos de linha de comando e documentação ao README)
```

## Exemplo de estrutura de saída

```json
{
  "cabecalho": {
    "emitente_nome": "...",
    "cnpj": "...",
    "ie": "...",
    "rntrc": "...",
    "serie": "GYN",
    "numero": "004100-9",
    "data_hora_emissao": "dd/mm/aa hh:mm",
    "folha": "01/01",
    "origem": "...",
    "placa_resumo": "..."
  },
  "contratante": {},
  "contratado": {},
  "servico_contratado": {},
  "veiculo": {},
  "motorista_1": {},
  "motorista_2": {},
  "valor_dos_servicos": {},
  "forma_de_pagamento": {
    "adiantamento": {},
    "adiantamento_ccf_os": null,
    "saldo": null,
    "saldo_referencia": null,
    "por_conta_transportadora": {}
  },
  "observacoes": [],
  "rodape": {
    "emitente": null,
    "contratante_assinatura": null,
    "contratado_assinatura": null
  },
  "rpa": null
}
```

## Como o parser funciona

1. Extrai palavras e coordenadas do PDF (`extract_words`).
2. Agrupa por linhas lógicas com tolerância vertical (`Y_BIN`).
3. Divide seções por coordenadas Y fixas (headers).
4. Separa colunas por thresholds X (`X_COL1_MAX`, `X_COL2_MAX`).
5. Faz parsing de pares `chave:valor` com suporte a múltiplos pares por linha.
6. Normaliza chaves em `snake_case`.
7. Gera JSON final por documento.

## Estrutura do projeto

<<<<<<< HEAD
- [`ctrb_extractor.py`]: extrator principal e CLI
=======
- [`extrator/ctrb_extractor.py`]: extrator principal e CLI
>>>>>>> 3464ffc (Adiciona suporte a argumentos de linha de comando e documentação ao README)
- `caminho/`: PDFs e imagens de exemplo
