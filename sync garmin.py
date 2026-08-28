#!/usr/bin/env python3
"""
Sincroniza dados do Garmin Connect com o Supabase (schema `saude`).

Princípio central: o Garmin nunca sobrescreve o que você digitou na mão.
Campos manuais (kcal, proteína, água, cafeína, treino, checklist, crises)
são preservados. O script só preenche o que o relógio mede melhor que você:
sono, frequência cardíaca de repouso e, quando disponível, peso.

Uso:
    python sync_garmin.py              # ontem e hoje
    python sync_garmin.py --dias 7     # últimos 7 dias
    python sync_garmin.py --data 2026-08-26
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from garminconnect import Garmin
from supabase import create_client

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("garmin-sync")

# ----------------------------------------------------------------------
# Configuração
# ----------------------------------------------------------------------

GARMIN_EMAIL = os.getenv("GARMIN_EMAIL")
GARMIN_SENHA = os.getenv("GARMIN_SENHA")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
USER_ID = os.getenv("USER_ID")

# Pasta onde o token de sessão do Garmin fica guardado, para não
# refazer login (e disparar MFA) a cada execução.
TOKEN_DIR = os.getenv("GARMIN_TOKEN_DIR", os.path.expanduser("~/.garminconnect"))

OBRIGATORIAS = {
    "GARMIN_EMAIL": GARMIN_EMAIL,
    "GARMIN_SENHA": GARMIN_SENHA,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_SERVICE_KEY": SUPABASE_SERVICE_KEY,
    "USER_ID": USER_ID,
}


def checar_config() -> None:
    faltando = [k for k, v in OBRIGATORIAS.items() if not v]
    if faltando:
        log.error("Variáveis de ambiente ausentes: %s", ", ".join(faltando))
        log.error("Copie .env.example para .env e preencha.")
        sys.exit(1)


# ----------------------------------------------------------------------
# Garmin
# ----------------------------------------------------------------------


def conectar_garmin() -> Garmin:
    """Reaproveita a sessão salva; só faz login completo quando necessário."""
    os.makedirs(TOKEN_DIR, exist_ok=True)
    api = Garmin(GARMIN_EMAIL, GARMIN_SENHA)
    try:
        api.login(TOKEN_DIR)
        log.info("Sessão do Garmin reaproveitada.")
    except Exception:
        log.info("Fazendo login novo no Garmin…")
        api.login()
        try:
            api.garth.dump(TOKEN_DIR)
        except Exception as e:  # não é fatal
            log.warning("Não consegui salvar o token: %s", e)
    return api


def coletar_dia(api: Garmin, dia: date) -> dict:
    """Extrai o que interessa de um dia. Cada bloco falha isolado."""
    iso = dia.isoformat()
    dados: dict = {}

    # --- sono ---
    try:
        sono = api.get_sleep_data(iso) or {}
        diario = sono.get("dailySleepDTO") or {}
        segundos = diario.get("sleepTimeSeconds")
        if segundos:
            dados["sono_min"] = round(segundos / 60)
    except Exception as e:
        log.warning("%s  sono indisponível (%s)", iso, e)

    # --- frequência cardíaca de repouso ---
    try:
        fc = api.get_rhr_day(iso) or {}
        metricas = (fc.get("allMetrics") or {}).get("metricsMap") or {}
        serie = metricas.get("WELLNESS_RESTING_HEART_RATE") or []
        if serie and serie[0].get("value"):
            dados["fc_repouso"] = int(serie[0]["value"])
    except Exception as e:
        log.warning("%s  FC de repouso indisponível (%s)", iso, e)

    # --- peso (só se você pesar em balança sincronizada) ---
    try:
        peso = api.get_body_composition(iso) or {}
        registros = peso.get("dateWeightList") or []
        if registros and registros[0].get("weight"):
            dados["peso_kg"] = round(registros[0]["weight"] / 1000, 1)
    except Exception as e:
        log.debug("%s  peso indisponível (%s)", iso, e)

    return dados


# ----------------------------------------------------------------------
# Supabase
# ----------------------------------------------------------------------


def gravar(sb, dia: date, novos: dict) -> str:
    """
    Escreve sem destruir. Regra:
      - sono_min e fc_repouso: o Garmin manda, porque mede melhor.
      - peso_kg: só preenche se ainda estiver vazio (você usa a Omron).
      - qualquer outro campo: nunca tocado.
    """
    iso = dia.isoformat()
    if not novos:
        return "sem dados"

    atual = (
        sb.table("sd_registros_diarios")
        .select("*")
        .eq("user_id", USER_ID)
        .eq("data", iso)
        .execute()
    )
    existente = atual.data[0] if atual.data else None

    payload = {"user_id": USER_ID, "data": iso}
    mudou = []

    for campo in ("sono_min", "fc_repouso"):
        if campo in novos and (not existente or existente.get(campo) != novos[campo]):
            payload[campo] = novos[campo]
            mudou.append(campo)

    if "peso_kg" in novos and (not existente or existente.get("peso_kg") is None):
        payload["peso_kg"] = novos["peso_kg"]
        mudou.append("peso_kg")

    if not mudou:
        return "já atualizado"

    sb.table("sd_registros_diarios").upsert(payload, on_conflict="user_id,data").execute()
    return "gravado: " + ", ".join(mudou)


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(description="Sincroniza Garmin → Supabase")
    p.add_argument("--dias", type=int, default=2, help="quantos dias para trás (padrão: 2)")
    p.add_argument("--data", type=str, help="uma data específica, formato AAAA-MM-DD")
    args = p.parse_args()

    checar_config()

    if args.data:
        dias = [datetime.strptime(args.data, "%Y-%m-%d").date()]
    else:
        hoje = date.today()
        dias = [hoje - timedelta(days=i) for i in range(args.dias)]

    api = conectar_garmin()
    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    erros = 0
    for dia in sorted(dias):
        try:
            dados = coletar_dia(api, dia)
            resultado = gravar(sb, dia, dados)
            resumo = " · ".join(f"{k}={v}" for k, v in dados.items()) or "nada"
            log.info("%s  %s  [%s]", dia.isoformat(), resultado, resumo)
        except Exception as e:
            erros += 1
            log.error("%s  falhou: %s", dia.isoformat(), e)

    if erros:
        log.error("Concluído com %d erro(s).", erros)
        sys.exit(1)
    log.info("Concluído sem falhas.")


if __name__ == "__main__":
    main()
