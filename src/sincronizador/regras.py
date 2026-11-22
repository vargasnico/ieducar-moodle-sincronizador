"""Regras da integração (as mesmas do T1): o que deve existir no Moodle a partir do
estado de uma entidade do i-Educar. Funções puras, sem banco nem rede."""

EDITINGTEACHER, STUDENT = "editingteacher", "student"


def usuario_servidor(servidor_id: int) -> str:
    return f"ieducar-servidor-{servidor_id}"


def usuario_aluno(aluno_id: int) -> str:
    return f"ieducar-aluno-{aluno_id}"


def curso(turma_id: int, componente_id: int) -> str:
    """idnumber do curso no Moodle: um curso por turma × componente curricular."""
    return f"ieducar-turma-{turma_id}-componente-{componente_id}"


def _usuario(idnumber: str, username: str, nome: str, email: str | None, ativo: bool) -> dict:
    partes = nome.split() or [username]
    return {
        "idnumber": idnumber,
        "username": username,
        "firstname": partes[0],
        "lastname": " ".join(partes[1:]) or partes[0],
        # O Moodle exige e-mail; quem não tem (todos os alunos, na API) recebe um provisório.
        "email": email or f"{idnumber}@sem-email.invalid",
        # Ninguém é apagado no Moodle: quem sai é suspenso.
        "suspenso": not ativo,
    }


def professor(servidor: dict) -> tuple[dict, set[str]]:
    """Professor = servidor ativo com pelo menos um vínculo com turma no ano letivo.
    Devolve o usuário e os cursos em que ele deve estar como editingteacher."""
    eh_professor = servidor["ativo"] and bool(servidor["vinculos"])
    idnumber = usuario_servidor(servidor["servidor_id"])
    # Login pelo CPF (só números) ou, sem CPF, pelo código do servidor.
    username = servidor["cpf"] or f"servidor{servidor['servidor_id']}"
    usuario = _usuario(idnumber, username, servidor["nome"], servidor["email"], eh_professor)
    cursos = {curso(v["turma_id"], c) for v in servidor["vinculos"] for c in v["componentes"]}
    return usuario, cursos if eh_professor else set()


def aluno(dados: dict) -> tuple[dict, set[str]]:
    """Aluno ativo e enturmado: inscrito como student nos cursos dos componentes que
    cursa em cada turma (os da série, sem os de dispensa — o detector já os tirou)."""
    enturmado = dados["ativo"] and bool(dados["turmas"])
    idnumber = usuario_aluno(dados["aluno_id"])
    # O código do aluno nunca muda; a matrícula é renovada a cada ano.
    usuario = _usuario(idnumber, f"aluno{dados['aluno_id']}", dados["nome"], None, enturmado)
    cursos = {curso(t["turma_id"], c) for t in dados["turmas"] for c in t["componentes"]}
    return usuario, cursos if enturmado else set()


def cursos_da_turma(turma: dict, visivel: bool) -> list[dict]:
    """Um curso por componente da turma, na categoria do ano letivo."""
    ano, turma_id = turma["ano"], turma["turma_id"]
    return [
        {
            "idnumber": curso(turma_id, c["id"]),
            "shortname": f"{ano}-T{turma_id}-C{c['id']}",
            "fullname": f"{turma['nome']} – {c['nome']} ({ano})",
            "ano": ano,
            # Turma desativada ou componente retirado: o curso é ocultado, não apagado.
            "visivel": visivel,
        }
        for c in turma["componentes"]
    ]
