import pytest

from ferramentas.textos import (Entrada, ErroTextos, carregar_textos,
                                carregar_todos, mesclar, salvar_textos)


def _yaml(tmp_path, nome, conteudo):
    arq = tmp_path / nome
    arq.write_text(conteudo, encoding="utf-8")
    return arq


def test_salvar_carregar_acentos(tmp_path):
    arq = tmp_path / "t.yaml"
    e = Entrada(id="a", en="Hi", pt="Olá, ação!", status="traduzido")
    salvar_textos(arq, [e])
    assert "ação".encode("utf-8") in arq.read_bytes()
    assert rb"\u" not in arq.read_bytes()
    assert carregar_textos(arq) == [e]


def test_nota_vazia_nao_gravada(tmp_path):
    arq = tmp_path / "t.yaml"
    salvar_textos(arq, [Entrada(id="a", en="Hi")])
    assert "nota" not in arq.read_text(encoding="utf-8")


def test_id_duplicado(tmp_path):
    arq = _yaml(tmp_path, "t.yaml", "- {id: x, en: A}\n- {id: x, en: B}\n")
    with pytest.raises(ErroTextos, match="x"):
        carregar_textos(arq)


def test_status_invalido(tmp_path):
    arq = _yaml(tmp_path, "t.yaml", "- {id: y, en: A, pt: B, status: pronto}\n")
    with pytest.raises(ErroTextos, match="y"):
        carregar_textos(arq)


def test_traduzido_sem_pt(tmp_path):
    arq = _yaml(tmp_path, "t.yaml", "- {id: z, en: A, status: traduzido}\n")
    with pytest.raises(ErroTextos, match="z"):
        carregar_textos(arq)


def test_campo_ausente(tmp_path):
    arq = _yaml(tmp_path, "t.yaml", "- {id: w}\n")
    with pytest.raises(ErroTextos, match="w"):
        carregar_textos(arq)


def test_yaml_invalido(tmp_path):
    arq = _yaml(tmp_path, "t.yaml", "- {id: [\n")
    with pytest.raises(ErroTextos, match="t.yaml"):
        carregar_textos(arq)


def test_arquivo_vazio(tmp_path):
    assert carregar_textos(_yaml(tmp_path, "t.yaml", "")) == []


def test_mesclar_preserva_traducao():
    ex = [Entrada(id="a", en="Hi", pt="Oi", status="revisado", nota="ok")]
    r = mesclar(ex, [Entrada(id="a", en="Hi")])
    assert r == ex


def test_mesclar_original_mudou():
    ex = [Entrada(id="a", en="Hi", pt="Oi", status="revisado")]
    r = mesclar(ex, [Entrada(id="a", en="Hello")])
    assert r[0].en == "Hello" and r[0].pt == "Oi"
    assert r[0].status == "pendente" and "[original mudou]" in r[0].nota


def test_mesclar_novo_e_orfao():
    ex = [Entrada(id="velho", en="X", pt="Y", status="traduzido")]
    r = mesclar(ex, [Entrada(id="novo", en="N")])
    assert [e.id for e in r] == ["novo", "velho"]
    assert r[0].status == "pendente"
    assert "[órfão]" in r[1].nota and r[1].pt == "Y"


def test_duplicado_entre_arquivos(tmp_path):
    _yaml(tmp_path, "a.yaml", "- {id: x, en: A}\n")
    _yaml(tmp_path, "b.yaml", "- {id: x, en: B}\n")
    with pytest.raises(ErroTextos, match="x"):
        carregar_todos(tmp_path)


def test_carregar_todos(tmp_path):
    _yaml(tmp_path, "a.yaml", "- {id: x, en: A}\n")
    assert list(carregar_todos(tmp_path)) == ["a"]
    assert carregar_todos(tmp_path / "nao_existe") == {}
