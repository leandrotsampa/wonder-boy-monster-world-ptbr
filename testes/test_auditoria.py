"""Auditoria de referências absolutas ao texto (guarda contra texto fora da realocação)."""

from pathlib import Path

import pytest
import yaml

pytest.importorskip("capstone")

from ferramentas.script.auditoria import referencias_absolutas  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent


def test_referencias_sinteticas():
    # lea $21000.l,a0 ; rts
    rom = bytes.fromhex("41F900021000" "4E75")
    assert referencias_absolutas(rom, 0x21000, 0x22000, regioes=[(0, len(rom))]) == [(2, 0x21000)]
    assert referencias_absolutas(rom, 0x22000, 0x23000, regioes=[(0, len(rom))]) == []


def test_referencias_rom(rom_base):
    cfg = yaml.safe_load((RAIZ / "config" / "texto.yaml").read_text(encoding="utf-8"))
    raizes = set(cfg["raizes_extra"])
    ignoradas = set()
    for item in cfg["referencias_ignoradas"]:
        assert str(item["motivo"]).strip(), f"sem justificativa: {item}"
        ignoradas.add((item["end"], item["valor"]))
    achadas = referencias_absolutas(rom_base, 0x1DD94, 0x22460)
    faltando = [(hex(e), hex(v)) for e, v in achadas if v not in raizes and (e, v) not in ignoradas]
    assert not faltando, f"referências não classificadas: {faltando}"


def test_referencias_ram_sinteticas():
    """Endereços da RAM ($FF0000-$FFFFFF): absoluto .w (estendido com sinal), .l (com os
    espelhos $E0-$FF) e imediato carregado em registrador de endereço; a faixa é dada em
    deslocamentos de 16 bits a partir de $FF0000."""
    from ferramentas.script.auditoria import referencias_ram

    rom = bytes.fromhex(
        "47F88CE0"        # 0x00 lea $8CE0.w,a3          -> $FF8CE0
        "41F900FF8CF0"    # 0x04 lea $FF8CF0.l,a0
        "207C00E08CE4"    # 0x0A movea.l #$E08CE4,a0     (espelho)
        "41F80CE0"        # 0x10 lea $0CE0.w,a0          -> ROM, não RAM
        "303C8CE0"        # 0x14 move.w #$8CE0,d0        -> imediato em dado: ignorado
        "41FA8CE0"        # 0x18 lea (pc): ROM
        "4E75")
    regioes = [(0, len(rom))]
    assert referencias_ram(rom, 0x8CE0, 0x8D00, regioes=regioes) == [0x00, 0x04, 0x0A]
    assert referencias_ram(rom, 0x8CF0, 0x8CF1, regioes=regioes) == [0x04]
    assert referencias_ram(rom, 0x0CE0, 0x0CE1, regioes=regioes) == []
