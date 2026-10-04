#!/bin/sh
set -e
if [ ! -f "/dados/_resumo_geracao.json" ]; then
  echo "[seed] gerando dados (escala=${ESCALA:-1.0})..."
  python gerar_dados.py
else
  echo "[seed] dados já gerados; pulando geração"
fi
python carregar.py
